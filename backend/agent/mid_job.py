"""Fast local head for utterances spoken while a long job is running.

Capri runs the job on one thread and classifies mid-job speech on a second,
cheap head: stop ends the job, status/screen questions get a bounded answer, and
only ordinary chat reaches the main brain. Murmur's classifier is deterministic
first with an optional tiny-model fallback, so it works without any extra call.
"""

from __future__ import annotations

import re

from agent.abort import is_abort_phrase

STOP_RE = re.compile(
    r"\b(stop|abort|cancel|halt)\b[^.!?]{0,40}"
    r"\b(automation|task|job|what you'?re doing|vision loop)\b",
    re.IGNORECASE,
)
STATUS_RE = re.compile(
    r"\b(what'?s|what is|how'?s|how is)\b[^.!?]{0,30}\b(going on|happening|status)\b"
    r"|\bstatus\b|\bhow'?s it going\b",
    re.IGNORECASE,
)
SCREEN_RE = re.compile(
    r"\b(what'?s|what is|read|describe|show me|tell me)\b[^.!?]{0,60}"
    r"\b(on (the |my |your )?screen|display|dialog|error|picture)\b",
    re.IGNORECASE,
)

_VALID = {"stop", "status", "screen", "chat"}


def classify(text: str, llm=None) -> str:
    """Return stop | status | screen | chat for an utterance."""
    if is_abort_phrase(text) or STOP_RE.search(text or ""):
        return "stop"
    if STATUS_RE.search(text or ""):
        return "status"
    if SCREEN_RE.search(text or ""):
        return "screen"
    if llm is not None:
        try:
            answer = str(llm(text) or "").strip().lower()
            if answer in _VALID:
                return answer
        except Exception:  # pragma: no cover - a slow head must never break speech
            pass
    return "chat"


def dispatch(
    text: str,
    status_text: str,
    on_stop,
    on_status,
    on_screen,
    llm=None,
) -> bool:
    """Run exactly one fast handler. Returns True if the utterance was handled."""
    intent = classify(text, llm)
    if intent == "stop":
        on_stop()
    elif intent == "status":
        on_status(status_text)
    elif intent == "screen":
        on_screen()
    return intent != "chat"
