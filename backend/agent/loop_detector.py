"""Stuck / loop detection for the visual agent.

Detects two failure modes across consecutive steps that fail to advance the
current subgoal:
  1. Repeated identical actions (same action type + coordinates/text).
  2. Near-identical screen states (perceptual hash similarity), meaning the
     action had no visible effect.

When a loop is detected the caller triggers a recovery step (alternative UI
path first, then asking the user verbally for guidance).
"""

from __future__ import annotations

import io
import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger("murmur_ai.agent.loop_detector")

DEFAULT_REPEAT_THRESHOLD = 3   # same action N times in a row -> stuck
DEFAULT_SCREEN_THRESHOLD = 4   # average-hash Hamming distance <= N -> "same screen"
HISTORY = 6


@dataclass
class LoopStatus:
    stuck: bool
    kind: str = ""            # "repeat_action" | "static_screen" | ""
    detail: str = ""


def action_fingerprint(
    action: str,
    element_id: Optional[int],
    coordinates: Optional[list[float]],
    text: Optional[str],
) -> str:
    """Coarse fingerprint that groups near-identical actions."""
    if element_id is not None:
        target = f"el{element_id}"
    elif coordinates:
        # Round to 2% grid so tiny coordinate jitter still counts as "same".
        target = f"{round(coordinates[0] / 20)}x{round(coordinates[1] / 20)}"
    elif text:
        target = "t:" + text.strip().lower()[:40]
    else:
        target = "none"
    return f"{action.upper()}|{target}"


def screen_hash(png_bytes: bytes, size: int = 16) -> Optional[int]:
    """Average-hash of a screenshot: an int bitmask robust to minor UI changes."""
    try:
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(png_bytes)).convert("L").resize((size, size))
        arr = np.asarray(img, dtype=np.float32)
        mean = arr.mean()
        bits = (arr > mean).flatten()
        value = 0
        for bit in bits:
            value = (value << 1) | int(bit)
        return value
    except Exception:  # pragma: no cover - defensive
        logger.debug("screen_hash failed", exc_info=True)
        return None


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class LoopDetector:
    def __init__(
        self,
        repeat_threshold: int = DEFAULT_REPEAT_THRESHOLD,
        screen_threshold: int = DEFAULT_SCREEN_THRESHOLD,
    ):
        self.repeat_threshold = repeat_threshold
        self.screen_threshold = screen_threshold
        # One deque keeps action, hash and subgoal aligned. Separate deques let
        # failed hashes silently shift screens onto the wrong subgoal.
        self.steps: deque[tuple[str, Optional[int], int]] = deque(maxlen=HISTORY)
        self.last_progress_subgoal = -1

    def reset(self) -> None:
        self.steps.clear()
        self.last_progress_subgoal = -1

    def mark_progress(self, subgoal_index: int) -> None:
        """Called when a subgoal is completed, breaks any loop streak."""
        self.last_progress_subgoal = subgoal_index
        self.steps.clear()

    def record(
        self,
        fp: str,
        scr_hash: Optional[int],
        subgoal_index: int,
    ) -> None:
        self.steps.append((fp, scr_hash, subgoal_index))

    def assess(self, current_subgoal: int) -> LoopStatus:
        """Decide whether the agent is stuck on the current subgoal."""
        # Only look at steps since the last subgoal progress.
        recent = [step for step in self.steps if step[2] == current_subgoal]
        recent_actions = [action for action, _hash, _subgoal in recent]
        if len(recent_actions) >= self.repeat_threshold:
            tail = recent_actions[-self.repeat_threshold:]
            if len(set(tail)) == 1:
                return LoopStatus(
                    stuck=True,
                    kind="repeat_action",
                    detail=f"Repeated the same action {len(tail)} times: {tail[-1]}",
                )

        # Static screen: last N hashes on this subgoal all near-identical.
        recent_screens = [h for _action, h, _subgoal in recent if h is not None]
        if len(recent_screens) >= self.repeat_threshold:
            tail = recent_screens[-self.repeat_threshold:]
            if all(hamming(tail[0], h) <= self.screen_threshold for h in tail[1:]):
                return LoopStatus(
                    stuck=True,
                    kind="static_screen",
                    detail="The screen has not changed for several steps; the action is not taking effect.",
                )

        return LoopStatus(stuck=False)
