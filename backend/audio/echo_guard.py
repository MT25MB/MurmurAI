"""Speaker-bleed / echo guard shared by the listener and wake-word detector.

The guard is deliberately simple and local: while the TTS speaker is active,
(and for a short tail afterwards) voice input is ignored so Murmur AI cannot
hear its own voice and start a feedback loop. An optional loopback device can
also be configured for rooms where other media plays through the speakers.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from audio.speaker_provider import get_speaker

ECHO_TAIL_S = 0.25
LOOPBACK_THRESHOLD = 0.02


def speaker_is_active(tail_s: float = ECHO_TAIL_S) -> bool:
    """True while TTS is playing, or within ``tail_s`` of it finishing."""
    speaker = get_speaker()
    if speaker is None:
        return False
    try:
        if speaker.is_speaking():
            return True
    except Exception:
        pass
    last_end = getattr(speaker, "last_speak_end", None)
    if last_end is None:
        return False
    try:
        return (time.monotonic() - float(last_end)) < tail_s
    except (TypeError, ValueError):
        return False


def loopback_is_loud(threshold: Optional[float] = None) -> bool:
    """Optional system-audio check via MURMUR_LOOPBACK_DEVICE (name substring)."""
    device_name = os.getenv("MURMUR_LOOPBACK_DEVICE", "").strip()
    if not device_name:
        return False
    try:  # pragma: no cover - hardware dependent
        import numpy as np
        import sounddevice as sd

        match = next(
            (
                d
                for d in sd.query_devices()
                if device_name.lower() in str(d.get("name", "")).lower()
            ),
            None,
        )
        if match is None:
            return False
        level = float(threshold if threshold is not None else os.getenv(
            "MURMUR_LOOPBACK_THRESHOLD", str(LOOPBACK_THRESHOLD)
        ))
        block = sd.rec(
            int(16000 * 0.1), samplerate=16000, channels=1, dtype="float32",
            device=match["index"],
        )
        sd.wait()
        rms = float(np.sqrt(np.mean(np.asarray(block, dtype=np.float64) ** 2)))
        return rms > level
    except Exception:
        return False


def echo_is_active(tail_s: float = ECHO_TAIL_S, loopback: bool = True) -> bool:
    """Combined guard: our own TTS/bleed or loud system audio."""
    return speaker_is_active(tail_s) or (loopback and loopback_is_loud())
