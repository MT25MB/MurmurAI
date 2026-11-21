"""WebSocket state machine, verbal confirmation, and first-run setup checks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import setup as app_setup
from agent.state import ServerMessage
from tools.event_bus import ToolEventBus


# ---- WebSocket state broadcasts ----

@pytest.mark.parametrize("status", ["IDLE", "LISTENING", "THINKING", "SPEAKING",
                                    "CONFIRMATION_REQUIRED"])
def test_state_broadcast_to_all_huds(status):
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
    assert len(sent) == 1 and sent[0]["status"] == status


def test_ws_greeting_and_ping():
    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        greeting = ws.receive_json()
        assert greeting["type"] == "state" and greeting["status"] == "IDLE"
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json()["type"] == "pong"


def test_health_and_setup_status():
    client = TestClient(main.app)
    assert client.get("/health").json()["status"] == "ok"
    s = client.get("/setup/status").json()
    assert "models" in s and "ollama" in s and "weights" in s
    p = client.get("/setup/permissions").json()
    assert "platform" in p and "items" in p


# ---- verbal confirmation handling ----

def test_verbal_yes_resolves_pending_confirmation(monkeypatch):
    from agent.abort import abort_controller

    abort_controller.reset()
    bus = ToolEventBus()
    resolved = {}
    bus._pending["rid123"] = (__import__("threading").Event(), resolved)
    bus.resolve_confirmation = lambda rid, approved: resolved.__setitem__("ok", approved) or True
    monkeypatch.setattr(main.tool_bus, "resolve_confirmation", bus.resolve_confirmation)
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: ["rid123"])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: [])

    result = main._try_verbal_confirmation("yes, confirm")
    assert result is True and resolved["ok"] is True
    abort_controller.reset()


def test_verbal_no_denies_pending_confirmation(monkeypatch):
    from agent.abort import abort_controller

    abort_controller.reset()
    resolved = {}
    monkeypatch.setattr(main.tool_bus, "resolve_confirmation",
                        lambda rid, approved: resolved.__setitem__("ok", approved) or True)
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: ["rid"])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: [])
    result = main._try_verbal_confirmation("no, cancel")
    assert result is False and resolved["ok"] is False
    abort_controller.reset()


def test_abort_phrase_halts_everything(monkeypatch):
    from agent.abort import abort_controller

    abort_controller.reset()
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: [])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: [])
    main._try_verbal_confirmation("stop automation")
    assert abort_controller.is_aborted()
    abort_controller.reset()


def test_guidance_answer_consumed(monkeypatch):
    from agent.abort import abort_controller

    abort_controller.reset()
    answers = {}
    monkeypatch.setattr(main.tool_bus, "resolve_guidance",
                        lambda rid, text: answers.__setitem__("text", text) or True)
    monkeypatch.setattr(main.tool_bus, "pending_ids", lambda: [])
    monkeypatch.setattr(main.tool_bus, "guidance_ids", lambda: ["g1"])
    result = main._try_verbal_confirmation("try the menu instead")
    assert result is False and answers["text"] == "try the menu instead"
    abort_controller.reset()


# ---- first-run setup checks ----

def test_model_cache_path_is_under_home():
    assert app_setup.MODEL_CACHE_DIR == Path.home() / ".murmur-ai" / "models"
    assert app_setup.COMPLETE_MARKER.parent == Path.home() / ".murmur-ai"


def test_pulled_models_shape(monkeypatch):
    class FakeResp:
        status_code = 200
        def json(self):
            return {"models": [{"name": "qwen2.5:7b"}, {"name": "qwen2.5-vl:7b"}]}
    monkeypatch.setattr(app_setup.httpx, "get", lambda *a, **k: FakeResp())
    result = app_setup.pulled_models()
    assert result == {"qwen2.5:7b": True, "qwen2.5-vl:7b": True}


def test_pulled_models_partial(monkeypatch):
    class FakeResp:
        status_code = 200
        def json(self):
            return {"models": [{"name": "qwen2.5:7b"}]}
    monkeypatch.setattr(app_setup.httpx, "get", lambda *a, **k: FakeResp())
    result = app_setup.pulled_models()
    assert result["qwen2.5:7b"] is True and result["qwen2.5-vl:7b"] is False


def test_ollama_status_offline(monkeypatch):
    monkeypatch.setattr(app_setup, "_ollama_binary_path", lambda: None)
    monkeypatch.setattr(app_setup.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(Exception("offline")))
    result = app_setup.ollama_status()
    assert result["installed"] is False and result["running"] is False
    assert "error" in result


def test_required_models_and_labels():
    assert app_setup.REQUIRED_MODELS == ["qwen2.5:7b", "qwen2.5-vl:7b"]
    assert all(m in app_setup.MODEL_LABELS for m in app_setup.REQUIRED_MODELS)


def test_permission_status_platform_shape(monkeypatch):
    monkeypatch.setattr(app_setup.platform, "system", lambda: "Windows")
    result = app_setup.permission_status()
    assert result["platform"] == "Windows" and result["items"]
    assert all({"key", "label", "granted", "hint"} <= item.keys() for item in result["items"])
