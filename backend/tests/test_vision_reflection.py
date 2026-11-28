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
    def capture(self, max_dim=None):
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


def test_vision_server_error_retries_with_a_smaller_capture(monkeypatch, tmp_path):
    import base64
    import io

    from PIL import Image

    agent = _agent(monkeypatch, tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (1600, 900), "black").save(buf, format="PNG")
    big = base64.b64encode(buf.getvalue()).decode()

    calls = []

    class Response:
        def __init__(self, status, payload):
            self.status_code = status
            self.is_success = status < 400
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return ""

    class Client:
        def post(self, path, json):
            calls.append(json)
            if len(calls) == 1:
                return Response(500, {"error": "image too large"})
            return Response(200, {"message": {"content": "{}"}})

    agent._client = Client()
    try:
        agent._chat_with_image("System", "Prompt", big)
    finally:
        agent.abort.remove_listener(agent._announce_stop)

    assert len(calls) == 2
    assert calls[1]["messages"][1]["images"][0] != big
    assert calls[1]["options"]["num_ctx"] == 4096


def test_vision_errors_are_plain_english_without_http_details(monkeypatch, tmp_path):
    import pytest

    agent = _agent(monkeypatch, tmp_path)

    class Response:
        status_code = 404
        is_success = False

        def json(self):
            return {"error": "model 'qwen2.5vl:7b' not found, try pulling"}

        @property
        def text(self):
            return ""

    class Client:
        def post(self, path, json):
            return Response()

    agent._client = Client()
    try:
        with pytest.raises(RuntimeError) as exc:
            agent._chat_with_image("System", "Prompt", "BASE64PNG")
    finally:
        agent.abort.remove_listener(agent._announce_stop)

    message = str(exc.value)
    assert "not found" in message
    assert "http" not in message.lower()
    assert "developer.mozilla" not in message


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
