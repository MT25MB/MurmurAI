"""Offline wake-word detection for Murmur AI.

100% local. No cloud audio ever leaves the machine. Two strategies, in order:
  1. `openwakeword` if installed (tiny local model, best accuracy).
  2. Silero VAD + tiny faster-whisper keyword gate fallback.

The detector exposes:
  - WakeWordDetector.detect(pcm) -> bool  (does this audio contain the wake phrase?)
  - text_is_wake_phrase(text) -> bool     (keyword gate for transcribed text)
  - sleep/wake phrase helpers used by the backend state machine.

Wake phrases: "hey murmur", "wake up murmur", "murmur".
Sleep phrases: "go to sleep", "stop listening", "pause murmur", "go to standby".
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import numpy as np

from audio.echo_guard import ECHO_TAIL_S, echo_is_active

logger = logging.getLogger("murmur_ai.audio.wake_word")

SAMPLE_RATE = 16000

# Normalized wake phrases. "murmur" alone is accepted but guarded against
# false positives by requiring a clearer, near-exact match in text mode.
WAKE_PHRASES = ("hey murmur", "wake up murmur", "wake murmur", "ok murmur", "murmur")

SLEEP_PHRASES = (
    "go to sleep", "stop listening", "pause murmur", "pause listening",
    "go to standby", "sleep mode", "standby mode",
)

# Regexes built once; allow optional punctuation and "hey" variants.
_WAKE_RE = re.compile(
    r"\b(?:hey|hi|ok|okay)?\s*(?:wake up\s+)?murmur\b", re.IGNORECASE
)
_SLEEP_RE = re.compile(
    r"\b(?:go to sleep|stop listening|pause (?:murmur|listening)|go to standby|"
    r"sleep mode|standby mode)\b",
    re.IGNORECASE,
)


def text_is_wake_phrase(text: str) -> bool:
    """True when a transcribed utterance is a wake phrase."""
    if not text or not text.strip():
        return False
    cleaned = text.strip().lower().rstrip(".,!? ")
    return bool(_WAKE_RE.search(cleaned))


def text_is_sleep_phrase(text: str) -> bool:
    """True when a transcribed utterance asks to enter standby."""
    if not text or not text.strip():
        return False
    return bool(_SLEEP_RE.search(text.strip().lower()))


class WakeWordDetector:
    """Local wake-word detector with graceful degradation.

    Try openwakeword first if available. Fall back to a tiny faster-whisper
    keyword gate that transcribes short PCM windows and matches WAKE_PHRASES.
    If no local backend is installed, detection returns False and callers keep
    the microphone in active mode (never a silent failure: a clear log is made).
    """

    def __init__(self, model_name: str = "tiny.en", echo_guard: bool = True,
                 echo_tail_s: float = ECHO_TAIL_S, loopback_guard: bool = True):
        self.model_name = model_name
        self.echo_guard = bool(echo_guard)
        self.echo_tail_s = float(echo_tail_s)
        self.loopback_guard = bool(loopback_guard)
        self.backend: Optional[str] = None
        self._oww_model = None
        self._whisper_model = None
        self._init_backend()

    def _init_backend(self) -> None:
        # 1) openwakeword
        try:  # pragma: no cover - optional dependency
            from openwakeword.model import Model  # type: ignore

            self._oww_model = Model()  # default bundled local models
            self.backend = "openwakeword"
            logger.info("Wake-word backend: openwakeword")
            return
        except Exception:
            self._oww_model = None

        # 2) silero-vad + tiny whisper keyword gate
        try:  # pragma: no cover - optional dependency
            from faster_whisper import WhisperModel  # type: ignore

            self._whisper_model = WhisperModel(
                self.model_name, compute_type="int8", device="cpu"
            )
            self.backend = "whisper-keyword"
            logger.info("Wake-word backend: silero-vad + %s keyword gate", self.model_name)
            return
        except Exception:
            self._whisper_model = None

        self.backend = None
        logger.info("No local wake-word backend installed; standby uses text keyword gate only.")

    def detect(self, pcm: bytes) -> bool:
        """Return True if the PCM window contains the wake phrase.

        Accepts int16 mono bytes at SAMPLE_RATE. Never raises on backend errors.
        """
        if not pcm:
            return False
        if getattr(self, "echo_guard", True) and echo_is_active(
            getattr(self, "echo_tail_s", ECHO_TAIL_S),
            getattr(self, "loopback_guard", True),
        ):
            # Never wake ourselves up with our own TTS or loud media.
            return False

        if self.backend == "openwakeword" and self._oww_model is not None:
            try:  # pragma: no cover - model dependent
                audio = np.frombuffer(pcm, dtype=np.int16)
                prediction = self._oww_model.predict(audio)
                # openwakeword returns {model_name: [score, ...]}
                for scores in prediction.values():
                    if scores and max(scores) >= 0.5:
                        return True
                return False
            except Exception:  # pragma: no cover - defensive
                logger.debug("openwakeword predict failed", exc_info=True)
                return False

        if self.backend == "whisper-keyword" and self._whisper_model is not None:
            try:  # pragma: no cover - model dependent
                audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _ = self._whisper_model.transcribe(
                    audio, language="en", beam_size=1
                )
                text = " ".join(seg.text for seg in segments)
                return text_is_wake_phrase(text)
            except Exception:  # pragma: no cover - defensive
                logger.debug("whisper keyword gate failed", exc_info=True)
                return False

        return False

    @property
    def available(self) -> bool:
        return self.backend is not None
