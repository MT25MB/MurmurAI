"""Approvals are bound to one exact request, single-use, and dropped on drift.

Modelled on Capri's Security.Gate / Holding / Resume / Drop behaviour: a user's
"yes" can spend exactly one held action, cannot be replayed, and is discarded as
soon as they say anything that is not a yes or no.
"""

from __future__ import annotations

import threading
import time

import main
from tools.event_bus import ToolEventBus


def _start_pending(bus: ToolEventBus, timeout: float = 5.0, **kwargs):
    """Start request_confirmation on a worker thread and return (thread, result)."""
    result: dict[str, bool] = {}

    def worker() -> None:
        result["approved"] = bus.request_confirmation(
            kwargs.pop("description", "Confirm action"),
            kwargs.pop("command", "do thing"),
            timeout=timeout,
            **kwargs,
        )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    for _ in range(200):
        if bus.pending_ids():
            break
        time.sleep(0.01)
    assert bus.pending_ids(), "confirmation never became pending"
    return thread, result


def test_confirmation_is_single_use():
    bus = ToolEventBus()
    thread, result = _start_pending(bus)
    rid = bus.pending_ids()[0]

    assert bus.resolve_confirmation(rid, True) is True
    assert bus.resolve_confirmation(rid, True) is False, "a yes must not be replayable"

    thread.join(timeout=2)
    assert result["approved"] is True


def test_yes_for_one_action_cannot_authorize_another():
    bus = ToolEventBus()
    first_thread, first_result = _start_pending(bus, description="Delete A", command="del A")
    first_id = bus.pending_ids()[0]

    assert bus.resolve_confirmation(first_id, True) is True
    first_thread.join(timeout=2)
    assert first_result["approved"] is True

    second_thread, second_result = _start_pending(bus, description="Delete B", command="del B")
    second_id = bus.pending_ids()[0]
    assert second_id != first_id, "each held action must get a fresh request id"
    assert bus.resolve_confirmation(first_id, True) is False, "an old yes cannot approve B"
    assert bus.has_pending(second_id), "approving A must not resolve B"

    bus.resolve_confirmation(second_id, False)
    second_thread.join(timeout=2)
    assert second_result["approved"] is False


def test_only_one_confirmation_can_be_pending():
    bus = ToolEventBus()
    thread, result = _start_pending(bus, timeout=10)

    second: dict[str, bool] = {}

    def other_worker() -> None:
        second["approved"] = bus.request_confirmation(
            "Another action", "do other thing", timeout=10
        )

    other = threading.Thread(target=other_worker, daemon=True)
    other.start()
    other.join(timeout=1)
    assert "approved" in second, "a second approval must be rejected immediately, not block"
    assert second["approved"] is False
    assert len(bus.pending_ids()) == 1

    bus.resolve_confirmation(bus.pending_ids()[0], True)
    thread.join(timeout=2)
    assert result["approved"] is True


def test_drop_pending_denies_held_action():
    bus = ToolEventBus()
    thread, result = _start_pending(bus)

    bus.drop_pending("unrelated utterance")

    thread.join(timeout=2)
    assert result["approved"] is False
    assert bus.pending_ids() == []


def test_unrelated_speech_drops_pending_approval(monkeypatch):
    from agent.abort import abort_controller

    abort_controller.reset()
    dropped: list[str] = []
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: ["rid"])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: [])
    monkeypatch.setattr(main.tool_bus, "drop_pending", lambda reason: dropped.append(reason))

    assert main._try_verbal_confirmation("what time is it") is None
    assert dropped == ["unrelated utterance"], "stale approval must be dropped"
    abort_controller.reset()


def test_abort_phrase_denies_and_drops_pending(monkeypatch):
    from agent.abort import abort_controller

    abort_controller.reset()
    denied: list[tuple[str, bool]] = []
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: ["rid"])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: [])
    monkeypatch.setattr(main.tool_bus, "resolve_confirmation",
                        lambda rid, approved: denied.append((rid, approved)) or True)

    main._try_verbal_confirmation("stop automation")
    assert denied == [("rid", False)]
    assert abort_controller.is_aborted()
    abort_controller.reset()
