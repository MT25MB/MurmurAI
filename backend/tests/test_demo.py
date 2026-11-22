"""Guided eyes-free practice walkthrough tests."""

from __future__ import annotations

import pytest

import agent.brain as brain
import main
import system.demo as demo
import tools.os_tools as os_tools
from agent.state import SessionState


def test_four_safe_steps():
    assert len(demo.DEMO_STEPS) == 4
    titles = " ".join(step["title"].lower() for step in demo.DEMO_STEPS)
    for word in ("screen", "browser", "macro", "barge-in"):
        assert word in titles
    for step in demo.DEMO_STEPS:
        assert "practice mode" in step["prompt"] or "in real use" in step["prompt"]


def test_session_advances_and_finishes():
    session = demo.DemoSession()
    for expected_index in range(4):
        assert session.active is True
        assert session.current() is demo.DEMO_STEPS[expected_index]
        session.next_step()
    assert session.active is False
    assert "finished" in session.next_step().lower()


def test_finish_stops_immediately():
    session = demo.DemoSession()
    assert "stopped" in session.finish().lower()
    assert session.active is False


def test_start_demo_returns_first_prompt():
    assert "Practice one of four" in demo.start_demo()


def test_demo_tool_registered_and_dispatched():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert "start_demo" in names
    assert "Practice one of four" in os_tools.dispatch_tool("start_demo", {}, None)


@pytest.mark.asyncio
async def test_demo_voice_phrase_starts_walkthrough(monkeypatch):
    spoken = []

    async def fake_speak_and_return(session, send, text):
        spoken.append(text)

    monkeypatch.setattr(main, "_speak_and_return", fake_speak_and_return)
    main.app_state.demo = None
    sent = []

    async def send(message):
        sent.append(message)

    assert await main._try_demo_phrase(SessionState(), send, "Start tutorial") is True
    assert spoken and "Practice one of four" in spoken[0]
    assert main.app_state.demo is not None
    main.app_state.demo = None


@pytest.mark.asyncio
async def test_demo_next_and_exit(monkeypatch):
    spoken = []

    async def fake_speak_and_return(session, send, text):
        spoken.append(text)

    monkeypatch.setattr(main, "_speak_and_return", fake_speak_and_return)

    async def send(message):
        pass

    session = SessionState()
    await main._try_demo_phrase(session, send, "start demo")
    assert await main._try_demo_phrase(session, send, "next") is True
    assert any("Practice two of four" in text for text in spoken)

    assert await main._try_demo_phrase(session, send, "exit tutorial") is True
    assert main.app_state.demo is None
    assert any("stopped" in text.lower() for text in spoken)


@pytest.mark.asyncio
async def test_non_demo_phrase_ignored(monkeypatch):
    main.app_state.demo = None
    spoken = []

    async def fake_speak_and_return(session, send, text):
        spoken.append(text)

    monkeypatch.setattr(main, "_speak_and_return", fake_speak_and_return)

    async def send(message):
        pass

    assert await main._try_demo_phrase(SessionState(), send, "What time is it?") is False
    assert spoken == []
