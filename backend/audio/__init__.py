"""Local audio pipeline: microphone capture, VAD, STT, TTS, wake word."""

from .listener import VoiceListener
from .speaker import LocalSpeaker
from .wake_word import WakeWordDetector, text_is_wake_phrase, text_is_sleep_phrase
from .pronunciation import (
    add_pronunciation,
    load_dictionary as load_pronunciations,
    normalize as normalize_pronunciation,
    reset_pronunciations,
)
from .voice_profiles import VOICE_PROFILES, apply_voice_profile, list_profiles
from . import earcons

__all__ = [
    "VoiceListener", "LocalSpeaker", "WakeWordDetector",
    "text_is_wake_phrase", "text_is_sleep_phrase",
    "add_pronunciation", "load_pronunciations", "normalize_pronunciation",
    "reset_pronunciations",
    "VOICE_PROFILES", "apply_voice_profile", "list_profiles", "earcons",
]
