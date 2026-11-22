"""OS permission diagnostics flow from the shell to /health and speech."""

from __future__ import annotations

import json

import main
from fastapi.testclient import TestClient

from agent.abort import abort_controller


def test_health_includes_permission_report():
    main.app_state.os_permissions = {
        "microphone": "denied",
        "screen": "notNeeded",
        "accessibility": "unknown",
        "recovery": ["Allow microphone access."],
        "summary": "Permissions need attention.",
    }
    try:
        client = TestClient(main.app)
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["os_permissions"]["microphone"] == "denied"
    finally:
        main.app_state.os_permissions = None


def test_permission_status_ws_message_is_stored(monkeypatch):
    from agent.state import ServerMessage

    spoken: list[str] = []
    report = {"recovery": ["Allow screen recording."], "summary": "check"}

    class Speaker:
        def speak_priority(self, text, priority):
            spoken.append(text)

    async def send(message: ServerMessage):
        return None

    class FakeSocket:
        async def send_text(self, payload):
            await send(json.loads(payload))

    main.app_state.speaker = Speaker()  # type: ignore[assignment]
    monkeypatch.setattr(main, "broadcast_to_huds", lambda m: send(m))

    async def run():
        sock = FakeSocket()
        main.app_state.hud_sockets = {sock}
        main.app_state.send_locks = {id(sock): __import__("asyncio").Lock()}
        await main.broadcast_to_huds(ServerMessage(type="state", status="IDLE"))
        # Call the handler directly with the parsed payload.
        await main._handle_permission_status(report, send)

    import asyncio

    asyncio.run(run())
    assert main.app_state.os_permissions == report
    assert any("screen recording" in text for text in spoken)
    main.app_state.os_permissions = None
    main.app_state.speaker = None
    abort_controller.reset()
