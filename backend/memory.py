"""Small local memory vault with a private-data filter and undo.

Capri shows everything she remembers and lets users edit, forget or undo it.
Murmur keeps the same control locally: secrets are never persisted, and every
forget can be undone until the next action.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("murmur_ai.memory")

DEFAULT_PATH = Path.home() / ".murmur-ai" / "memories.json"

PRIVATE_RE = re.compile(
    r"\b(passwords?|passcodes?|pin\s*(?:code|number)?|credit card|card number|"
    r"bank account|sort code|routing number|social security|api[ _-]?key|"
    r"secret|token|bearer|log ?in details)\b"
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"
    r"|\b\+?\d[\d\s-]{7,}\d\b"
    r"|\b(?:my|their|his|her)\s+(?:home|street|email|e-mail|phone|mobile)\s+"
    r"(?:address|number)\b",
    re.IGNORECASE,
)


class MemoryVault:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self._facts: list[dict[str, Any]] = []
        self._last_forgotten: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            facts = data.get("facts", []) if isinstance(data, dict) else []
            self._facts = [f for f in facts if isinstance(f, dict)] if isinstance(facts, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read memory vault %s: %s", self.path, exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"facts": self._facts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(self) -> list[dict[str, Any]]:
        return list(self._facts)

    def store(self, text: str) -> dict[str, Any] | None:
        """Remember a fact, or refuse it if it contains private data."""
        if PRIVATE_RE.search(text or ""):
            logger.info("Refused to remember a fact containing private data")
            return None
        entry = {"id": uuid.uuid4().hex, "text": str(text)}
        self._facts.append(entry)
        self._save()
        return entry

    def forget(self, entry_id: str) -> bool:
        for index, entry in enumerate(self._facts):
            if entry.get("id") == entry_id:
                self._last_forgotten = self._facts.pop(index)
                self._save()
                return True
        return False

    def undo(self) -> bool:
        if self._last_forgotten is None:
            return False
        self._facts.append(self._last_forgotten)
        self._last_forgotten = None
        self._save()
        return True

    def clear(self) -> int:
        count = len(self._facts)
        self._facts = []
        self._save()
        return count
