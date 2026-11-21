"""Local audio pipeline: microphone capture, VAD, STT, and TTS.

Everything runs on-device. No cloud speech services.
"""

from .listener import VoiceListener
from .speaker import LocalSpeaker

__all__ = ["VoiceListener", "LocalSpeaker"]
