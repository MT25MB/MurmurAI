"""Local Text-to-Speech for Murmur AI.

Primary engine: kokoro. Fallbacks: piper-tts, then pyttsx3.
Plays through sounddevice and exposes interrupt() so the AI stops speaking
the moment the user starts talking mid-sentence. Zero cloud dependencies.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np

try:  # pragma: no cover - platform optional
    import sounddevice as sd
except Exception:  # pragma: no cover - optional dep may be installed but unusable (headless/no PortAudio)
    sd = None  # type: ignore

logger = logging.getLogger("murmur_ai.audio.speaker")

SAMPLE_RATE = 22050  # kokoro/piper typical output rate


class LocalSpeaker:
    """Local TTS speaker with barge-in (interrupt) support."""

    def __init__(
        self,
        engine: str = "auto",
        kokoro_voice: str = "af_heart",
        piper_model: Optional[str] = None,
        device: Optional[int] = None,
        earcons: Optional[bool] = None,
    ):
        if sd is None:
            raise RuntimeError(
                "sounddevice is not installed. Run: pip install sounddevice"
            )
        self.engine_pref = engine
        self.kokoro_voice = kokoro_voice
        self.piper_model = piper_model
        self.device = device
        # Non-intrusive state chimes. Opt-in via constructor or
        # MURMUR_AI_EARCONS=1; can be toggled at runtime with set_earcons().
        if earcons is None:
            earcons = os.getenv("MURMUR_AI_EARCONS", "0") == "1"
        self.earcons_enabled = bool(earcons)

        self._engine = None  # resolved engine name
        self._kokoro = None
        self._piper = None
        self._pyttsx3 = None

        self._lock = threading.Lock()
        self._play_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._interrupted = False

    # ---- engine resolution (lazy) ----

    def _resolve_engine(self) -> str:
        if self._engine is not None:
            return self._engine
        pref = (self.engine_pref or "auto").lower()
        if pref == "kokoro" and self._try_kokoro():
            self._engine = "kokoro"
        elif pref == "piper" and self._try_piper():
            self._engine = "piper"
        elif pref == "pyttsx3" and self._try_pyttsx3():
            self._engine = "pyttsx3"
        elif pref == "auto":
            if self._try_kokoro():
                self._engine = "kokoro"
            elif self._try_piper():
                self._engine = "piper"
            elif self._try_pyttsx3():
                self._engine = "pyttsx3"
            else:
                raise RuntimeError(
                    "No local TTS engine available. Install kokoro, piper-tts, or pyttsx3."
                )
        else:
            raise RuntimeError(f"Requested TTS engine '{pref}' is not available.")
        logger.info("TTS engine ready: %s", self._engine)
        return self._engine

    def _try_kokoro(self) -> bool:
        if self._kokoro is not None:
            return True
        try:
            from kokoro import KModel, KPipeline  # type: ignore

            # Kokoro exposes models via pip package + downloaded weights.
            # If weights are missing this raises; fall through gracefully.
            self._kokoro = (KModel, KPipeline)
            return True
        except Exception:  # pragma: no cover - environment dependent
            self._kokoro = None
            return False

    def _try_piper(self) -> bool:
        if self._piper is not None:
            return True
        try:
            from piper_tts import PiperVoice  # type: ignore

            self._piper = PiperVoice
            return True
        except Exception:  # pragma: no cover - environment dependent
            self._piper = None
            return False

    def _try_pyttsx3(self) -> bool:
        if self._pyttsx3 is not None:
            return True
        try:
            import pyttsx3  # type: ignore

            self._pyttsx3 = pyttsx3
            return True
        except Exception:  # pragma: no cover - environment dependent
            self._pyttsx3 = None
            return False

    # ---- earcons (non-intrusive state chimes) ----

    # Each cue is a short list of (frequency_hz, duration_s, gain) notes.
    # Tones are gentle sine waves with a fade envelope to avoid clicks.
    EARCON_NOTES: dict[str, list[tuple[float, float, float]]] = {
        "listening": [(660.0, 0.06, 0.16)],
        "thinking": [(520.0, 0.05, 0.13), (700.0, 0.05, 0.11)],
        "speaking": [(480.0, 0.05, 0.10)],
        "confirmation": [(740.0, 0.07, 0.15), (880.0, 0.09, 0.15)],
        "error": [(300.0, 0.10, 0.16), (220.0, 0.14, 0.16)],
    }

    def set_earcons(self, enabled: bool) -> None:
        """Enable or disable state chimes at runtime."""
        self.earcons_enabled = bool(enabled)
        logger.info("Earcons %s", "enabled" if enabled else "disabled")

    def chime(self, kind: str) -> None:
        """Play a short audio cue for a state transition (non-blocking, multiplicative).

        No-op when earcons are disabled or an unknown cue is requested. Never
        interrupts speech — chimes are short and played at low gain.
        """
        if not self.earcons_enabled or sd is None:
            return
        notes = self.EARCON_NOTES.get(kind)
        if not notes:
            return
        try:

            def render() -> np.ndarray:
                chunks: list[np.ndarray] = []
                for freq, dur, gain in notes:
                    n = int(SAMPLE_RATE * dur)
                    t = np.linspace(0, dur, n, endpoint=False)
                    wave = np.sin(2 * np.pi * freq * t) * gain
                    # Fade in/out (10% each end) to avoid audible clicks.
                    env = np.ones(n)
                    edge = max(1, n // 10)
                    env[:edge] = np.linspace(0, 1, edge)
                    env[-edge:] = np.linspace(1, 0, edge)
                    chunks.append(wave * env)
                    # Tiny silence between notes.
                    chunks.append(np.zeros(int(SAMPLE_RATE * 0.02)))
                audio = np.concatenate(chunks).astype(np.float32)
                return audio

            # Fire-and-forget in a thread so the event loop never blocks.
            threading.Thread(
                target=lambda: self._stream_audio(render(), SAMPLE_RATE),
                daemon=True,
                name="murmur_ai-earcon",
            ).start()
        except Exception:  # pragma: no cover - defensive
            logger.debug("Earcon playback failed", exc_info=True)

    # ---- public API ----

    def speak(self, text: str) -> None:
        """Speak text. Blocks until done or interrupted. Safe to call from any thread."""
        text = (text or "").strip()
        if not text:
            return
        self.interrupt()  # cut anything currently playing
        self._stop.clear()
        self._interrupted = False
        self._play_thread = threading.Thread(
            target=self._run_speak, args=(text,), daemon=True, name="Murmur AI-speaker"
        )
        self._play_thread.start()

    def interrupt(self) -> None:
        """Immediately stop speaking. Idempotent and thread-safe."""
        with self._lock:
            self._stop.set()
            self._interrupted = True
            # sounddevice stop is thread-safe; abort current output.
            if sd is not None:
                try:
                    sd.stop()
                except Exception:  # pragma: no cover - defensive
                    logger.exception("sd.stop failed")

    def is_speaking(self) -> bool:
        with self._lock:
            return self._play_thread is not None and self._play_thread.is_alive()

    # ---- internals ----

    def _run_speak(self, text: str) -> None:
        engine = self._resolve_engine()
        try:
            if engine == "kokoro":
                self._speak_kokoro(text)
            elif engine == "piper":
                self._speak_piper(text)
            else:
                self._speak_pyttsx3(text)
        except Exception:  # pragma: no cover - engine dependent
            logger.exception("TTS playback failed")
        finally:
            with self._lock:
                self._play_thread = None

    def _stream_audio(self, audio: np.ndarray, sample_rate: int) -> None:
        """Play audio via sounddevice, honoring interrupt/stop."""
        if self._interrupted:
            return
        try:
            sd.play(audio, samplerate=sample_rate, device=self.device, blocking=True)
        except sd.PortAudioError:
            pass  # interrupted via sd.stop()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Audio playback error")

    def _speak_kokoro(self, text: str) -> None:
        KModel, KPipeline = self._kokoro  # type: ignore[misc]
        # Kokoro API may vary by version; adapt defensively.
        pipeline = KPipeline(lang_code="a", model=KModel())
        for _, _, audio in pipeline(text, voice=self.kokoro_voice, speed=1.0):
            if self._interrupted:
                break
            audio = np.asarray(audio, dtype=np.float32)
            self._stream_audio(audio, SAMPLE_RATE)

    def _speak_piper(self, text: str) -> None:
        PiperVoice = self._piper  # type: ignore[misc]
        if self.piper_model:
            voice = PiperVoice.load(self.piper_model)
        else:
            voice = PiperVoice.load()  # default bundled voice, if any
        for audio in voice.synthesize(text):
            if self._interrupted:
                break
            audio = np.asarray(audio, dtype=np.float32)
            self._stream_audio(audio, SAMPLE_RATE)

    def _speak_pyttsx3(self, text: str) -> None:
        import pyttsx3  # type: ignore

        engine = pyttsx3.init()
        # pyttsx3 runs its own event loop; drive it until done or interrupted.
        engine.say(text)
        while engine.isBusy() and not self._interrupted:
            engine.iterate()
        if self._interrupted:
            engine.stop()
