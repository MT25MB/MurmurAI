"""LAN isolation, pairing and approval-parity tests for the phone companion.

No browser, microphone, real server socket or Ollama call is used here: the
FastAPI app is exercised with Starlette's in-process test client and all
side-effecting helpers are stubbed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import remote.companion_server as companion
import system.settings_tools as settings_tools
from remote.companion_server import PairingManager, is_lan_address


@pytest.fixture(autouse=True)
def _no_real_runtime(monkeypatch):
    """Never bind a socket or speak during unit tests."""
    monkeypatch.setattr(companion, "_speak", lambda text: None)
    monkeypatch.setattr(companion.runtime, "start", lambda: True)
    monkeypatch.setattr(companion.runtime, "stop", lambda: None)
    monkeypatch.setattr(companion.runtime, "is_running", lambda: True)
    monkeypatch.setattr(settings_tools, "_CACHE", None)
    yield
    from tools.event_bus import tool_bus

    tool_bus.drop_pending("test cleanup")


# ---- subnet isolation ----

@pytest.mark.parametrize("address", [
    "8.8.8.8", "1.1.1.1", "93.184.216.34", "100.64.0.1", "169.254.5.4",
    "2001:4860:4860::8888", "", "not-an-ip", "192.168.1.999",
])
def test_public_and_invalid_addresses_rejected(address):
    assert is_lan_address(address) is False


@pytest.mark.parametrize("address", [
    "10.0.0.5", "10.255.255.254", "172.16.4.9", "172.31.255.1",
    "192.168.1.20", "127.0.0.1", "::1",
])
def test_rfc1918_and_loopback_accepted(address):
    assert is_lan_address(address) is True


def test_http_routes_reject_public_client():
    public = TestClient(companion.app, client=("8.8.8.8", 4444))
    assert public.get("/remote/status").status_code == 403
    assert public.get("/remote/").status_code == 403
    assert public.get("/remote/app.js").status_code == 403


def test_http_routes_serve_lan_client():
    lan = TestClient(companion.app, client=("192.168.1.20", 4444))
    status = lan.get("/remote/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is False  # opt-in, off by default
    index = lan.get("/remote/")
    assert index.status_code == 200
    assert "<main>" in index.text
    assert 'aria-live="polite"' in index.text
    assert lan.get("/remote/app.js").status_code == 200
    assert lan.get("/remote/styles.css").status_code == 200
    assert lan.get("/remote/../../etc/passwd").status_code in (403, 404)


def test_websocket_rejects_public_client(monkeypatch):
    monkeypatch.setattr(companion, "pairing", PairingManager())
    public = TestClient(companion.app, client=("203.0.113.9", 4444))
    with pytest.raises(WebSocketDisconnect) as denied:
        with public.websocket_connect("/remote/ws") as ws:
            ws.receive_json()
    assert denied.value.code == 1008


# ---- PIN authentication ----

def test_pin_exchange_is_single_use_and_peer_bound():
    manager = PairingManager()
    pin = manager.rotate()
    assert len(pin) == 6 and pin.isdigit()

    token = manager.verify(pin, "192.168.1.20")
    assert token
    assert manager.validate_token(token, "192.168.1.20") is True
    # PIN cannot be replayed for a second token.
    assert manager.verify(pin, "192.168.1.20") is None
    # Token is bound to the pairing peer.
    assert manager.validate_token(token, "10.0.0.9") is False
    assert manager.validate_token(token, "192.168.1.20") is True


def test_expired_pin_and_token_fail():
    manager = PairingManager()
    pin = manager.rotate()
    manager._pin_expires = time.monotonic() - 1
    assert manager.verify(pin, "192.168.1.20") is None

    manager.rotate()
    pin = manager.rotate()
    token = manager.verify(pin, "192.168.1.20")
    manager._tokens[token] = ("192.168.1.20", time.monotonic() - 1)
    assert manager.validate_token(token, "192.168.1.20") is False


def test_pin_attempts_rate_limited():
    manager = PairingManager()
    pin = manager.rotate()
    wrong = "000000" if pin != "000000" else "999999"
    for _ in range(companion.MAX_PIN_ATTEMPTS):
        assert manager.verify(wrong, "192.168.1.20") is None
    assert manager.verify(pin, "192.168.1.20") is None
    assert manager._attempts == companion.MAX_PIN_ATTEMPTS


def test_websocket_pairing_and_command_gating(monkeypatch):
    manager = PairingManager()
    pin = manager.rotate()
    monkeypatch.setattr(companion, "pairing", manager)
    lan = TestClient(companion.app, client=("192.168.1.20", 4444))
    with lan.websocket_connect("/remote/ws") as ws:
        assert ws.receive_json()["type"] == "pairing_required"
        ws.send_json({"type": "command", "text": "hello"})
        assert ws.receive_json()["detail"].startswith("Pair first")

        ws.send_json({"type": "pair", "pin": "000000" if pin != "000000" else "999999"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "pair", "pin": pin})
        paired = ws.receive_json()
        assert paired["type"] == "paired" and paired["token"]
        assert manager.validate_token(paired["token"], "192.168.1.20")


# ---- approval parity with the desktop HUD ----

def test_remote_approval_uses_single_use_bound_bus():
    from tools.event_bus import tool_bus

    result: dict[str, bool] = {}

    def ask() -> None:
        result["approved"] = tool_bus.request_confirmation(
            "Install a local package", "winget install example", timeout=3
        )

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    deadline = time.monotonic() + 2
    while not tool_bus.pending_ids() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert tool_bus.pending_ids(), "confirmation was not held"
    request_id = tool_bus.pending_ids()[0]

    details = tool_bus.pending_details()
    assert details[0]["description"] == "Install a local package"
    assert details[0]["command"] == "winget install example"

    assert companion.resolve_remote_approval(request_id, True) is True
    # Replaying the same yes must be refused: one exact request, one decision.
    assert companion.resolve_remote_approval(request_id, True) is False
    worker.join(timeout=3)
    assert result["approved"] is True


def test_remote_approval_cancel_is_a_no():
    from tools.event_bus import tool_bus

    result: dict[str, bool] = {}

    def ask() -> None:
        result["approved"] = tool_bus.request_confirmation("Delete a file", "del x", timeout=3)

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    deadline = time.monotonic() + 2
    while not tool_bus.pending_ids() and time.monotonic() < deadline:
        time.sleep(0.02)
    request_id = tool_bus.pending_ids()[0]
    assert companion.resolve_remote_approval(request_id, False) is True
    worker.join(timeout=3)
    assert result["approved"] is False


def test_approval_from_websocket(monkeypatch):
    from tools.event_bus import tool_bus

    manager = PairingManager()
    pin = manager.rotate()
    monkeypatch.setattr(companion, "pairing", manager)
    lan = TestClient(companion.app, client=("192.168.1.20", 4444))

    done = []
    worker = threading.Thread(
        target=lambda: done.append(
            tool_bus.request_confirmation("Run installer", "winget install x", timeout=3)
        ),
        daemon=True,
    )
    worker.start()
    deadline = time.monotonic() + 2
    while not tool_bus.pending_ids() and time.monotonic() < deadline:
        time.sleep(0.02)
    request_id = tool_bus.pending_ids()[0]

    with lan.websocket_connect("/remote/ws") as ws:
        assert ws.receive_json()["type"] == "pairing_required"
        ws.send_json({"type": "pair", "pin": pin})
        paired = ws.receive_json()
        assert paired["type"] == "paired"
        ws.send_json(
            {"type": "approve", "token": paired["token"],
             "request_id": request_id, "approved": True}
        )
        assert ws.receive_json()["type"] == "status"
    worker.join(timeout=3)
    assert done == [True]


# ---- resource use under repeated commands ----

def test_transcribe_reuses_one_local_model(monkeypatch):
    """Repeated audio turns must not reload weights on every request."""
    import sys
    import types

    constructed = []

    class FakeSegment:
        text = " hello "

    class FakeModel:
        def __init__(self, *_args, **_kwargs):
            constructed.append(self)

        def transcribe(self, *_args, **_kwargs):
            return [FakeSegment()], None

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    pcm = b"\x00\x00" * 100
    companion.transcribe_audio(pcm)
    companion.transcribe_audio(pcm)

    assert len(constructed) == 1


# ---- opt-in voice control ----

def test_companion_disabled_by_default(monkeypatch):
    settings_tools._CACHE = None
    monkeypatch.setattr(settings_tools, "CONFIG_PATH", Path("/nonexistent/config.json"))
    assert settings_tools.load_settings()["remote_companion_enabled"] is False


def test_start_phone_remote_voice_spokes_pin(monkeypatch, tmp_path):
    spoken = []
    monkeypatch.setattr(companion, "_speak", lambda text: spoken.append(text))
    monkeypatch.setattr(settings_tools, "CONFIG_PATH", tmp_path / "config.json")
    settings_tools._CACHE = None
    monkeypatch.setattr(settings_tools, "_voice_reply", lambda text: text)

    reply = settings_tools.handle_voice_command("start phone remote")
    assert reply and "Pairing code" in reply
    pin = companion.pairing._pin
    assert pin and all(digit in "0123456789" for digit in pin)
    assert spoken and pin[0] in spoken[-1]
    assert settings_tools.load_settings()["remote_companion_enabled"] is True

    off = settings_tools.handle_voice_command("stop phone remote")
    assert "off" in off.lower()
    assert settings_tools.load_settings()["remote_companion_enabled"] is False
