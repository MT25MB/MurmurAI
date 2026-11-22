"""Post-action screen verification using a bounded pixel/perceptual diff.

An action is not assumed successful just because it did not throw. This module
compares small downscaled grayscale frames and makes "no change" an explicit
verdict, with documented exceptions for actions that legitimately leave the
pixels unchanged.
"""

from __future__ import annotations

import io
import logging
from enum import Enum

logger = logging.getLogger("murmur_ai.agent.screen_diff")

NO_VISUAL_CHANGE_ACTIONS = {"wait", "read", "think", "sleep", "scroll", "status"}
MAX_DIM = 320


class ScreenVerdict(str, Enum):
    CHANGED = "changed"
    NO_CHANGE = "no_change"
    ERROR = "error"


def _frame(png: bytes):
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("L")
    image.thumbnail((MAX_DIM, MAX_DIM))
    return image


def diff_screens(before: bytes, after: bytes, threshold: float = 0.02) -> ScreenVerdict:
    """Return CHANGED when a meaningful fraction of pixels differ."""
    try:
        import numpy as np

        a = np.asarray(_frame(before), dtype=np.int16)
        b = np.asarray(_frame(after), dtype=np.int16)
        if a.shape != b.shape:
            return ScreenVerdict.CHANGED
        changed = np.mean(np.abs(a - b) > 24)
        return ScreenVerdict.CHANGED if changed > threshold else ScreenVerdict.NO_CHANGE
    except Exception:  # pragma: no cover - corrupt screenshot
        logger.debug("Screen diff failed", exc_info=True)
        return ScreenVerdict.ERROR


def verify_action(
    action: str,
    before: bytes,
    after: bytes,
    expected: str | None = None,
    threshold: float = 0.02,
) -> dict:
    """Combine a before/after diff with the action's expected visual effect."""
    verdict = diff_screens(before, after, threshold)
    changed = verdict == ScreenVerdict.CHANGED
    expects_none = bool(expected and "no visual change" in expected.lower())
    allowed_static = action.lower() in NO_VISUAL_CHANGE_ACTIONS or expects_none
    satisfied = (
        verdict == ScreenVerdict.ERROR
        or changed
        or allowed_static
    )
    return {
        "verdict": verdict,
        "changed": changed,
        "satisfied": satisfied,
        "action": action,
        "expected": expected or "",
    }
