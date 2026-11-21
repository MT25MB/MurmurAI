"""Update notification, spoken confirmation and offline fallback tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from agent.state import ServerMessage, SessionState


@pytest.fixture(autouse=True)
def _clear_update_state(monkeypatch):
    main.app_state.pending_update = None
    monkeypatch.setattr(main, "_announce", lambda text: None)
    yield
    main.app_state.pending_update = None


@pytest.fixture
def captured_broadcast(monkeypatch):
    messages = []

    async def fake_broadcast(message: ServerMessage) -> None:
        messages.append(message)

    monkeypatch.setattr(main, "broadcast_to_huds", fake_broadcast)
    return messages


@pytest.mark.asyncio
async def test_update_available_broadcasts_prompt(captured_broadcast):
    session = SessionState()

    async def send(message):
        pytest.fail("broadcast is used for HUD updates, not direct send")

    await main.on_update_available(
        session, send, "1.2.3", "## Highlights\n- Faster startup\n- Better screen reader labels"
    )
    assert len(captured_broadcast) == 1
    message = captured_broadcast[0]
    assert message.type == "update_available"
    assert message.version == "1.2.3"
    assert "Faster startup" in message.notes
    assert "#" not in message.notes
    assert "Would you like me to download and restart to install it?" in message.text
    assert main.app_state.pending_update["version"] == "1.2.3"


@pytest.mark.asyncio
async def test_update_prompt_speech_contains_version_summary_and_question(monkeypatch, captured_broadcast):
    spoken = []
    monkeypatch.setattr(main, "_announce", lambda text: spoken.append(text))
    session = SessionState()

    async def send(message):
        pass

    await main.on_update_available(session, send, "2.0.0", "Offline mode improvements.")
    assert spoken
    text = spoken[0].lower()
    assert "version 2.0.0" in text
    assert "offline mode improvements" in text
    assert "download and restart" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,expected_type", [
    ("yes please", "update_install"),
    ("yes, go ahead", "update_install"),
    ("no thanks", "info"),
    ("cancel that", "info"),
])
async def test_verbal_confirmation_resolves_pending_update(
    captured_broadcast, answer, expected_type
):
    session = SessionState()
    main.app_state.pending_update = {"request_id": "u1", "version": "1.2.3", "notes": "x"}
    sent = []

    async def send(message):
        sent.append(message)

    assert await main._try_update_verbal_confirmation(session, send, answer) is True
    assert (captured_broadcast or sent), f"no message for {answer}"
    observed = captured_broadcast[-1].type if captured_broadcast else sent[-1].type
    assert observed == expected_type
    assert main.app_state.pending_update is None


@pytest.mark.asyncio
async def test_yes_without_pending_update_falls_through_to_other_confirmations(captured_broadcast):
    session = SessionState()

    async def send(message):
        pass

    assert await main._try_update_verbal_confirmation(session, send, "yes") is False
    assert captured_broadcast == []


@pytest.mark.asyncio
async def test_update_check_phrase_requests_check(monkeypatch, captured_broadcast):
    spoken = []
    monkeypatch.setattr(main, "_announce", lambda text: spoken.append(text))
    session = SessionState()
    sent = []

    async def send(message):
        sent.append(message)

    assert await main._try_update_check_phrase(session, send, "Check for updates") is True
    assert sent[-1].type == "update_check_request"
    assert spoken and "check for updates" in spoken[0].lower()


@pytest.mark.asyncio
async def test_unrelated_phrase_does_not_trigger_check(captured_broadcast):
    session = SessionState()

    async def send(message):
        pytest.fail("no message expected")

    assert await main._try_update_check_phrase(session, send, "What time is it?") is False


def test_ws_update_available_then_install(monkeypatch):
    monkeypatch.setattr(main, "_announce", lambda text: None)
    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # greeting
        ws.send_text(
            '{"type":"update_available","version":"3.0.0","notes":"Bug fixes"}'
        )
        available = ws.receive_json()
        assert available["type"] == "update_available"
        assert available["version"] == "3.0.0"

        ws.send_text('{"type":"update_confirm","request_id":"u","approved":true}')
        installing = ws.receive_json()
        assert installing["type"] == "update_install"
        assert installing["version"] == "3.0.0"


def test_ws_offline_status_is_graceful(monkeypatch):
    monkeypatch.setattr(main, "_announce", lambda text: None)
    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # greeting
        ws.send_text('{"type":"update_status","detail":"Update check unavailable: offline"}')
        message = ws.receive_json()
        assert message["type"] == "info"
        assert "unavailable" in message["text"]
    assert main.app_state.pending_update is None
