"""Clipboard and active-context tools for hands-free, deictic commands.

Everything is local: pyperclip (or a small native fallback) for the clipboard and
plain filesystem stats for recent files. A tiny per-session context store lets
phrases like "this", "it" and "what's copied" resolve to something concrete.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("murmur_ai.tools.context_tools")

# Module-level fallback when a caller has no SessionState handy.
_GLOBAL_CONTEXT: dict[str, object] = {}

DIRECTORY_PRESETS = {
    "downloads": Path.home() / "Downloads",
    "desktop": Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "pictures": Path.home() / "Pictures",
    "screenshots": Path.home() / "Pictures" / "Screenshots",
}

KNOWN_APPS = (
    "blender", "daVinci resolve", "davinci resolve", "chrome", "firefox",
    "vs code", "notepad", "excel", "word", "photoshop", "figma",
)

FILE_EXT_RE = re.compile(
    r"\b[\w \-]+\.(pdf|png|jpe?g|gif|webp|docx?|xlsx?|pptx?|txt|md|zip|"
    r"mp4|mov|mp3|wav|py|json|csv|blend|svg)\b",
    re.IGNORECASE,
)

REFERENCE_RE = re.compile(
    r"\b(this|it|that|that file|the last file|what'?s copied|what did i just copy|"
    r"my clipboard|the clipboard)\b",
    re.IGNORECASE,
)
CLIPBOARD_RE = re.compile(
    r"\b(clipboard|copied|copy that|what did i just copy|what'?s copied)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def _clipboard_read() -> str:
    try:  # pragma: no cover - environment dependent
        import pyperclip  # type: ignore

        return pyperclip.paste() or ""
    except Exception:
        pass
    system = platform.system()
    try:  # pragma: no cover - platform specific
        if system == "Windows":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True, text=True, timeout=4, check=False,
            )
            return result.stdout.strip()
        if system == "Darwin":
            return subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=4, check=False
            ).stdout
        for tool in ("xclip", "xsel"):
            result = subprocess.run(
                [tool, "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=4, check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception:
        logger.debug("Clipboard read fallback failed", exc_info=True)
    return ""


def _clipboard_write(text: str) -> bool:
    try:  # pragma: no cover - environment dependent
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True
    except Exception:
        pass
    system = platform.system()
    try:  # pragma: no cover - platform specific
        if system == "Windows":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $args[0]", text],
                capture_output=True, timeout=4, check=False,
            )
            return True
        if system == "Darwin":
            subprocess.run(
                ["pbcopy"], input=text, text=True, capture_output=True, timeout=4, check=False
            )
            return True
        for tool, args in (
            ("xclip", ["-selection", "clipboard", "-i"]),
            ("xsel", ["--clipboard", "--input"]),
        ):
            result = subprocess.run(
                [tool, *args], input=text, text=True, capture_output=True, timeout=4, check=False
            )
            if result.returncode == 0:
                return True
    except Exception:
        logger.debug("Clipboard write fallback failed", exc_info=True)
    return False


def read_clipboard() -> str:
    """Return the current clipboard text, or a clear spoken message if empty."""
    text = _clipboard_read().strip()
    if not text:
        return "Your clipboard is empty or unavailable."
    _store("clipboard", text)
    return text


def write_clipboard(text: str) -> str:
    """Copy text to the clipboard and confirm success in plain language."""
    value = str(text or "")
    if not value.strip():
        return "There's nothing to copy."
    if _clipboard_write(value):
        _store("clipboard", value)
        return f"Copied to clipboard. {_summary(value)}"
    return "I couldn't access the clipboard on this machine."


# ---------------------------------------------------------------------------
# Session context
# ---------------------------------------------------------------------------

def _store(key: str, value: object, session: Any | None = None) -> None:
    if session is not None and hasattr(session, "remember"):
        session.remember(key, value)
    _GLOBAL_CONTEXT[key] = value


def _recall(key: str, session: Any | None = None) -> object | None:
    if session is not None and hasattr(session, "recall"):
        value = session.recall(key)
        if value is not None:
            return value
    return _GLOBAL_CONTEXT.get(key)


def record_context(text: str, session: Any | None = None) -> None:
    """Remember filenames/apps mentioned in an utterance for later 'it' refs."""
    value = text or ""
    match = FILE_EXT_RE.search(value)
    if match:
        _store("last_file", match.group(0).strip(), session)
    for app in KNOWN_APPS:
        if re.search(rf"\b{re.escape(app)}\b", value, re.IGNORECASE):
            _store("last_app", app, session)
            break
    if CLIPBOARD_RE.search(value):
        clip = _clipboard_read().strip()
        if clip:
            _store("clipboard", clip, session)


def resolve_reference(text: str, session: Any | None = None) -> Optional[str]:
    """Resolve 'this'/'it'/'what's copied' to concrete context, or None."""
    if not text or not REFERENCE_RE.search(text):
        return None
    if CLIPBOARD_RE.search(text):
        clip = str(_recall("clipboard", session) or _clipboard_read() or "").strip()
        return clip or None
    last_file = _recall("last_file", session)
    if last_file:
        return f"the last file you mentioned: {last_file}"
    clip = str(_recall("clipboard", session) or "").strip()
    return clip or None


# ---------------------------------------------------------------------------
# Recent files
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    path: Path
    name: str
    size_bytes: int
    modified: float

    @property
    def kind(self) -> str:
        suffix = self.path.suffix.lower().lstrip(".")
        return suffix.upper() if suffix else "file"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "size_bytes": self.size_bytes,
            "kind": self.kind,
            "modified": self.modified,
        }


def resolve_directory(directory: str = "downloads") -> Path:
    key = (directory or "downloads").strip().lower()
    if key in DIRECTORY_PRESETS:
        return DIRECTORY_PRESETS[key]
    candidate = Path(os.path.expanduser(directory or ""))
    return candidate if candidate.is_dir() else Path.home()


def list_recent_files(directory: str = "downloads", limit: int = 5) -> list[FileInfo]:
    root = resolve_directory(directory)
    try:
        entries = [p for p in root.iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return []
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for path in entries[: max(0, min(50, int(limit)))]:
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append(FileInfo(path, path.name, stat.st_size, stat.st_mtime))
    return result


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _age(timestamp: float) -> str:
    seconds = max(0, time.time() - timestamp)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


def describe_files(files: list[FileInfo], location: str = "that folder") -> str:
    if not files:
        return f"I didn't find any files in {location}."
    parts = [f"{len(files)} recent file{'s' if len(files) != 1 else ''} in {location}."]
    for item in files:
        parts.append(
            f"{item.name}, {item.kind}, {_human_size(item.size_bytes)}, {_age(item.modified)}."
        )
    return " ".join(parts)


def _speak(text: str) -> None:
    try:  # pragma: no cover - TTS optional
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            speaker.speak(text)
    except Exception:
        logger.debug("Context summary speech failed", exc_info=True)


def inspect_recent_files(directory: str = "downloads", limit: int = 5, speak: bool = True) -> str:
    """List recently modified files with sizes/types and speak a clear summary."""
    files = list_recent_files(directory, limit)
    summary = describe_files(files, directory)
    if files:
        _store("last_file", files[0].name)
        _store("recent_files", [f.to_dict() for f in files])
    if speak:
        _speak(summary)
    return summary


def find_recent_file(query: str, directory: str = "downloads", limit: int = 20) -> Optional[FileInfo]:
    """Find a recent file by extension word ('PDF', 'screenshot') or name."""
    files = list_recent_files(directory, limit)
    if not files:
        return None
    needle = re.sub(r"\b(the|a|my|just|downloaded|latest|recent|file|open|move)\b", "", (query or "").lower())
    needle = re.sub(r"[^a-z0-9.]", "", needle)
    if not needle:
        return files[0]
    for item in files:
        if needle in item.name.lower() or item.kind.lower() == needle:
            return item
    return files[0]


def _summary(text: str, limit: int = 240) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------
# Voice routing helper
# ---------------------------------------------------------------------------

def handle_context_phrase(text: str, session: Any | None = None) -> Optional[str]:
    """Handle clipboard/recent-file questions locally; return None if unmatched."""
    value = (text or "").strip().lower()
    if not value:
        return None

    if re.search(
        r"copy (that result|that answer|that|this|it|the result|the answer) to (my )?clipboard",
        value,
    ):
        if session is not None and hasattr(session, "turns"):
            for turn in reversed(session.turns):
                if turn.get("role") == "assistant":
                    return write_clipboard(turn.get("content", ""))
        return "I don't have a result to copy yet."

    if re.search(
        r"what did i just copy|what'?s (copied|on (my )?clipboard)|read (my )?clipboard",
        value,
    ):
        text_value = read_clipboard()
        reply = f"You copied: {_summary(text_value)}" if not text_value.startswith("Your clipboard") else text_value
        _speak(reply)
        return reply

    if re.search(r"summari[sz]e (my )?clipboard", value):
        clip = read_clipboard()
        if clip.startswith("Your clipboard"):
            _speak(clip)
            return clip
        words = len(clip.split())
        reply = f"Your clipboard has {words} words. It says: {_summary(clip)}"
        _speak(reply)
        return reply

    if re.search(r"recent files|what did i (just )?download|list my downloads|latest screenshot", value):
        return inspect_recent_files("downloads", 5)

    return None


CONTEXT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_clipboard",
            "description": (
                "Read the user's local clipboard text. Use when they ask what "
                "they just copied or to summarize/act on clipboard contents."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_clipboard",
            "description": "Copy a result or text to the local clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to copy."}
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_recent_files",
            "description": (
                "List recently modified files in Downloads/Desktop/Documents or "
                "an explicit local directory, with sizes, types and ages. Use for "
                "'what did I just download' or 'open the PDF I just downloaded'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Preset (downloads/desktop/documents) or a local path.",
                    },
                    "limit": {"type": "integer", "description": "How many files to list."},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]
