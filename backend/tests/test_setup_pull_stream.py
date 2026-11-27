"""Model-pull progress frames must all arrive, in order, even under bursts."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

import main
from agent.state import ServerMessage


class FakeWebSocket:
    def __init__(self):
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict] = []

    async def accept(self):
        return None

    async def receive_text(self) -> str:
        return await self.inbox.get()

    async def send_text(self, payload: str):
        self.sent.append(json.loads(payload))
        await asyncio.sleep(0)


async def _burst_pull(model, progress):
    for index in range(12):
        progress(model, index * 8, f"chunk {index}")
        await asyncio.sleep(0)


async def _staged_pull(model, progress):
    progress(model, None, "pulling manifest")
    await asyncio.sleep(0)
    progress(model, None, "downloading layer")
    await asyncio.sleep(0)
    return {"ok": True, "model": model}


async def _run_pull(monkeypatch, pull, model="qwen3.5:4b"):
    import system.profiler as profiler

    monkeypatch.setattr(profiler, "model_fits_hardware", lambda *_a, **_k: True)
    monkeypatch.setattr(main.setup_module, "pull_model", pull)
    ws = FakeWebSocket()
    ws.inbox.put_nowait(json.dumps({"model": model}))
    task = asyncio.create_task(main.setup_pull_model(ws))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if any(m.get("type") in ("pull_complete", "error") for m in ws.sent):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return ws.sent


@pytest.mark.asyncio
async def test_unknown_model_cannot_start_an_unbounded_download(monkeypatch):
    import system.profiler as profiler

    monkeypatch.setattr(profiler, "model_fits_hardware", lambda *_a, **_k: True)
    called = []

    async def must_not_run(model, progress):
        called.append(model)
        return {"ok": True, "model": model}

    sent = await _run_pull(monkeypatch, must_not_run, model="qwen3.5:999b")
    assert called == []
    assert any(m.get("type") == "error" for m in sent)


@pytest.mark.asyncio
async def test_all_progress_frames_arrive_in_order(monkeypatch):
    sent = await _run_pull(monkeypatch, _burst_pull)
    frames = [m for m in sent if m.get("type") == "pull_progress"]
    assert [m["text"] for m in frames] == [f"chunk {i}" for i in range(12)]
    assert [m["percent"] for m in frames] == [i * 8 for i in range(12)]


@pytest.mark.asyncio
async def test_stages_without_byte_counts_still_move_progress(monkeypatch):
    sent = await _run_pull(monkeypatch, _staged_pull)
    percents = [m["percent"] for m in sent if m.get("type") == "pull_progress"]
    assert percents
    assert any(p is not None and p > 0 for p in percents), percents
    assert any(m.get("type") == "pull_complete" for m in sent)
