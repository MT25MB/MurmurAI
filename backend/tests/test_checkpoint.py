"""Persistent task checkpoints let a paused multi-step job resume cleanly."""

from __future__ import annotations

import json

from agent import checkpoint


def test_checkpoint_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    cp = checkpoint.Checkpoint(
        goal="Open Blender and render",
        subgoals=["Open Blender", "Set camera", "Render image"],
        completed=["Open Blender", "Set camera"],
        active_index=2,
    )
    checkpoint.save(cp)
    loaded = checkpoint.load_last()

    assert loaded is not None
    assert loaded.goal == cp.goal
    assert loaded.completed == ["Open Blender", "Set camera"]
    assert loaded.active_index == 2


def test_checkpoint_summary_names_next_subgoal(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    cp = checkpoint.Checkpoint(
        goal="Render image",
        subgoals=["Open Blender", "Render image"],
        completed=["Open Blender"],
        active_index=1,
    )
    summary = checkpoint.describe(cp)
    assert "Render image" in summary
    assert "step 2" in summary


def test_load_last_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    assert checkpoint.load_last() is None


def test_checkpoint_saves_only_verified_subgoals(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    checkpoint.record_progress(
        "Do a task",
        subgoals=["One", "Two", "Three"],
        completed=["One"],
        active_index=1,
    )
    loaded = checkpoint.load_last()
    assert loaded.completed == ["One"]
    assert loaded.active_index == 1
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["completed"] == ["One"]


def test_resume_restarts_at_first_uncompleted_subgoal(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    cp = checkpoint.Checkpoint(
        goal="Task", subgoals=["A", "B", "C"], completed=["A"], active_index=1
    )
    remaining = checkpoint.resume_subgoals(cp)
    assert remaining == ["B", "C"]


def test_checkpoint_status_voice_command(tmp_path, monkeypatch):
    import asyncio

    import main

    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    checkpoint.record_progress("Task", ["A", "B", "C"], ["A"], 1)
    spoken: list[str] = []

    async def fake_speak(session, send, reply, stream=False):
        spoken.append(reply)

    monkeypatch.setattr(main, "_speak_and_return", fake_speak)

    async def run():
        session = type("S", (), {
            "add_turn": lambda self, *a: None,
            "uptime": lambda self: 0,
        })()
        async def send(msg):
            return None
        handled = await main._try_checkpoint_phrase(session, send, "what step did we stop on?")
        assert handled is True

    asyncio.run(run())
    assert any("step 2" in text for text in spoken)
