"""The agent refuses to act until required local components are present."""

from __future__ import annotations

import pytest

import main
import setup as setup_mod
from agent.state import SessionState
from agent.vision_agent import VisionAgent


@pytest.mark.asyncio
async def test_incomplete_setup_blocks_agent_work(monkeypatch):
    monkeypatch.setattr(setup_mod, "readiness", lambda: {
        "ready": False, "missing": ["model qwen2.5vl:7b is not installed"],
        "detail": "model qwen2.5vl:7b is not installed",
    })
    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    def no_brain(**_kwargs):
        raise AssertionError("brain must not run when setup is incomplete")

    monkeypatch.setattr(main.app_state.brain, "think_and_act", no_brain)
    await main.handle_text_input(SessionState(), send, "delete the default cube")

    assert any(getattr(m, "type", None) == "error" for m in sent)
    assert any("Setup is incomplete" in str(getattr(m, "text", "")) for m in sent)


@pytest.mark.asyncio
async def test_repair_commands_still_work_without_setup():
    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    assert await main._require_ready(SessionState(), send, "run diagnostics") is True
    assert sent == []


def test_vision_task_rejects_missing_model(monkeypatch, tmp_path):
    monkeypatch.setattr("agent.vision_agent.LOGS_DIR", tmp_path)
    agent = VisionAgent(
        model="qwen2.5vl:7b",
        controller=object(),
        use_som=False,
        use_app_knowledge=False,
    )
    monkeypatch.setattr(setup_mod, "ollama_status", lambda: {"running": True})
    monkeypatch.setattr(setup_mod, "pulled_models", lambda _models: {"qwen2.5vl:7b": False})

    try:
        result = agent.run_visual_task("delete the cube")
        assert "not installed" in result
    finally:
        agent.abort.remove_listener(agent._announce_stop)
