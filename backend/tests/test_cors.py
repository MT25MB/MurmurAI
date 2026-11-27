"""Local Tauri webview can reach the FastAPI control plane."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_tauri_origin_is_allowed():
    client = TestClient(main.app)
    response = client.get("/health", headers={"Origin": "tauri://localhost"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_windows_tauri_origin_is_allowed():
    client = TestClient(main.app)
    response = client.get("/setup/status", headers={"Origin": "http://tauri.localhost"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_preflight_for_settings_post():
    client = TestClient(main.app)
    response = client.options(
        "/settings",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_unrelated_origin_is_not_allowed():
    client = TestClient(main.app)
    response = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_arbitrary_localhost_origin_cannot_mutate_state():
    """A page on any localhost port must not reach state-changing endpoints."""
    client = TestClient(main.app)
    response = client.post(
        "/settings/reset", headers={"Origin": "http://localhost:9999"}
    )
    assert response.status_code == 403


def test_ws_origin_check_rejects_unlisted_localhost_port():
    class FakeWS:
        headers = {"origin": "http://127.0.0.1:31337"}

    assert main._ws_origin_allowed(FakeWS()) is False  # type: ignore[arg-type]


def test_ws_origin_check_accepts_shell_and_native_clients():
    class Shell:
        headers = {"origin": "http://tauri.localhost"}

    class Native:
        headers = {}

    assert main._ws_origin_allowed(Shell()) is True  # type: ignore[arg-type]
    assert main._ws_origin_allowed(Native()) is True  # type: ignore[arg-type]
