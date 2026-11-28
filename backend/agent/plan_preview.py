"""Spoken plan preview (dry run) parsing and formatting.

Pure helpers shared by the brain, the vision agent and main.py. A preview is a
read-only proposal: it holds the planned steps, the tools and files involved,
and the exact decision phrases that may later approve, adjust or discard it.
Nothing here performs an action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


PREVIEW_RE = re.compile(
    r"^\s*(?:preview|show me (?:the )?plan|what would you do)\b.*?\b(?:to|for)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
APPROVE_RE = re.compile(
    r"^\s*(?:go ahead|go for it|let'?s do it|do that|do it|"
    r"yes(?:[, ]+confirm|[, ]+please|[, ]+(?:i'?m |i am )?ready)?|"
    r"yeah|yep|yup|ok|okay|sure|"
    r"confirm(?: the plan)?|execute (?:the )?plan|proceed|approved?)\s*[.!]?$",
    re.IGNORECASE,
)
SKIP_RE = re.compile(
    r"^\s*skip\s+(?:steps?\s+)?"
    r"(?P<numbers>(?:\d+|[A-Za-z]+)(?:[\s,]+(?:\d+|[A-Za-z]+))*)\s*[.!]?$",
    re.IGNORECASE,
)
CANCEL_RE = re.compile(
    r"^\s*(?:cancel|never ?mind|discard(?: the plan)?|no[, ]+cancel|no thanks)\s*[.!]?$",
    re.IGNORECASE,
)
FILE_RE = re.compile(r"(?<![\w])([\w./\\-]+\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,5})\b")

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8,
}

GUI_KEYWORDS = (
    "blender", "davinci", "resolve", "photoshop", "figma", "notepad",
    "vs code", "chrome", "firefox", "desktop", "screen", "window", "click",
)

MULTI_STEP_RE = re.compile(r"\b(and|then|after that|finally)\b|;", re.IGNORECASE)


@dataclass
class Decision:
    kind: str  # preview | approve | skip | cancel | none
    goal: str = ""
    numbers: list[int] = field(default_factory=list)


@dataclass
class PlanPreview:
    goal: str
    steps: list[str]
    tools: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    engine: str = "brain"  # brain | vision
    tool_calls: list[dict] = field(default_factory=list)
    plan: object | None = None  # approved vision TaskPlan is reused on execution
    skipped: set[int] = field(default_factory=set)

    def active_steps(self) -> list[str]:
        return [step for i, step in enumerate(self.steps, start=1) if i not in self.skipped]

    def skip(self, numbers: list[int]) -> str:
        for number in numbers:
            if 1 <= number <= len(self.steps):
                self.skipped.add(number)
        names = ", ".join(str(n) for n in numbers)
        return f"Skipping step {names}. {self.spoken()}"

    def spoken(self) -> str:
        parts = [f"Preview: {len(self.steps)} steps."]
        for index, step in enumerate(self.steps, start=1):
            marker = " (skipped)" if index in self.skipped else ""
            parts.append(f"Step {index}, {step}{marker}.")
        if self.tools:
            parts.append("Tools: " + ", ".join(self.tools[:6]) + ".")
        if self.files:
            parts.append("Files: " + ", ".join(self.files[:6]) + ".")
        parts.append("Say yes or go ahead to run it, skip step two to adjust, or cancel to discard.")
        return " ".join(parts)


def classify(text: str) -> Decision:
    """Recognize a preview request or one of its single-use decisions."""
    value = (text or "").strip()
    if not value:
        return Decision("none")
    if APPROVE_RE.match(value):
        return Decision("approve")
    if CANCEL_RE.match(value):
        return Decision("cancel")
    skip = SKIP_RE.match(value)
    if skip:
        numbers: list[int] = []
        for token in re.findall(r"\d+|[A-Za-z]+", skip.group("numbers").lower()):
            numbers.append(int(token) if token.isdigit() else WORD_NUMBERS.get(token, 0))
        return Decision("skip", numbers=[n for n in numbers if n > 0])
    preview = PREVIEW_RE.match(value)
    if preview:
        return Decision("preview", goal=preview.group(1).strip(" ,."))
    return Decision("none")


def extract_files(text: object) -> list[str]:
    """Return unique file-like tokens (paths included) in encounter order."""
    if isinstance(text, str):
        pieces = [text]
    else:
        pieces = [str(item) for item in (text or [])]
    found: list[str] = []
    for piece in pieces:
        for match in FILE_RE.findall(piece):
            name = match.replace("\\", "/").rsplit("/", 1)[-1]
            if name not in found:
                found.append(name)
    return found


def should_auto_preview(goal: str, settings: dict) -> bool:
    """Auto-preview multi-step or file tasks only when the user opted in."""
    if not settings.get("preview_plans"):
        return False
    return bool(MULTI_STEP_RE.search(goal or "") or extract_files(goal))


def pick_engine(goal: str) -> str:
    lowered = (goal or "").lower()
    return "vision" if any(keyword in lowered for keyword in GUI_KEYWORDS) else "brain"
