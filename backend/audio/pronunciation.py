"""User-editable pronunciation dictionary for spoken output.

Murmur's replies are normalized before they reach Kokoro/piper so acronyms and
developer/accessibility terms sound natural. The user can add or override any
entry at ~/.murmur-ai/pronunciations.json, or by voice at runtime.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("murmur_ai.audio.pronunciation")

PRONUNCIATIONS_PATH = Path.home() / ".murmur-ai" / "pronunciations.json"

DEFAULT_PRONUNCIATIONS: dict[str, str] = {
    # General/software
    "GUI": "gooey",
    "CLI": "C-L-I",
    "API": "A-P-I",
    "URL": "U-R-L",
    "HTTP": "H-T-T-P",
    "HTTPS": "H-T-T-P-S",
    "JSON": "J-S-O-N",
    "YAML": "Y-A-M-L",
    "SQL": "S-Q-L",
    "CSV": "C-S-V",
    "PDF": "P-D-F",
    "FAQ": "F-A-Q",
    "CPU": "C-P-U",
    "GPU": "G-P-U",
    "RAM": "RAM",
    "VRAM": "V-ram",
    "SSD": "S-S-D",
    "USB": "U-S-B",
    "OS": "O-S",
    "ID": "I-D",
    "OK": "okay",
    "Ctrl": "Control",
    "Alt": "Alt",
    "Esc": "Escape",
    "sudo": "soo-doo",
    "bpy": "B-P-Y",
    "venv": "V-env",
    "git": "git",
    "npm": "N-P-M",
    "npx": "N-P-X",
    "PyInstaller": "Py-installer",
    # Accessibility
    "NVDA": "N-V-D-A",
    "JAWS": "J-A-W-S",
    "OCR": "O-C-R",
    "TTS": "T-T-S",
    "STT": "S-T-T",
    "ARIA": "A-R-I-A",
    "WAI": "W-A-I",
    "WCAG": "W-C-A-G",
    "VAD": "V-A-D",
    "A11Y": "accessibility",
    # AI/dev
    "LLM": "L-L-M",
    "VLM": "V-L-M",
    "MCP": "M-C-P",
    "RAG": "R-A-G",
    "IDE": "I-D-E",
    "CI": "C-I",
    "CD": "C-D",
    "SDK": "S-D-K",
    "Ollama": "Ollama",
    "Kokoro": "Kokoro",
    "Whisper": "Whisper",
}

_CACHE: Optional[dict[str, str]] = None


def load_dictionary() -> dict[str, str]:
    """Return defaults overlaid with the user's dictionary."""
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    user: dict[str, str] = {}
    try:
        if PRONUNCIATIONS_PATH.exists():
            data = json.loads(PRONUNCIATIONS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                user = {str(k): str(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read pronunciation dictionary", exc_info=True)
    merged = dict(DEFAULT_PRONUNCIATIONS)
    merged.update(user)
    _CACHE = merged
    return dict(merged)


def save_dictionary(dictionary: dict[str, str]) -> dict[str, str]:
    global _CACHE
    clean = {str(k): str(v) for k, v in (dictionary or {}).items()}
    try:
        PRONUNCIATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PRONUNCIATIONS_PATH.write_text(
            json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        logger.debug("Could not save pronunciation dictionary", exc_info=True)
    _CACHE = clean
    return dict(clean)


def add_pronunciation(word: str, spoken_as: str) -> str:
    """Persist a word/pronunciation pair and return a spoken confirmation."""
    term = (word or "").strip()
    spoken = (spoken_as or "").strip()
    if not term or not spoken:
        return "I need both a word and how you want it pronounced."
    dictionary = load_dictionary()
    # Preserve the canonical default casing when overriding a known term.
    canonical = next((k for k in dictionary if k.lower() == term.lower()), term)
    dictionary[canonical] = spoken
    save_dictionary(dictionary)
    return f"Pronouncing {canonical} as {spoken}."


def reset_pronunciations() -> dict[str, str]:
    return save_dictionary(dict(DEFAULT_PRONUNCIATIONS))


def normalize(text: str, dictionary: Optional[dict[str, str]] = None) -> str:
    """Replace known terms with their spoken forms, case-insensitively."""
    value = text or ""
    if not value:
        return value
    dictionary = dictionary if dictionary is not None else load_dictionary()
    if not dictionary:
        return value
    # Longest first so overlapping terms (HTTP vs HTTPS) resolve correctly.
    for term in sorted(dictionary, key=len, reverse=True):
        spoken = dictionary[term]
        if not term:
            continue
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        value = re.sub(pattern, spoken, value, flags=re.IGNORECASE)
    return value


PRONUNCIATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_pronunciation",
            "description": (
                "Teach Murmur how to pronounce a word or acronym. Use when the "
                "user says 'pronounce NVDA as N-V-D-A'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {"type": "string", "description": "Word or acronym to teach."},
                    "spoken_as": {"type": "string", "description": "How it should sound."},
                },
                "required": ["word", "spoken_as"],
                "additionalProperties": False,
            },
        },
    },
]
