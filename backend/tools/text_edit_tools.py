"""Local text-entry and editing helpers for voice dictation.

Keyboard simulation uses optional ``pyautogui`` behind a lazy import. Long
passages go through the OS clipboard so CJK text and slow per-key typing are
handled reliably; the user's previous clipboard is always restored. No text or
clipboard content leaves the machine.
"""

from __future__ import annotations

import logging
import platform
import re
from typing import Optional

from tools.context_tools import (
    _clipboard_read as _read_clipboard,
    _clipboard_write as _write_clipboard,
)

logger = logging.getLogger("murmur_ai.tools.text_edit_tools")

# Above this many characters, clipboard paste is faster and handles Unicode.
PASTE_THRESHOLD = 180


def _keyboard():
    """Lazily load pyautogui so the control plane boots without it."""
    try:  # pragma: no cover - optional dependency
        import pyautogui  # type: ignore

        return pyautogui
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Text editing needs pyautogui. Install it with `pip install pyautogui`."
        ) from exc


def _paste_chord() -> tuple[str, ...]:
    return ("command", "v") if platform.system() == "Darwin" else ("ctrl", "v")


def type_text(text: str) -> str:
    """Type into whichever field currently has keyboard focus."""
    value = text or ""
    if not value.strip():
        return "Nothing to type."

    keyboard = _keyboard()
    # pyautogui.write is ASCII-only; paste anything Unicode via the clipboard.
    needs_clipboard = len(value) > PASTE_THRESHOLD or any(ord(char) > 127 for char in value)
    if needs_clipboard:
        saved = _read_clipboard()
        pasted = False
        try:
            pasted = _write_clipboard(value)
            if pasted:
                keyboard.hotkey(*_paste_chord())
        finally:
            if pasted:
                _write_clipboard(saved)
        if pasted:
            return f"Pasted {len(value)} characters."

        logger.warning("Clipboard paste unavailable; typing long text character by character")
    keyboard.write(value, interval=0.01)
    return f"Typed: {value}"


def _modifier() -> str:
    return "command" if platform.system() == "Darwin" else "ctrl"


def _chord(*keys: str) -> None:
    _keyboard().hotkey(*keys)


def select_all() -> str:
    _chord(_modifier(), "a")
    return "Selected everything in the focused field."


def copy_selection() -> str:
    _chord(_modifier(), "c")
    return "Copied the selection."


def paste_here() -> str:
    _chord(*_paste_chord())
    return "Pasted here."


def delete_word() -> str:
    """Delete one word left of the caret. Standard editors can undo with Ctrl+Z."""
    _chord(_modifier(), "backspace")
    return "Deleted the last word."


def erase_last_chars(count: int) -> str:
    """Backspace over characters produced by a 'scratch that' cue."""
    if count <= 0:
        return "Nothing to erase."
    _keyboard().press("backspace", presses=count)
    return f"Erased {count} characters."


def _speak(text: str) -> None:
    try:  # pragma: no cover - TTS may be unavailable in tests
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker and hasattr(speaker, "speak"):
            speaker.speak(text)
    except Exception:  # pragma: no cover - defensive
        logger.debug("Read-back TTS unavailable", exc_info=True)


def read_back_last_dictation(text: str) -> str:
    """Speak the last dictated buffer verbatim for accuracy verification."""
    value = text or ""
    if not value.strip():
        return "Nothing typed yet."
    message = f"You typed: {value}"
    _speak(message)
    return message


def _tool(name: str, description: str, properties: Optional[dict] = None) -> dict:
    properties = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


TEXT_EDIT_TOOLS = [
    _tool(
        "type_text",
        "Type text into the field that currently has keyboard focus. Used for "
        "voice dictation; long passages are pasted from the local clipboard.",
        {"text": {"type": "string", "description": "Exact text to enter."}},
    ),
    _tool("select_all", "Select all text in the focused field."),
    _tool("copy_selection", "Copy the current selection to the local clipboard."),
    _tool("paste_here", "Paste the clipboard at the caret."),
    _tool("delete_word", "Delete the word immediately left of the caret."),
    _tool(
        "read_back_last_dictation",
        "Speak dictated text back verbatim so the user can check accuracy.",
        {"text": {"type": "string", "description": "Buffer to read aloud."}},
    ),
]


def handle_text_edit_tool(name: str, arguments: dict) -> Optional[str]:
    """Dispatch a model tool call; return None when the name is not ours."""
    handlers = {
        "select_all": select_all,
        "copy_selection": copy_selection,
        "paste_here": paste_here,
        "delete_word": delete_word,
    }
    try:
        if name == "type_text":
            return type_text(str(arguments.get("text", "")))
        if name == "read_back_last_dictation":
            return read_back_last_dictation(str(arguments.get("text", "")))
        handler = handlers.get(name)
        return handler() if handler else None
    except RuntimeError as exc:  # missing optional dependency
        return str(exc)


VOICE_ACTIONS = (
    (re.compile(r"^(?:select all|select everything)$", re.I), select_all),
    (
        re.compile(
            r"^(?:copy selection|copy the selection|copy selected text)$", re.I
        ),
        copy_selection,
    ),
    (re.compile(r"^(?:paste here|paste that|paste it here)$", re.I), paste_here),
    (
        re.compile(r"^(?:delete word|erase last word|delete last word)$", re.I),
        delete_word,
    ),
)

READ_BACK_RE = re.compile(
    r"^(?:read back|read that back|read back what you (?:just )?typed)$", re.I
)


def handle_text_edit_phrase(text: str, buffer: str = "") -> Optional[str]:
    """Match a spoken editing command locally, before the model sees it."""
    phrase = (text or "").strip().strip(".!?").strip()
    if not phrase:
        return None

    action: Optional[object] = None
    for pattern, candidate in VOICE_ACTIONS:
        if pattern.match(phrase):
            action = candidate
            break
    if action is None and READ_BACK_RE.match(phrase):
        try:
            return read_back_last_dictation(buffer)
        except RuntimeError as exc:  # missing optional dependency
            return str(exc)
    if action is None:
        return None
    try:
        return action()  # type: ignore[operator]
    except RuntimeError as exc:  # missing optional dependency
        return str(exc)
