"""Procedural spatial audio cues and action sonification.

Zero audio assets: everything is synthesized with numpy and played through
sounddevice. Cues are panned horizontally by screen X and pitched by screen Y,
so blind users can perceive where an action happened without visual clutter.

All playback is best effort: missing PortAudio, disabled cues, or an exception
simply results in silence. Pure math helpers are exposed for tests.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Optional

import numpy as np

try:  # pragma: no cover - platform optional
    import sounddevice as sd
except Exception:  # pragma: no cover - headless CI
    sd = None  # type: ignore

logger = logging.getLogger("murmur_ai.audio.earcons")

SAMPLE_RATE = 22050
PITCH_RANGE_OCTAVES = 0.5  # top = +0.25 octave, bottom = -0.25 octave

# Distinct, short, non-intrusive chimes (frequency tuples, played sequentially).
CHIMES: dict[str, tuple[float, ...]] = {
    "wake_up": (523.25, 659.25, 783.99),
    "sleep": (587.33, 440.0),
    "action_success": (659.25, 987.77),
    "confirmation_needed": (740.0, 880.0, 740.0),
    "error_recovery": (392.0, 523.25, 349.23),
}

_enabled = True


def set_enabled(enabled: bool) -> bool:
    """Global mute switch for spatial cues and action chimes."""
    global _enabled
    _enabled = bool(enabled)
    return _enabled


def is_enabled() -> bool:
    return _enabled


def normalize_coordinate(value: float) -> float:
    """Accept 0..1 or 0..1000 normalized coordinates; clamp to 0..1."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number > 1.0:
        number /= 1000.0
    return max(0.0, min(1.0, number))


def pan_and_pitch(x: float, y: float) -> tuple[float, float, float]:
    """Return (left_gain, right_gain, pitch_multiplier) for a screen point.

    Equal-power panning: x=0 is fully left, x=1 fully right, centre balanced.
    Pitch: y=0 (top of screen) is higher, y=1 (bottom) is lower.
    """
    nx = normalize_coordinate(x)
    ny = normalize_coordinate(y)
    angle = nx * (math.pi / 2.0)
    left = math.cos(angle)
    right = math.sin(angle)
    pitch = 2.0 ** ((0.5 - ny) * PITCH_RANGE_OCTAVES)
    return left, right, pitch


def render_spatial_cue(
    x: float,
    y: float,
    sample_rate: int = SAMPLE_RATE,
    duration: float = 0.11,
    base_freq: float = 880.0,
) -> np.ndarray:
    """Synthesize a short stereo cue shaped by ``pan_and_pitch``."""
    left_gain, right_gain, pitch = pan_and_pitch(x, y)
    count = max(1, int(sample_rate * duration))
    t = np.linspace(0.0, duration, count, endpoint=False)
    wave = np.sin(2.0 * np.pi * base_freq * pitch * t).astype(np.float32)

    # Gentle fade to avoid audible clicks at the edges.
    envelope = np.ones(count, dtype=np.float32)
    edge = max(1, count // 8)
    envelope[:edge] = np.linspace(0.0, 1.0, edge, dtype=np.float32)
    envelope[-edge:] = np.linspace(1.0, 0.0, edge, dtype=np.float32)
    wave *= envelope * 0.12

    stereo = np.zeros((count, 2), dtype=np.float32)
    stereo[:, 0] = wave * left_gain
    stereo[:, 1] = wave * right_gain
    return stereo


def render_chime(kind: str, sample_rate: int = SAMPLE_RATE) -> Optional[np.ndarray]:
    """Synthesize a named mono chime, or None for an unknown cue."""
    notes = CHIMES.get(kind)
    if not notes:
        return None
    chunks = []
    for frequency in notes:
        duration = 0.09
        count = max(1, int(sample_rate * duration))
        t = np.linspace(0.0, duration, count, endpoint=False)
        envelope = np.sin(np.pi * t / duration).astype(np.float32)
        chunks.append(
            (np.sin(2.0 * np.pi * frequency * t) * envelope * 0.11).astype(np.float32)
        )
        chunks.append(np.zeros(int(sample_rate * 0.012), dtype=np.float32))
    return np.concatenate(chunks).astype(np.float32)


def _play(audio: np.ndarray, sample_rate: int) -> None:
    if not _enabled or sd is None:
        return
    try:
        sd.play(audio, samplerate=sample_rate, blocking=False)
    except Exception:  # pragma: no cover - device dependent
        logger.debug("Earcon playback failed", exc_info=True)


def play_spatial_cue(x: float, y: float) -> None:
    """Play a positioned cue asynchronously (safe to call from any thread)."""
    if not _enabled:
        return
    audio = render_spatial_cue(x, y)
    threading.Thread(
        target=_play, args=(audio, SAMPLE_RATE), daemon=True, name="murmur-earcon"
    ).start()


def play_chime(kind: str) -> None:
    """Play a named action chime asynchronously."""
    audio = render_chime(kind)
    if audio is None:
        return
    threading.Thread(
        target=_play, args=(audio, SAMPLE_RATE), daemon=True, name="murmur-chime"
    ).start()
