"""Declarative app workflow packs (.murmur-skill).

Packs contain hotkeys, UI terminology and prompt context only. They never carry
code, commands, URLs or file paths, so importing one cannot execute anything.
All text is run through the shared prompt-injection filter before it reaches a
model.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("murmur_ai.skills.pack_loader")

BUILTIN_DIR = Path(__file__).resolve().parent / "packs"
USER_PACKS_DIR = Path.home() / ".murmur-ai" / "skills"
FORBIDDEN_KEYS = {
    "script", "command", "exec", "execute", "run", "code", "shell", "bash",
    "url", "http", "path", "file", "env", "token", "key", "secret",
}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


@dataclass(frozen=True)
class SkillPack:
    id: str
    app_name: str
    hotkeys: dict[str, str] = field(default_factory=dict)
    terminology: dict[str, str] = field(default_factory=dict)
    prompt_context: str = ""
    source: str = "builtin"


def sanitize_text(text: str) -> str:
    from agent.prompt_guard import strip_override_lines

    return strip_override_lines(str(text or ""))[:1000]


def validate_pack(raw: Any, source: str = "builtin") -> SkillPack | None:
    if not isinstance(raw, dict):
        return None
    for key in raw:
        if str(key).lower() in FORBIDDEN_KEYS:
            return None
    pack_id = str(raw.get("id", "")).strip()
    if not _ID_RE.match(pack_id):
        return None
    hotkeys = raw.get("hotkeys") or {}
    terminology = raw.get("terminology") or {}
    if not isinstance(hotkeys, dict) or not isinstance(terminology, dict):
        return None
    if len(hotkeys) > 40 or len(terminology) > 40:
        return None
    clean_hotkeys = {
        sanitize_text(k)[:40]: sanitize_text(v)[:60]
        for k, v in hotkeys.items()
        if isinstance(k, str) and isinstance(v, str)
    }
    clean_terms = {
        sanitize_text(k)[:40]: sanitize_text(v)[:120]
        for k, v in terminology.items()
        if isinstance(k, str) and isinstance(v, str)
    }
    return SkillPack(
        id=pack_id,
        app_name=sanitize_text(str(raw.get("app_name", pack_id)))[:60],
        hotkeys=clean_hotkeys,
        terminology=clean_terms,
        prompt_context=sanitize_text(raw.get("prompt_context", ""))[:1000],
        source=source,
    )


def _read_pack(path: Path, source: str) -> SkillPack | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read skill pack %s: %s", path, exc)
        return None
    return validate_pack(raw, source)


def load_packs() -> dict[str, SkillPack]:
    packs: dict[str, SkillPack] = {}
    for path in sorted(BUILTIN_DIR.glob("*.json")):
        pack = _read_pack(path, "builtin")
        if pack:
            packs[pack.id] = pack
    if USER_PACKS_DIR.exists():
        for path in sorted(USER_PACKS_DIR.glob("*.murmur-skill")):
            pack = _read_pack(path, "user")
            if pack:
                packs[pack.id] = pack
    return packs


def app_context(packs: dict[str, SkillPack], window_title: str, limit: int = 600) -> str:
    """Return bounded prompt context for the app named in a window title."""
    title = (window_title or "").lower()
    matched = [pack for pack in packs.values() if pack.app_name.lower() in title]
    if not matched:
        return ""
    pack = matched[0]
    lines = [f"App profile: {pack.app_name}."]
    if pack.prompt_context:
        lines.append(pack.prompt_context)
    if pack.terminology:
        terms = "; ".join(f"{k} = {v}" for k, v in list(pack.terminology.items())[:6])
        lines.append(f"Terminology: {terms}")
    if pack.hotkeys:
        keys = "; ".join(f"{k} = {v}" for k, v in list(pack.hotkeys.items())[:6])
        lines.append(f"Useful shortcuts: {keys}")
    return "\n".join(lines)[:limit]


SKILL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_skill_packs",
            "description": "List available declarative app workflow packs and their shortcuts.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
]


def handle_skill_tool(name: str, arguments: dict) -> str | None:
    if name != "list_skill_packs":
        return None
    packs = load_packs()
    if not packs:
        return "No app skill packs are available."
    return "App packs: " + ", ".join(sorted(packs))
