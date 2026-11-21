"""Best-effort background-media ducking while Murmur AI is speaking.

All OS calls are optional and wrapped: if the helper is missing or the user
denies access, speaking simply continues at the current system volume.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from typing import Optional

logger = logging.getLogger("murmur_ai.audio.media_duck")


def _current_volume() -> Optional[int]:
    """Return system output volume as 0..100, or None if unavailable."""
    system = platform.system()
    try:  # pragma: no cover - platform specific
        if system == "Darwin":
            out = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=3, check=False,
            ).stdout.strip()
            return int(out) if out.isdigit() else None
        if system == "Linux":
            out = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True, text=True, timeout=3, check=False,
            ).stdout
            import re

            match = re.search(r"(\d+)%", out)
            return int(match.group(1)) if match else None
        if system == "Windows":
            from pycaw.pycaw import AudioUtilities  # type: ignore

            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                volume = session.SimpleAudioVolume
                if volume is not None:
                    return int(volume.GetMasterVolume() * 100)
    except Exception:
        pass
    return None


def _set_volume(value: int) -> None:
    system = platform.system()
    value = max(0, min(100, int(value)))
    try:  # pragma: no cover - platform specific
        if system == "Darwin":
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {value}"],
                capture_output=True, timeout=3, check=False,
            )
        elif system == "Linux":
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
                capture_output=True, timeout=3, check=False,
            )
        elif system == "Windows":
            from pycaw.pycaw import AudioUtilities  # type: ignore

            for session in AudioUtilities.GetAllSessions():
                volume = session.SimpleAudioVolume
                if volume is not None:
                    volume.SetMasterVolume(value / 100.0, None)
    except Exception:
        logger.debug("Volume change failed", exc_info=True)


class MediaDucker:
    """Lower system media volume while speaking, then restore it."""

    def __init__(self, enabled: bool = False, duck_to: int = 35):
        self.enabled = enabled
        self.duck_to = max(0, min(100, int(duck_to)))
        self._saved: Optional[int] = None

    def duck(self) -> None:
        if not self.enabled or self._saved is not None:
            return
        current = _current_volume()
        if current is None:
            return
        self._saved = current
        if current > self.duck_to:
            _set_volume(self.duck_to)

    def restore(self) -> None:
        if not self.enabled or self._saved is None:
            return
        saved = self._saved
        self._saved = None
        _set_volume(saved)
