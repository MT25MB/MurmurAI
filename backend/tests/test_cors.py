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
