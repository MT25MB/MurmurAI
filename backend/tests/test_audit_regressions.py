"""Regression tests for confirmed audit defects.

Each test reproduces a real defect in isolation, without microphones, model
weights, network access or OS permissions. They are written before the fix so a
failure proves the bug exists.
"""

from __future__ import annotations

import json

import pytest

import agent.checkpoint as checkpoint
from agent.loop_detector import LoopDetector
from agent.vision_agent import VisionAgent
from memory import MemoryVault


class TestVlmOutputHardening:
    def test_string_false_is_not_treated_as_complete(self):
        agent = VisionAgent.__new__(VisionAgent)
        agent.reflect = True
        agent._recovery_attempts = 0
        agent._recovery_hint = ""
        agent._chat_with_image = lambda *a, **k: {
            "message": {"content": '{"complete": "false", "evidence": "nothing changed"}'}
        }
        complete = agent._subgoal_complete("step", "goal", "b64", 100, 100, "", "thought")
        assert complete is False

    def test_string_true_is_accepted(self):
        agent = VisionAgent.__new__(VisionAgent)
        agent.reflect = True
        agent._recovery_attempts = 0
        agent._recovery_hint = ""
        agent._chat_with_image = lambda *a, **k: {
            "message": {"content": '{"complete": "true", "evidence": "saved"}'}
        }
        assert agent._subgoal_complete("step", "goal", "b64", 10, 10, "", "t") is True

    @pytest.mark.parametrize("payload", [
        '{"coordinates": {"x": 0.2, "y": 0.5}}',
        '{"coordinates": "ab"}',
        '{"coordinates": ["0.2", "oops"]}',
        '{"drag_to": {"x": 1, "y": 2}}',
    ])
    def test_malformed_coordinates_are_ignored_not_crashing(self, payload):
        result = VisionAgent._parse_vlm_json(payload)
        assert result[3] is None or (
            isinstance(result[3], list) and len(result[3]) == 2
        )

    def test_subgoal_done_string_false_is_false(self):
        parsed = VisionAgent._parse_vlm_json('{"subgoal_done": "false"}')
        assert parsed[-1] is False


class TestNoOpActions:
    def test_incomplete_actions_report_failure_not_success(self):
        agent = VisionAgent.__new__(VisionAgent)

        class Controller:
            def click(self, *_a):
                raise AssertionError("no click should be attempted")

        agent.controller = Controller()
        assert agent._execute("CLICK", None, None, None) is False
        assert agent._execute("DRAG", [1, 2], None, None) is False
        assert agent._execute("FINISH", None, None, None) is False

    def test_complete_actions_report_success(self):
        agent = VisionAgent.__new__(VisionAgent)
        called = []

        class Controller:
            def press_key(self, *args):
                called.append(args)

        agent.controller = Controller()
        assert agent._execute("KEY", None, None, "ctrl+z") is True
        assert called


class TestLoopAlignment:
    def test_failed_hashes_do_not_misalign_static_screen_detection(self):
        detector = LoopDetector(repeat_threshold=3)
        # Two failed screen hashes on subgoal 0 previously shifted every later
        # hash one slot too early, so three identical screens on subgoal 1 were
        # read as only two and the loop went unnoticed.
        detector.record("a", 111, 0)
        detector.record("a2", None, 0)
        detector.record("a3", None, 0)
        detector.record("b", 222, 1)
        detector.record("c", 222, 1)
        detector.record("d", 222, 1)
        status = detector.assess(1)
        assert status.stuck is True
        assert status.kind == "static_screen"


class TestCorruptLocalState:
    def test_corrupt_checkpoint_falls_back_instead_of_raising(self, tmp_path, monkeypatch):
        folder = tmp_path / "checkpoints"
        folder.mkdir()
        (folder / "bad.json").write_text(
            json.dumps({"goal": "g", "subgoals": ["s"], "active_index": "abc",
                        "updated_at": "nope"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", folder)
        loaded = checkpoint.load_last()
        assert loaded is not None
        assert loaded.active_index == 0
        assert loaded.updated_at >= 0

    def test_clear_does_not_resurrect_forgotten_fact(self, tmp_path):
        vault = MemoryVault(tmp_path / "memory.json")
        entry = vault.store("The project is called Orca")
        assert entry is not None
        assert vault.forget(entry["id"]) is True
        assert vault.clear() == 0
        assert vault.undo() is False
        assert vault.list() == []
