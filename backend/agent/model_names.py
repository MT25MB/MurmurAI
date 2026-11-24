"""Normalize local model names to the tags published in Ollama's library.

Older releases used the hyphenated spelling (``qwen2.5`` + ``-vl``), which
does not exist in
Ollama and failed every pull with “file does not exist”. Accept the legacy
spelling at the input boundary so existing env vars and saved settings keep
working, but always talk to Ollama with the real tag.
"""

from __future__ import annotations

LEGACY_BASE_NAMES = {
    "qwen2.5" + "-vl": "qwen2.5vl",
}


def normalize_model(name: str) -> str:
    """Return the Ollama library tag for a possibly legacy model name."""
    value = (name or "").strip()
    if not value:
        return ""
    base, separator, tag = value.partition(":")
    base = LEGACY_BASE_NAMES.get(base.lower(), base)
    return f"{base}:{tag}" if separator else base
