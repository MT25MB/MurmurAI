"""Small local journal of reversible file moves for voice undo."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("murmur_ai.tools.undo_journal")

JOURNAL_PATH = Path.home() / ".murmur-ai" / "undo_journal.json"


def _load() -> list[dict[str, Any]]:
    if not JOURNAL_PATH.exists():
        return []
    try:
        data = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(entries: list[dict[str, Any]]) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def record_move(source: str, destination: str) -> None:
    entries = _load()
    entries.append({"kind": "move", "source": str(source), "destination": str(destination)})
    _save(entries[-50:])


def undo_last() -> bool:
    """Reverse the last recorded move if the original is still free."""
    entries = _load()
    if not entries:
        return False
    entry = entries[-1]
    if entry.get("kind") != "move":
        return False
    source = Path(str(entry.get("source", "")))
    destination = Path(str(entry.get("destination", "")))
    if not destination.exists() or source.exists():
        return False
    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))
        entries.pop()
        _save(entries)
        return True
    except OSError:  # pragma: no cover - filesystem dependent
        logger.debug("Could not reverse last move", exc_info=True)
        return False
