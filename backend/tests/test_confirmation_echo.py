"""A spoken approval must come from the user, not from TTS or call echo."""

from __future__ import annotations

import main


def _pending(monkeypatch, resolved):
    from agent.abort import abort_controller

    abort_controller.reset()
    monkeypatch.setattr(main, "_echo_is_active", lambda: True)
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: ["rid"])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: [])
    monkeypatch.setattr(main.tool_bus, "resolve_confirmation",
                        lambda rid, approved: resolved.append((rid, approved)) or True)
    return abort_controller


def test_echo_cannot_spend_a_yes(monkeypatch):
    resolved: list[tuple[str, bool]] = []
    controller = _pending(monkeypatch, resolved)

    assert main._try_verbal_confirmation("yes, confirm") is None
    assert resolved == []
    controller.reset()


def test_echo_cannot_spend_a_no(monkeypatch):
    resolved: list[tuple[str, bool]] = []
    controller = _pending(monkeypatch, resolved)

    assert main._try_verbal_confirmation("no, cancel") is None
    assert resolved == []
    controller.reset()


def test_abort_still_works_during_echo(monkeypatch):
    resolved: list[tuple[str, bool]] = []
    controller = _pending(monkeypatch, resolved)

    main._try_verbal_confirmation("stop automation")
    assert controller.is_aborted()
    controller.reset()


def test_normal_yes_is_accepted_without_echo(monkeypatch):
    resolved: list[tuple[str, bool]] = []
    controller = _pending(monkeypatch, resolved)
    monkeypatch.setattr(main, "_echo_is_active", lambda: False)

    assert main._try_verbal_confirmation("yes, confirm") is True
    assert resolved == [("rid", True)]
    controller.reset()
