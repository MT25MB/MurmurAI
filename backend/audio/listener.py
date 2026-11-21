"""Real-time local voice listener.

Captures 16 kHz mono microphone audio, detects speech start/end with webrtcvad
(silero-vad optional), and transcribes each utterance in-memory with
faster-whisper. Zero cloud dependencies.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

import numpy as np

try:  # pragma: no cover - platform optional
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None  # type: ignore

try:  # pragma: no cover - platform optional
    import webrtcvad
except ImportError:  # pragma: no cover
    webrtcvad = None  # type: ignore

try:  # pragma: no cover - platform optional
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover
    WhisperModel = None  # type: ignore

logger = logging.getLogger("murmur_ai.audio.listener")

SAMPLE_RATE = 16000
FRAME_MS = 30  # webrtcvad wants 10/20/30 ms frames
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480 samples @16k
SILENCE_END_MS = 800  # end-of-utterance after this much silence
MAX_UTTERANCE_S = 30  # hard cap on a single utterance


class VoiceListener:
    """Streaming microphone listener with VAD segmentation and local STT."""

    def __init__(
        self,
        model_name: str = "base.en",
        compute_type: str = "int8",
        device: Optional[int] = None,
        silence_ms: int = SILENCE_END_MS,
        on_utterance: Optional[Callable[[str], None]] = None,
    ):
        if sd is None:
            raise RuntimeError(
                "sounddevice is not installed. Run: pip install sounddevice"
            )
        if webrtcvad is None:
            raise RuntimeError(
                "webrtcvad2 is not installed. Run: pip install webrtcvad2"
            )
        if WhisperModel is None:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            )

        self.model_name = model_name
        self.compute_type = compute_type
        self.device = device
        self.silence_ms = silence_ms
        self.on_utterance = on_utterance

        self._model: Optional[WhisperModel] = None
        self._model_lock = threading.Lock()
        self._vad = webrtcvad.Vad(3)  # aggressiveness 0-3, 3 = most aggressive
        self._stream: Optional[sd.InputStream] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._buffer = bytearray()
        self._silence_frames = 0
        self._speaking = False
        self._utterance_start = 0.0

    # ---- model (lazy) ----

    def _get_model(self) -> WhisperModel:
        with self._model_lock:
            if self._model is None:
                logger.info("Loading faster-whisper %s (%s)…", self.model_name, self.compute_type)
                self._model = WhisperModel(
                    self.model_name,
                    compute_type=self.compute_type,
                    device="cpu",
                    cpu_threads=max(1, (os.cpu_count() or 2)),
                )
            return self._model

    def unload_model(self) -> None:
        with self._model_lock:
            self._model = None

    # ---- lifecycle ----

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Murmur AI-listener")
        self._thread.start()
        logger.info("VoiceListener started (16 kHz mono, VAD %d ms silence).", self.silence_ms)

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to close audio stream")
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("VoiceListener stopped.")

    # ---- audio callback ----

    def _callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio stream status: %s", status)
        if not self._running:
            return
        # int16 mono from sounddevice
        pcm = (indata * 32767).astype(np.int16).tobytes()
        self._buffer.extend(pcm)

    # ---- main loop ----

    def _loop(self) -> None:
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME_SAMPLES,
                device=self.device,
                callback=self._callback,
            ) as stream:
                self._stream = stream
                while self._running:
                    self._process_frames()
        except Exception:  # pragma: no cover - hardware dependent
            logger.exception("VoiceListener loop crashed")
            self._running = False

    def _process_frames(self) -> None:
        """Consume complete 30 ms frames from the buffer and run VAD."""
        while len(self._buffer) >= FRAME_SAMPLES * 2:
            frame = bytes(self._buffer[: FRAME_SAMPLES * 2])
            del self._buffer[: FRAME_SAMPLES * 2]
            is_speech = self._vad_is_speech(frame)
            now = self._mono_now()

            if is_speech and not self._speaking:
                # speech start
                self._speaking = True
                self._utterance_start = now
                self._silence_frames = 0
                logger.debug("Speech started")

            if self._speaking:
                if is_speech:
                    self._silence_frames = 0
                else:
                    self._silence_frames += FRAME_MS

                # end of utterance: sustained silence OR max length
                if (
                    self._silence_frames >= self.silence_ms
                    or (now - self._utterance_start) >= MAX_UTTERANCE_S
                ):
                    self._finalize_utterance()

    def _vad_is_speech(self, frame: bytes) -> bool:
        try:
            return self._vad.is_speech(frame, SAMPLE_RATE)
        except Exception:  # pragma: no cover - defensive
            return False

    def _finalize_utterance(self) -> None:
        """Transcribe the captured utterance and hand it off."""
        pcm = bytes(self._buffer[:])  # everything captured so far for this turn
        self._buffer = bytearray()
        self._speaking = False
        self._silence_frames = 0

        if not pcm or len(pcm) < SAMPLE_RATE * 2 * 0.3:  # < 0.3s is noise
            logger.debug("Ignoring sub-threshold utterance")
            return

        text = self._transcribe(pcm)
        if text and self.on_utterance:
            try:
                self.on_utterance(text)
            except Exception:  # pragma: no cover - defensive
                logger.exception("on_utterance callback failed")

    def _transcribe(self, pcm: bytes) -> str:
        model = self._get_model()
        # Convert int16 bytes to float32 numpy for faster-whisper.
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            segments, _info = model.transcribe(
                audio,
                language="en",
                beam_size=1,
                vad_filter=False,  # we already did VAD
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info("Transcribed: %r", text)
            return text
        except Exception:  # pragma: no cover - model dependent
            logger.exception("Transcription failed")
            return ""

    @staticmethod
    def _mono_now() -> float:
        import time

        return time.monotonic()
