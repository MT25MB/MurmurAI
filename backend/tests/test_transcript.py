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


def test_transcript_message_serialization():
    message = ServerMessage(type="transcript", text="Hello.", role="assistant")
    assert '"type":"transcript"' in message.to_json()
    assert '"role":"assistant"' in message.to_json()
    assert ClientMessage.model_fields["type"].annotation is not None
