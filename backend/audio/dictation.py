"""Voice dictation mode: speech becomes text, never agent commands.

A small state machine owns the last dictated buffer and turns spoken formatting
cues into typed characters. While active, every utterance is handed to
``feed()``; the caller types ``result.text`` into the focused field. Dictation
ends only on an explicit stop phrase or a command trigger, at which point the
remainder is returned as a normal agent command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


START_RE = re.compile(
    r"^\s*(?:start|begin|turn on)\s+(?:dictation|dictating)\s*[.!]?$",
    re.IGNORECASE,
)

STOP_RE = re.compile(
    r"^\s*(?:stop|end|turn off|exit)\s+(?:dictation|dictating)\s*[.!]?$",
    re.IGNORECASE,
)

# A trigger ends dictation and hands the remainder to the normal agent loop.
COMMAND_TRIGGER_RE = re.compile(
    r"^\s*(?:computer|hey murmur|okay murmur)\s*,?\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

SCRATCH_RE = re.compile(
    r"^\s*(?:scratch that|scratch it|erase that|undo that)\b[,\s]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

CUE_SUBSTITUTIONS = (
    (re.compile(r"\bnew paragraph\b|\bparagraph break\b", re.I), "\n\n"),
    (re.compile(r"\bnew line\b|\bnewline\b|\bline break\b", re.I), "\n"),
    (re.compile(r"\bperiod\b|\bfull stop\b", re.I), "."),
    (re.compile(r"\bcomma\b", re.I), ","),
    (re.compile(r"\bquestion mark\b", re.I), "?"),
    (re.compile(r"\bexclamation mark\b|\bexclamation point\b", re.I), "!"),
)


def apply_formatting_cues(text: str) -> str:
    """Turn spoken punctuation into characters, keeping intended newlines."""
    result = text
    for pattern, replacement in CUE_SUBSTITUTIONS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"[ \t]+([.,?!])", r"\1", result)
    result = re.sub(r"([.,?!])[ \t]+", r"\1 ", result)
    return result.strip(" ")


@dataclass
class DictationResult:
    text: str = ""
    backspaces: int = 0
    stopped: bool = False
    command: str = ""
    spoken: str = ""


class DictationSession:
    """In-memory dictation state for one HUD session."""

    def __init__(self) -> None:
        self.active = False
        self._phrases: list[str] = []

    @property
    def buffer(self) -> str:
        """Everything dictated since the session started, for read-back."""
        return "".join(self._phrases)

    def start(self) -> str:
        self.active = True
        self._phrases.clear()
        return "Dictation on. I'll type what you say until you say stop dictating."

    def stop(self) -> str:
        self.active = False
        count = len(self.buffer.split())
        # Keep the buffer so "read back what you just typed" still works.
        return f"Dictation stopped. {count} words typed."

    def feed(self, text: str) -> DictationResult:
        if not self.active or not text.strip():
            return DictationResult()
        value = text.strip()
        if STOP_RE.match(value):
            return DictationResult(stopped=True, spoken=self.stop())
        trigger = COMMAND_TRIGGER_RE.match(value)
        if trigger:
            spoken = self.stop()
            return DictationResult(stopped=True, command=trigger.group(1).strip(), spoken=spoken)

        scratch = SCRATCH_RE.match(value)
        if scratch:
            erased = self._phrases.pop() if self._phrases else ""
            replacement = apply_formatting_cues(scratch.group(1).strip())
            if replacement:
                self._phrases.append(replacement)
            spoken = "Scratch that." if erased else "Nothing to erase."
            return DictationResult(
                text=replacement,
                backspaces=len(erased),
                spoken=spoken,
            )

        value = apply_formatting_cues(value)
        if not value:
            return DictationResult()
        self._phrases.append(value)
        return DictationResult(text=value)
