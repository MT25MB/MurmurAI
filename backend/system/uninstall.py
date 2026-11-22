"""Uninstall data policy: keep by default, clear only when explicitly chosen.

The choice lives in ``~/.murmur-ai/config.json`` as ``clear_data_on_uninstall``.
Only a fixed allowlist of data files under the app data directory is ever
removed. Downloaded model weights are deliberately left alone: they are large,
re-downloadable, and not personal data.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("murmur_ai.system.uninstall")

DATA_DIR = ".murmur-ai"
CHOICE_KEY = "clear_data_on_uninstall"

CLEAR_FILES = (
    "memories.json",
    "config.json",
    "setup_complete.json",
    "hardware_profile.json",
    "pronunciations.json",
    "mcp_servers.json",
    "local_endpoints.json",
    "tool_recipes.json",
)
CLEAR_DIRS = ("logs",)


def data_root(home: Path | None = None) -> Path:
    return (Path(home) if home else Path.home()) / DATA_DIR


def _within(root: Path, path: Path) -> bool:
    """Reject symlinks and anything resolving outside the app data directory."""
    try:
        return os.path.commonpath(
            [str(root.resolve()), str(path.resolve())]
        ) == str(root.resolve())
    except (ValueError, OSError):  # pragma: no cover - defensive
        return False


def clear_data_requested(root: Path | None = None) -> bool:
    root = root or data_root()
    config = root / "config.json"
    if not config.exists():
        return False
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get(CHOICE_KEY, False)) if isinstance(data, dict) else False


def collect_data_paths(root: Path | None = None) -> list[Path]:
    root = root or data_root()
    candidates: list[Path] = []
    names = list(CLEAR_FILES) + list(root.glob("*.signin.json"))
    for name in names:
        path = root / name if isinstance(name, str) else name
        if path.exists() and _within(root, path):
            candidates.append(path)
    for name in CLEAR_DIRS:
        path = root / name
        if path.is_dir() and _within(root, path):
            candidates.append(path)
    return candidates


def run_cleanup(home: Path | None = None, apply: bool = False) -> dict[str, Any]:
    """Report (and optionally perform) the uninstall data cleanup."""
    root = data_root(home)
    choice = clear_data_requested(root)
    candidates = collect_data_paths(root)
    result: dict[str, Any] = {
        "choice": choice,
        "applied": False,
        "candidates": [str(p) for p in candidates],
        "removed": [],
        "errors": [],
    }
    if not choice or not apply:
        return result

    # config.json is read for the choice, so delete it last.
    ordered = sorted(candidates, key=lambda p: p.name == "config.json")
    for path in ordered:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            result["removed"].append(str(path))
        except OSError as exc:  # pragma: no cover - filesystem dependent
            result["errors"].append(f"{path}: {exc}")
            logger.warning("Could not remove %s during uninstall cleanup: %s", path, exc)
    result["applied"] = True
    return result
