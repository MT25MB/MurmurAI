"""The shell can ask the sidecar to exit cleanly instead of hard-killing it.

A hard kill leaves PyInstaller's ~744 MB onefile extraction directory behind on
every quit, which eventually fills the disk and breaks the next launch.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class _FakeServer:
    def __init__(self) -> None:
        self.should_exit = False


def test_shutdown_endpoint_flags_uvicorn_server():
    server = _FakeServer()
    with patch.dict(main.__dict__, {"_uvicorn_server": server}):
        response = TestClient(main.app).post("/shutdown")

    assert response.status_code == 200
    assert response.json() == {"status": "shutting_down"}
    assert server.should_exit is True


def test_shutdown_without_running_server_is_still_safe():
    with patch.dict(main.__dict__, {"_uvicorn_server": None}):
        response = TestClient(main.app).post("/shutdown")

    assert response.status_code == 200
    assert response.json() == {"status": "shutting_down"}
