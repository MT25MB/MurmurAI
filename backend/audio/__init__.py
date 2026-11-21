"""Local audio pipeline: microphone capture, VAD, STT, TTS, wake word."""

from .listener import VoiceListener
from .speaker import LocalSpeaker
from .wake_word import WakeWordDetector, text_is_wake_phrase, text_is_sleep_phrase

__all__ = [
    "VoiceListener", "LocalSpeaker", "WakeWordDetector",
    "text_is_wake_phrase", "text_is_sleep_phrase",
]
