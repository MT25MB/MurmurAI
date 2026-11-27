"""A user's spoken/typed prompt appears in the shared chat transcript."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import main
from agent.state import SessionState


@pytest.mark.asyncio
async def test_handle_text_input_emits_user_prompt_as_transcript(monkeypatch):
    session = SessionState()
    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    monkeypatch.setattr(main, "_working_on_it", AsyncMock())
    monkeypatch.setattr(main, "_set_state", AsyncMock())
    monkeypatch.setattr(main, "_speak_and_return", AsyncMock())
    monkeypatch.setattr(
        main.app_state.brain,
        "think_and_act",
        lambda **_kwargs: "Done.",
    )

    await main.handle_text_input(session, send, "open my notes file")

    user_turns = [
        message
        for message in sent
        if getattr(message, "type", None) == "transcript"
        and getattr(message, "role", None) == "user"
    ]
    assert len(user_turns) == 1
    assert getattr(user_turns[0], "text") == "open my notes file"
