"""Dynamic vocabulary hints for local ASR.

Active window titles, loaded app-skill terminology, custom pronunciations and
macro names are folded into a short prompt/hotword hint so faster-whisper
recognises domain words correctly. All input is local and bounded.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("murmur_ai.audio.hotwords")

MAX_CHARS = 240


def _active_window_title() -> str:
    try:
        from tools.window_tools import list_windows

        focused = next((w for w in list_windows() if getattr(w, "focused", False)), None)
        return str(getattr(focused, "title", "") or "") if focused else ""
    except Exception:  # pragma: no cover - platform dependent
        return ""


def _skill_keywords() -> list[str]:
    try:
        from skills.pack_loader import app_context, load_packs

        title = _active_window_title()
        packs = load_packs()
        context = app_context(packs, title, limit=200)
        words = []
        for line in context.splitlines():
            if ":" in line:
                words.extend(part.strip() for part in line.split(":", 1)[1].split(";"))
        return [w for w in words if w][:20]
    except Exception:  # pragma: no cover - optional packs
        return []


def _custom_names() -> list[str]:
    names: list[str] = []
    try:
        from audio.pronunciation import load_dictionary

        names.extend(str(k) for k in load_dictionary().keys())
    except Exception:  # pragma: no cover - optional dictionary
        pass
    try:
        from tools.macro_tools import macro_names

        names.extend(macro_names())
    except Exception:  # pragma: no cover - no macro module yet
        pass
    return names[:20]


def build_hint() -> str:
    """Return a compact hint string suitable for initial_prompt/hotwords."""
    parts: list[str] = []
    title = _active_window_title().strip()
    if title:
        parts.append(title[:80])
    parts.extend(_skill_keywords())
    parts.extend(_custom_names())
    seen: set[str] = set()
    unique = []
    for part in parts:
        key = part.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(part.strip())
    return ", ".join(unique)[:MAX_CHARS]
