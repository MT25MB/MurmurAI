"""Global abort controller for long-running GUI automation.

A single, thread-safe singleton that any component can trigger and any running
vision loop checks. Triggered by:
  - PyAutoGUI failsafe (mouse moved to a screen corner),
  - a spoken stop/abort phrase parsed in main.py,
  - a UI control that sends the abort signal.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable

logger = logging.getLogger("murmur_ai.agent.abort")

# Dedicated phrases that immediately stop any running GUI automation.
ABORT_RE = re.compile(
    r"\b(stop automation|abort automation|stop the automation|abort task|"
    r"stop task|cancel task|stop what you.re doing|stop the vision loop|"
    r"stop the visual agent|halt automation|emergency stop|kill automation)\b",
    re.IGNORECASE,
)


def is_abort_phrase(text: str) -> bool:
    return bool(ABORT_RE.search(text or ""))


class AbortController:
    """Thread-safe abort flag with a reason and optional listener callbacks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str], None]] = []

    # ---- trigger / query ----

    def abort(self, reason: str = "user request") -> None:
        """Signal all running automation to stop. Idempotent."""
        with self._lock:
            if self._event.is_set():
                return
            self._reason = reason
            self._event.set()
            listeners = list(self._listeners)
        logger.warning("Automation abort requested: %s", reason)
        for listener in listeners:
            try:
                listener(reason)
            except Exception:  # pragma: no cover - defensive
                logger.debug("abort listener failed", exc_info=True)

    def is_aborted(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until abort is signalled or timeout expires.

        Returns True if aborted, False on timeout. Workers waiting on a held
        action use this so a global cancel releases them immediately and their
        ``finally`` cleanup always runs.
        """
        return self._event.wait(timeout)

    @property
    def reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        """Clear the abort flag before starting a new automation task."""
        with self._lock:
            self._event.clear()
            self._reason = ""

    # ---- listeners (used to speak/announce the stop) ----

    def add_listener(self, fn: Callable[[str], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn: Callable[[str], None]) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)


# Module-level singleton shared by main.py, brain.py and vision_agent.py.
abort_controller = AbortController()
