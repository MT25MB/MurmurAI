"""Guided, eyes-free practice sandbox for first-time users.

The walkthrough is purely instructional: it never edits files, installs apps,
or calls a model. It only speaks four short, safe practice tasks and advances
when the user says "next" (or presses Enter in the CLI runner).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEMO_STEPS: list[dict[str, str]] = [
    {
        "title": "Ask what is on screen",
        "prompt": (
            "Practice one of four. Say, describe the screen. I will read the "
            "headings, buttons and form fields aloud. This is practice mode: "
            "nothing changes on your computer. Say next when you are ready."
        ),
    },
    {
        "title": "Open a browser tab",
        "prompt": (
            "Practice two of four. In real use, say, open a new browser tab. I use "
            "accessible browser controls, not pixel clicks. Nothing opens in this "
            "practice mode. Say next to continue."
        ),
    },
    {
        "title": "Create a macro",
        "prompt": (
            "Practice three of four. You can say, save those last steps as a macro "
            "called Prep Browser, then run it by name. No macro is saved in practice "
            "mode. Say next to finish."
        ),
    },
    {
        "title": "Test barge-in interruption",
        "prompt": (
            "Practice four of four. I am about to speak a long sentence. Interrupt "
            "me by saying, stop talking, or pressing Q. In practice mode I will just "
            "explain it. Say next to finish the tutorial."
        ),
    },
]


@dataclass
class DemoSession:
    """Tracks position in the four-step walkthrough."""

    index: int = 0
    active: bool = True

    def current(self) -> Optional[dict[str, str]]:
        if not self.active or self.index >= len(DEMO_STEPS):
            return None
        return DEMO_STEPS[self.index]

    def next_step(self) -> str:
        """Advance one step and return the text to speak."""
        if not self.active:
            return "The tutorial is finished. Say, start tutorial, to begin again."
        step = self.current()
        if step is None:
            self.active = False
            return "Tutorial complete. You can now try these commands for real."
        spoken = step["prompt"]
        self.index += 1
        if self.index >= len(DEMO_STEPS):
            self.active = False
        return spoken

    def finish(self) -> str:
        self.active = False
        return "Tutorial stopped. Nothing was changed."


def start_demo() -> str:
    """Begin a fresh walkthrough (used by the voice tool and CLI)."""
    session = DemoSession()
    return session.next_step()


DEMO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_demo",
            "description": (
                "Start a guided, eyes-free practice walkthrough with four safe "
                "tasks. It never modifies files or settings."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]
