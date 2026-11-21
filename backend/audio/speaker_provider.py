"""Shared LocalSpeaker provider.

Avoids circular imports: tools/agent modules import `get_speaker()` from here,
while main.py registers the concrete speaker at startup with `set_speaker()`.
"""

from __future__ import annotations

from typing import Optional

_speaker: Optional[object] = None


def set_speaker(speaker: Optional[object]) -> None:
    """Register the app's shared TTS speaker (called by main.py at startup)."""
    global _speaker
    _speaker = speaker


def get_speaker():
    """Return the shared speaker, or None if TTS is unavailable."""
    return _speaker
