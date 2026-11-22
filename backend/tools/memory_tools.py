"""Voice tools for the local memory vault."""

from __future__ import annotations

from typing import Any

from memory import MemoryVault

MEMORY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Remember a non-private fact about the user. Refuses passwords, keys, emails, card numbers and phone numbers.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Fact to remember."}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memories",
            "description": "Speak everything Murmur remembers about the user.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "Forget one remembered fact by id, undoable until the next action.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_forget",
            "description": "Restore the last fact that was forgotten.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


def handle_memory_tool(name: str, arguments: dict[str, Any]) -> str | None:
    """Return a spoken result, or None if this is not a memory tool."""
    if name not in {tool["function"]["name"] for tool in MEMORY_TOOLS}:
        return None
    vault = MemoryVault()
    if name == "remember_fact":
        entry = vault.store(str(arguments.get("text", "")))
        if entry is None:
            return "I can't remember that — it looks like private information."
        return "Remembered."
    if name == "list_memories":
        facts = vault.list()
        if not facts:
            return "I haven't remembered anything yet."
        return "I remember: " + "; ".join(str(f.get("text", "")) for f in facts)
    if name == "forget_memory":
        return "Forgotten." if vault.forget(str(arguments.get("id", ""))) else "I couldn't find that memory."
    if name == "undo_forget":
        return "Restored." if vault.undo() else "There's nothing to undo."
    return None
