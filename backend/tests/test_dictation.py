"""Dictation-mode behavior: cues, scratch, stop and command handoff."""

from __future__ import annotations

import pytest

import main
import tools.text_edit_tools as tet
from agent.state import SessionState
from audio.dictation import DictationSession


@pytest.fixture
def dictation_env(monkeypatch):
    monkeypatch.setattr(main.app_state, "dictation", DictationSession())
    monkeypatch.setattr(main.app_state, "speaker", None)
    sent: list = []

    async def send(message):
        sent.append(message)

    return sent, send


def test_started_session_feeds_spoken_words_as_text_to_type():
    session = DictationSession()

    session.start()
    result = session.feed("Hello world")

    assert session.active is True
    assert result.text == "Hello world"
    assert result.stopped is False
    assert session.buffer == "Hello world"


def test_spoken_formatting_cues_become_real_characters():
    session = DictationSession()
    session.start()

    assert session.feed("new line").text == "\n"
    assert session.feed("new paragraph").text == "\n\n"
    assert session.feed("hello period how are you comma fine").text == (
        "hello. how are you, fine"
    )
    assert session.buffer == "\n\n\nhello. how are you, fine"


def test_scratch_that_erases_the_last_phrase():
    session = DictationSession()
    session.start()
    session.feed("Hello there")

    result = session.feed("scratch that")

    assert result.backspaces == len("Hello there")
    assert result.text == ""
    assert session.buffer == ""
    assert "scratch" in result.spoken.lower()


def test_scratch_that_can_be_followed_by_a_replacement_phrase():
    session = DictationSession()
    session.start()
    session.feed("wrong text")

    result = session.feed("scratch that, right text")

    assert result.backspaces == len("wrong text")
    assert result.text == "right text"
    assert session.buffer == "right text"


def test_stopped_buffer_stays_available_for_read_back():
    session = DictationSession()
    session.start()
    session.feed("important detail")
    session.stop()

    assert session.buffer == "important detail"


def test_stop_dictating_ends_the_session_and_ignores_later_speech():
    session = DictationSession()
    session.start()
    session.feed("typed words")

    result = session.feed("Stop dictating")

    assert result.stopped is True
    assert session.active is False
    assert "stopped" in result.spoken.lower()
    assert session.feed("should be ignored").text == ""


def test_command_trigger_hands_the_remainder_back_to_the_agent():
    session = DictationSession()
    session.start()

    result = session.feed("Computer, open Blender")

    assert result.stopped is True
    assert result.command == "open Blender"
    assert result.text == ""
    assert session.active is False


@pytest.mark.asyncio
async def test_dictation_routes_speech_to_typing_without_a_model_call(
    dictation_env, monkeypatch
):
    sent, send = dictation_env
    typed: list[str] = []
    monkeypatch.setattr(tet, "type_text", lambda text: typed.append(text) or "ok")
    session = SessionState()

    handled, routed = await main._route_dictation(session, send, "Start dictating")
    assert handled is True and routed == ""
    assert main.app_state.dictation.active is True

    handled, routed = await main._route_dictation(
        session, send, "deploy the app comma then save"
    )
    assert handled is True and typed == ["deploy the app, then save"]
    assert not any(getattr(m, "status", None) == "THINKING" for m in sent)

    handled, routed = await main._route_dictation(session, send, "Stop dictating")
    assert handled is True and main.app_state.dictation.active is False


@pytest.mark.asyncio
async def test_command_trigger_leaves_dictation_and_routes_the_remainder(
    dictation_env,
):
    sent, send = dictation_env
    session = SessionState()
    await main._route_dictation(session, send, "Start dictating")

    handled, routed = await main._route_dictation(session, send, "Computer, open Blender")

    assert handled is False
    assert routed == "open Blender"
    assert main.app_state.dictation.active is False


@pytest.mark.asyncio
async def test_handle_text_input_never_calls_the_brain_while_starting_dictation(
    dictation_env, monkeypatch
):
    sent, send = dictation_env
    session = SessionState()

    def no_brain(**_kwargs):
        raise AssertionError("dictation start must not reach the model")

    monkeypatch.setattr(main.app_state.brain, "think_and_act", no_brain)
    await main.handle_text_input(session, send, "Start dictating")

    assert main.app_state.dictation.active is True
