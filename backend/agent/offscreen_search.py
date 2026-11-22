"""Bounded directional scroll search for controls not on the current screen.

A target may live below or above the visible list. This module performs at most
a bounded number of scrolls, watching the set of visible element names so it
stops cleanly when the pane stops changing (top/bottom reached).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.abort import abort_controller


@dataclass(frozen=True)
class ScrollResult:
    found: bool
    reason: str  # found | boundary | limit | aborted
    scrolls: int = 0
    seen: tuple[frozenset[str], ...] = field(default_factory=tuple)


class ScrollSearch:
    """Search by scrolling one direction until found or the pane stops changing."""

    def __init__(
        self,
        observe: Callable[[], set[str]],
        scroll: Callable[[str], None],
        speak: Callable[[str], None] | None = None,
        max_scrolls: int = 6,
    ) -> None:
        self._observe = observe
        self._scroll = scroll
        self._speak = speak or (lambda _: None)
        self.max_scrolls = max(1, int(max_scrolls))

    def find(self, target: str, direction: str = "down") -> ScrollResult:
        needle = (target or "").strip().lower()
        seen: list[frozenset[str]] = []
        visible = frozenset(self._observe())
        seen.append(visible)
        if self._matches(visible, needle):
            return ScrollResult(True, "found", 0, tuple(seen))

        self._speak(f"Scrolling {direction} to look for {target}...")
        scrolls = 0
        for _ in range(self.max_scrolls):
            if abort_controller.is_aborted():
                return ScrollResult(False, "aborted", scrolls, tuple(seen))
            self._scroll(direction)
            scrolls += 1
            nxt = frozenset(self._observe())
            seen.append(nxt)
            if self._matches(nxt, needle):
                return ScrollResult(True, "found", scrolls, tuple(seen))
            if nxt == visible:
                self._speak(f"Reached the end while looking for {target}.")
                return ScrollResult(False, "boundary", scrolls, tuple(seen))
            visible = nxt
        self._speak(f"Could not find {target} after {scrolls} scrolls.")
        return ScrollResult(False, "limit", scrolls, tuple(seen))

    @staticmethod
    def _matches(visible: frozenset[str], needle: str) -> bool:
        if not needle:
            return False
        return any(needle in str(item).lower() for item in visible)
