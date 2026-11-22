"""A fast local head handles stop/status/screen mid-job without a model call."""

from __future__ import annotations

import pytest

from agent.abort import is_abort_phrase
from agent.mid_job import classify, dispatch


def test_classify_stop():
    assert classify("stop automation") == "stop"
    assert classify("cancel the task") == "stop"
    assert classify("halt the job") == "stop"


def test_classify_status():
    assert classify("what's happening") == "status"
    assert classify("how's it going") == "status"
    assert classify("status") == "status"


def test_classify_screen_question():
    assert classify("what's on screen") == "screen"
    assert classify("read the error on the screen") == "screen"
    assert classify("describe my display") == "screen"


def test_classify_ordinary_chat():
    assert classify("hello there") == "chat"
    assert classify("") == "chat"


def test_llm_fallback_used_only_for_uncertain_utterances(monkeypatch):
    from agent import mid_job

    monkeypatch.setattr(mid_job, "is_abort_phrase", is_abort_phrase)
    assert classify("tell me a story", llm=lambda _: "status") == "status"
    assert classify("stop automation", llm=lambda _: "status") == "stop"


def test_invalid_llm_fallback_is_ignored():
    assert classify("tell me a story", llm=lambda _: "do something dangerous") == "chat"


def test_dispatch_runs_exactly_one_handler():
    called: list[str] = []
    handled = dispatch(
        "what's on screen",
        "idle",
        on_stop=lambda: called.append("stop"),
        on_status=lambda value: called.append(f"status:{value}"),
        on_screen=lambda: called.append("screen"),
    )
    assert handled is True
    assert called == ["screen"]


@pytest.mark.asyncio
async def test_mid_job_status_answers_without_brain(monkeypatch):
    import main

    sent: list = []

    async def send(message):
        sent.append(message)

    async def no_speak(session, send_fn, reply):
        sent.append(type("M", (), {"type": "text_output", "text": reply})())

    monkeypatch.setattr(main, "_speak_and_return", no_speak)

    class Session:
        def add_turn(self, *args):
            pass

    handled = await main._try_mid_job_intent(Session(), send, "what's happening")

    assert handled is True
    assert any(getattr(m, "type", "") == "text_output" for m in sent)


@pytest.mark.asyncio
async def test_mid_job_stop_aborts_without_brain(monkeypatch):
    import main
    from agent.abort import abort_controller

    abort_controller.reset()

    async def send(message):
        return None

    class Session:
        def add_turn(self, *args):
            pass

        def uptime(self):
            return 0

    handled = await main._try_mid_job_intent(Session(), send, "stop the job")

    assert handled is True
    assert abort_controller.is_aborted()
    abort_controller.reset()


def test_dispatch_returns_false_for_chat():
    called: list[str] = []
    handled = dispatch(
        "hello",
        "idle",
        on_stop=lambda: called.append("stop"),
        on_status=lambda value: called.append("status"),
        on_screen=lambda: called.append("screen"),
    )
    assert handled is False
    assert called == []
