"""Persistent checkpoints for multi-step tasks.

Only verified (completed) subgoals are stored, so a resume never repeats work
that already succeeded. Checkpoints are local JSON files under
``~/.murmur-ai/checkpoints``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("murmur_ai.agent.checkpoint")

CHECKPOINT_DIR = Path.home() / ".murmur-ai" / "checkpoints"


@dataclass(frozen=True)
class Checkpoint:
    goal: str
    subgoals: list[str]
    completed: list[str] = field(default_factory=list)
    active_index: int = 0
    updated_at: float = field(default_factory=time.time)


def save(cp: Checkpoint) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKPOINT_DIR / f"checkpoint-{int(cp.updated_at * 1000)}.json"
    path.write_text(
        json.dumps({
            "goal": cp.goal,
            "subgoals": cp.subgoals,
            "completed": cp.completed,
            "active_index": cp.active_index,
            "updated_at": cp.updated_at,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Keep only the most recent few checkpoints.
    files = sorted(CHECKPOINT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for stale in files[:-10]:
        stale.unlink(missing_ok=True)
    return path


def record_progress(
    goal: str,
    subgoals: Iterable[str],
    completed: Iterable[str],
    active_index: int,
) -> Checkpoint:
    cp = Checkpoint(
        goal=goal,
        subgoals=list(subgoals),
        completed=list(completed),
        active_index=active_index,
        updated_at=time.time(),
    )
    save(cp)
    return cp


def load_last() -> Checkpoint | None:
    if not CHECKPOINT_DIR.exists():
        return None
    files = sorted(CHECKPOINT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - corrupt file
        return None
    def _as_int(value: object, default: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return default

    def _as_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return default

    subgoals = data.get("subgoals", [])
    if not isinstance(subgoals, list):
        subgoals = []
    completed = data.get("completed", [])
    if not isinstance(completed, list):
        completed = []
    return Checkpoint(
        goal=str(data.get("goal", "")),
        subgoals=[str(step) for step in subgoals],
        completed=[str(step) for step in completed],
        active_index=_as_int(data.get("active_index")),
        updated_at=_as_float(data.get("updated_at")),
    )


def describe(cp: Checkpoint) -> str:
    """One-breath spoken summary of the paused task."""
    next_step = (
        cp.subgoals[cp.active_index]
        if 0 <= cp.active_index < len(cp.subgoals)
        else (cp.subgoals[-1] if cp.subgoals else "the current step")
    )
    return (
        f"You stopped on step {cp.active_index + 1} of {len(cp.subgoals)}: "
        f"{next_step}. Say resume my last task to continue."
    )


def resume_subgoals(cp: Checkpoint) -> list[str]:
    """Return only the subgoals that have not been verified complete."""
    return [step for index, step in enumerate(cp.subgoals) if index >= cp.active_index]
