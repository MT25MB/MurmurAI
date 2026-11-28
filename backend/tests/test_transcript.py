"""Clean transcript message emission for screen readers / Braille."""

from __future__ import annotations

import pytest

import main
from agent.state import SessionState, ServerMessage, ClientMessage


@pytest.mark.asyncio
async def test_emit_transcript_sends_clean_plain_text():
    sent = []

    async def send(message):
        sent.append(message)

    await main.emit_transcript(SessionState(), send, "  **Bold**\nline  two.  ", "system")
    assert len(sent) == 1
    assert sent[0].type == "transcript"
    assert sent[0].text == "**Bold** line two."
    assert sent[0].role == "system"


@pytest.mark.asyncio
async def test_emit_transcript_ignores_empty(monkeypatch):
    sent = []

    async def send(message):
        sent.append(message)

    await main.emit_transcript(SessionState(), send, "   ")
    assert sent == []


@pytest.mark.asyncio
async def test_speak_and_return_emits_transcript(monkeypatch):
    monkeypatch.setattr(main, "app_state", type("A", (), {"speaker": None})())
    sent = []

    async def send(message):
        sent.append(message)

    await main._speak_and_return(SessionState(), send, "Opened Blender.")
    transcripts = [m for m in sent if m.type == "transcript"]
    assert len(transcripts) == 1 and transcripts[0].text == "Opened Blender."


@pytest.mark.asyncio
async def test_typed_replies_are_text_only(monkeypatch):
    """Typing mode gets a visible message, not unsolicited TTS."""
    spoken = []
    monkeypatch.setattr(
        main,
        "app_state",
        type("A", (), {"speaker": None, "last_input_mode": "typed", "muted": False})(),
    )

    sent = []

    async def send(message):
        sent.append(message)

    await main._speak_and_return(SessionState(), send, "Which file did you mean?")
    assert any(m.type == "transcript" for m in sent)
    assert not any(m.type == "state" and m.status == "SPEAKING" for m in sent)
    assert spoken == []


@pytest.mark.asyncio
async def test_working_on_it_is_announced(monkeypatch):
    """A slow command is acknowledged immediately, in text and by voice."""
    spoken = []

    class Speaker:
        def speak(self, text):
            spoken.append(text)

    monkeypatch.setattr(
        main,
        "app_state",
        type("A", (), {"speaker": Speaker(), "last_input_mode": "voice"})(),
    )
    sent = []

    async def send(message):
        sent.append(message)

    await main._working_on_it(SessionState(), send)
    assert any(m.type == "transcript" and "Loading" in m.text for m in sent)
    assert spoken == ["Loading, working on it."]


@pytest.mark.asyncio
async def test_working_on_it_stays_silent_for_typed_commands(monkeypatch):
    monkeypatch.setattr(
        main,
        "app_state",
        type("A", (), {"speaker": None, "last_input_mode": "typed"})(),
    )
    sent = []

    async def send(message):
        sent.append(message)

    await main._working_on_it(SessionState(), send)
    assert any(m.type == "transcript" and "Loading" in m.text for m in sent)


def test_transcript_message_serialization():
    message = ServerMessage(type="transcript", text="Hello.", role="assistant")
    assert '"type":"transcript"' in message.to_json()
    assert '"role":"assistant"' in message.to_json()
    assert ClientMessage.model_fields["type"].annotation is not None
