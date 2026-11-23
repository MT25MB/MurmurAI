"""Ollama pull-stream errors must reach the user instead of a generic stall."""

from __future__ import annotations

import pytest

import setup as app_setup


class FakeStream:
    def __init__(self, lines):
        self.lines = lines
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def aread(self):
        return b""


class FakeClient:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, *_args, **_kwargs):
        return FakeStream(self.lines)


@pytest.mark.asyncio
async def test_ollama_error_frame_becomes_an_actionable_pull_error(monkeypatch):
    lines = [
        '{"status":"pulling manifest"}',
        '{"error":"pull model manifest: file does not exist"}',
    ]
    monkeypatch.setattr(
        app_setup.httpx, "AsyncClient", lambda *_a, **_k: FakeClient(lines)
    )
    progress: list[tuple[int | None, str]] = []

    result = await app_setup.pull_model(
        "screen0-vission", lambda model, percent, status: progress.append((percent, status))
    )

    assert result["ok"] is False
    assert "file does not exist" in result["error"]
    assert "screen0-vission" in result["error"]
    assert any("file does not exist" in status for _, status in progress)


@pytest.mark.asyncio
async def test_stream_ending_mid_download_reports_last_progress_and_likely_cause(
    monkeypatch,
):
    lines = [
        '{"status":"pulling manifest"}',
        '{"status":"pulling abcd1234","total":1000,"completed":600}',
    ]
    monkeypatch.setattr(
        app_setup.httpx, "AsyncClient", lambda *_a, **_k: FakeClient(lines)
    )
    monkeypatch.setattr(app_setup, "_models_disk_free", lambda: 20_000_000_000)

    result = await app_setup.pull_model("qwen2.5:7b", lambda *_args: None)

    assert result["ok"] is False
    message = result["error"].lower()
    assert "before it finished" in message
    assert "disk space" in message
    assert "60%" in message


@pytest.mark.asyncio
async def test_low_disk_space_is_reported_before_a_long_download(monkeypatch):
    lines = [
        '{"status":"pulling manifest"}',
        '{"status":"pulling abcd1234","total":5_000_000_000,"completed":0}',
    ]
    monkeypatch.setattr(
        app_setup.httpx, "AsyncClient", lambda *_a, **_k: FakeClient(lines)
    )
    monkeypatch.setattr(app_setup, "_models_disk_free", lambda: 2_000_000_000)

    result = await app_setup.pull_model("qwen2.5:7b", lambda *_args: None)

    assert result["ok"] is False
    assert "disk space" in result["error"].lower()


@pytest.mark.asyncio
async def test_error_status_without_error_field_also_fails_cleanly(monkeypatch):
    lines = ['{"status":"error","detail":"model not found"}']
    monkeypatch.setattr(
        app_setup.httpx, "AsyncClient", lambda *_a, **_k: FakeClient(lines)
    )

    result = await app_setup.pull_model("missing:model", lambda *_args: None)

    assert result["ok"] is False
    assert result["error"] != "Pull stream ended without success status."
