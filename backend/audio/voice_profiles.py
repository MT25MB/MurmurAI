"""Named voice profiles combining rate, voice, chimes and verbosity.

Profiles are applied through the normal settings store so the HUD, voice loop
and TTS engine all see the same values. "clear" is tuned for screen-reader and
Braille users: slower speech, no chimes, detailed descriptions.
"""

from __future__ import annotations

from typing import Any

VOICE_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "speech_rate": 1.0,
        "voice": "af_heart",
        "earcons": True,
        "description_verbosity": "concise",
        "screen_reader_friendly": False,
    },
    "clear": {
        "speech_rate": 0.9,
        "voice": "af_heart",
        "earcons": False,
        "description_verbosity": "detailed",
        "screen_reader_friendly": True,
    },
    "fast": {
        "speech_rate": 1.35,
        "voice": "af_bella",
        "earcons": True,
        "description_verbosity": "concise",
        "screen_reader_friendly": False,
    },
    "quiet": {
        "speech_rate": 1.0,
        "voice": "af_heart",
        "earcons": False,
        "description_verbosity": "concise",
        "screen_reader_friendly": True,
    },
    # Best available fully-local voice: Kokoro's clearest voice, a calm pace,
    # and no chimes layered under clarifying questions.
    "natural": {
        "speech_rate": 0.95,
        "voice": "af_heart",
        "earcons": False,
        "description_verbosity": "detailed",
        "screen_reader_friendly": False,
    },
}


def profile_settings(name: str) -> dict[str, Any] | None:
    key = (name or "").strip().lower()
    for known, values in VOICE_PROFILES.items():
        if key in (known, f"{known} profile", f"my {known} profile"):
            return {**values, "voice_profile": known}
    return None


def list_profiles() -> str:
    return "Voice profiles: " + ", ".join(sorted(VOICE_PROFILES)) + "."


def apply_voice_profile(name: str) -> str:
    from system.settings_tools import update_settings

    values = profile_settings(name)
    if values is None:
        return f"I don't know a voice profile called {name}. {list_profiles()}"
    update_settings(values)
    return f"Voice profile {values['voice_profile']} applied."


VOICE_PROFILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_voice_profile",
            "description": (
                "Switch between named voice profiles (default, clear, fast, "
                "quiet, natural) that set speech rate, voice, chimes and "
                "verbosity. 'natural' uses the clearest fully-local voice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string", "description": "Profile name."}
                },
                "required": ["profile"],
                "additionalProperties": False,
            },
        },
    },
]
