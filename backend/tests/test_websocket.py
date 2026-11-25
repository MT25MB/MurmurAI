"""WebSocket state broadcasts + HTTP control-plane integration (mocked I/O)."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import main
from agent.state import ServerMessage


@pytest.mark.parametrize(
    "status",
    ["IDLE", "LISTENING", "THINKING", "SPEAKING", "CONFIRMATION_REQUIRED"],
)
def test_state_broadcast_sends_to_all_huds(status):
    """broadcast_to_huds pushes each state to every connected HUD as JSON."""
    sent = []

    class FakeSocket:
        async def send_text(self, payload):
            sent.append(json.loads(payload))

    async def run():
        sock = FakeSocket()
        main.app_state.hud_sockets = {sock}
        main.app_state.send_locks = {id(sock): asyncio.Lock()}
        await main.broadcast_to_huds(ServerMessage(type="state", status=status, uptime_s=1))
        main.app_state.hud_sockets.clear()

    asyncio.run(run())
    assert len(sent) == 1
    assert sent[0]["type"] == "state" and sent[0]["status"] == status


def test_ws_set_muted_toggles_the_runtime_mute_flag():
    """Mute is a real sidecar switch, not just a HUD icon colour."""
    client = TestClient(main.app)
    main.app_state.muted = False
    try:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # greeting
            ws.send_text('{"type":"set_muted","muted":true}')
            muted = ws.receive_json()
            assert muted["type"] == "info"
            assert "muted" in muted["text"].lower()
            assert main.app_state.muted is True
            ws.send_text('{"type":"set_muted","muted":false}')
            assert ws.receive_json()["type"] == "info"
            assert main.app_state.muted is False
    finally:
        main.app_state.muted = False


def test_ws_rejects_cross_origin_browser():
    """A random website must not be able to drive the local agent."""
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(main.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass


def test_ws_allows_tauri_origin():
    client = TestClient(main.app)
    with client.websocket_connect("/ws", headers={"origin": "http://tauri.localhost"}) as ws:
        assert ws.receive_json()["type"] == "state"


def test_server_message_serialization_omits_none():
    msg = ServerMessage(type="progress", text="45%", percent=45)
    assert '"percent":45' in msg.to_json()
    assert "null" not in msg.to_json()
    assert ServerMessage(type="state", status="IDLE").to_json() == '{"type":"state","status":"IDLE"}'


def test_health_and_setup_endpoints():
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    s = client.get("/setup/status")
    assert s.status_code == 200
    assert "models" in s.json() and "ollama" in s.json()


def test_ws_handshake_and_ping():
    """The /ws endpoint accepts, greets with IDLE state, and answers ping."""
    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        greeting = ws.receive_json()
        assert greeting["type"] == "state" and greeting["status"] == "IDLE"
        ws.send_text('{"type":"ping"}')
        pong = ws.receive_json()
        assert pong["type"] == "pong"


def test_ws_abort_broadcasts_automation_stopped():
    from agent.abort import abort_controller

    abort_controller.reset()
    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # greeting
        ws.send_text('{"type":"abort_automation","text":"test"}')
        msg = ws.receive_json()
        assert msg["type"] == "automation_stopped"
        assert "stopped" in msg["text"].lower()
    abort_controller.reset()


def test_brain_abort_phrase_halts_without_model_call(monkeypatch):
    from agent.brain import Brain
    from agent.abort import abort_controller

    abort_controller.reset()
    brain = Brain()
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("model must not be called")

    monkeypatch.setattr(brain, "_chat", boom)
    reply = brain.think_and_act("stop automation")
    assert "stopping" in reply.lower()
    assert abort_controller.is_aborted()
    assert called["n"] == 0
    abort_controller.reset()
