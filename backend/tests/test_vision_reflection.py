"""The visual agent must verify a claimed finish before declaring success."""

from __future__ import annotations

import base64
import io

from PIL import Image

from agent.task_plan import Subgoal, TaskPlan
from agent.vision_agent import VisionAgent


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 180), (10, 12, 18)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeController:
    def capture(self):
        return _png(), 320, 180

    def to_base64(self, png: bytes) -> str:
        return base64.b64encode(png).decode()


def _agent(monkeypatch, tmp_path) -> VisionAgent:
    monkeypatch.setattr("agent.vision_agent.LOGS_DIR", tmp_path)
    agent = VisionAgent(
        model="qwen2.5vl:7b",
        controller=_FakeController(),
        use_som=False,
        use_app_knowledge=False,
        max_steps=2,
    )
    monkeypatch.setattr(agent, "_launch_app_from_subgoal", lambda _text: False)
    monkeypatch.setattr(agent, "_speak", lambda _text: None)
    # Vision availability is covered by its own test; these loop tests mock the VLM.
    monkeypatch.setattr(agent, "_vision_model_available", lambda: (True, ""))
    return agent


def _finish_response(thought: str = "I think it is done."):
    return thought, "FINISH", None, None, None, None, True


def test_ollama_image_request_uses_native_images_field(monkeypatch, tmp_path):
    agent = _agent(monkeypatch, tmp_path)
    seen: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "{}"}}

    class FakeClient:
        def post(self, path, json):
            seen.update(json)
            seen["path"] = path
            return FakeResponse()

    agent._client = FakeClient()
    try:
        agent._chat_with_image("System", "Prompt", "BASE64PNG", format_json=True)
        assert seen["path"] == "/api/chat"
        assert seen["messages"][1]["content"] == "Prompt"
        assert seen["messages"][1]["images"] == ["BASE64PNG"]
        assert "format" not in seen
    finally:
        agent.abort.remove_listener(agent._announce_stop)


def test_already_open_app_is_not_launched_again(monkeypatch, tmp_path):
    from types import SimpleNamespace

    agent = _agent(monkeypatch, tmp_path)
    agent._app_kb = True
    agent._detect_app = lambda: SimpleNamespace(title="Blender 4.0")
    try:
        assert agent._app_already_open("open up blender") is True
        assert agent._app_already_open("create a new project") is False
    finally:
        agent.abort.remove_listener(agent._announce_stop)


def test_json_is_extracted_from_plain_or_fenced_vlm_reply():
    assert VisionAgent._extract_json('```json\n{"action":"CLICK"}\n```') == {"action": "CLICK"}
    assert VisionAgent._extract_json('Here: {"complete": true} done') == {"complete": True}
    assert VisionAgent._extract_json("nothing") == {}


def test_vlm_outage_is_fail_not_finish(monkeypatch, tmp_path):
    agent = _agent(monkeypatch, tmp_path)

    class _BrokenClient:
        def post(self, *_args, **_kwargs):
            raise RuntimeError("ollama offline")

    agent._client = _BrokenClient()
    try:
        parsed = agent._ask_vlm("goal", "b64", 320, 180, "", {}, None, "")
        assert parsed[1] == "FAIL"
        assert "vision request failed" in parsed[0].lower()
    finally:
        agent.abort.remove_listener(agent._announce_stop)


def test_unparseable_vlm_reply_is_fail_not_finish():
    parsed = VisionAgent._parse_vlm_json("not json at all")
    assert parsed[1] == "FAIL"
    assert VisionAgent._parse_vlm_json('{"thought":"x"}')[1] == "FAIL"


def test_subgoal_is_not_complete_without_visible_evidence(monkeypatch, tmp_path):
    agent = _agent(monkeypatch, tmp_path)
    monkeypatch.setattr(
        agent, "_reflect_on_subgoal", lambda *a, **k: (False, "cube is still visible")
    )
    try:
        done = agent._subgoal_complete(
            "Delete the default cube", "goal", "b64", 320, 180, "", "done"
        )
        assert done is False
        assert "cube is still visible" in agent._recovery_hint
    finally:
        agent.abort.remove_listener(agent._announce_stop)


def test_reflected_finish_does_not_end_an_incomplete_plan(monkeypatch, tmp_path):
    agent = _agent(monkeypatch, tmp_path)
    monkeypatch.setattr(agent, "_ask_vlm", lambda *a, **k: _finish_response())
    monkeypatch.setattr(
        agent, "_reflect_on_subgoal", lambda *a, **k: (False, "scene still has the cube")
    )
    plan = TaskPlan(
        goal="open blender, delete the cube",
        subgoals=[Subgoal(0, "open blender"), Subgoal(1, "Delete the cube")],
    )
    try:
        result = agent.run_visual_task(plan.goal, max_steps=2, plan=plan)
        assert "Task finished" not in result
        assert "Reached max steps" in result
    finally:
        agent.abort.remove_listener(agent._announce_stop)


def test_reflected_finish_completes_a_finished_plan(monkeypatch, tmp_path):
    agent = _agent(monkeypatch, tmp_path)
    monkeypatch.setattr(agent, "_ask_vlm", lambda *a, **k: _finish_response())
    monkeypatch.setattr(agent, "_reflect_on_subgoal", lambda *a, **k: (True, "sphere is visible"))
    plan = TaskPlan(goal="Add a sphere", subgoals=[Subgoal(0, "Add a sphere")])
    try:
        result = agent.run_visual_task(plan.goal, max_steps=2, plan=plan)
        assert "Task finished" in result
    finally:
        agent.abort.remove_listener(agent._announce_stop)
