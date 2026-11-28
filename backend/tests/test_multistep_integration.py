"""End-to-end harness for the multi-step visual agent loop.

The VLM and screen are stubbed with realistic replies; everything else is the
real loop (planning, action execution, subgoal completion, finishing).
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from agent.abort import AbortController
from agent.loop_detector import LoopDetector
from agent.task_plan import TaskPlan, Subgoal
from agent.vision_agent import VisionAgent


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), (20, 30, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def _agent(monkeypatch):
    agent = VisionAgent.__new__(VisionAgent)
    agent.abort = AbortController()
    agent.loop_detector = LoopDetector()
    agent.history = []
    agent.plan = TaskPlan(goal="goal", subgoals=[])
    agent.max_steps = 12
    agent.model = "qwen2.5vl:7b"
    monkeypatch.setattr(agent, "_vision_model_available", lambda: (True, ""))
    agent._som = False
    agent._app_kb = False
    agent._recovery_attempts = 0
    agent._recovery_hint = ""
    agent._recovery_guidance = 0
    agent.last_capture_detail = "test"
    agent._spoken = []
    monkeypatch.setattr(agent, "_speak", agent._spoken.append)
    monkeypatch.setattr(agent, "_capture_for_vlm", lambda: (_png(), 640, 360))
    monkeypatch.setattr(agent, "_verify_post_action", lambda before, action: _png())

    class Controller:
        def __init__(self):
            self.actions = []

        def to_base64(self, raw: bytes) -> str:
            return base64.b64encode(raw).decode("ascii")

        def click(self, *a):
            self.actions.append(("click", a))

        def double_click(self, *a):
            self.actions.append(("double_click", a))

        def move_and_drag(self, *a):
            self.actions.append(("drag", a))

        def scroll(self, *a):
            self.actions.append(("scroll", a))

        def type_text(self, *a):
            self.actions.append(("type", a))

        def press_key(self, *a):
            self.actions.append(("key", a))

        def click_global(self, *a):
            self.actions.append(("click_global", a))

    agent.controller = Controller()
    return agent


@pytest.mark.asyncio
async def test_three_subgoals_finish_without_manual_steps(monkeypatch):
    agent = _agent(monkeypatch)
    monkeypatch.setattr("agent.vision_agent.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "agent.checkpoint.record_progress", lambda *a, **k: None
    )
    monkeypatch.setattr(
        agent,
        "_subgoal_complete",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(agent, "_app_already_open", lambda _text: False)
    monkeypatch.setattr(agent, "_launch_app_from_subgoal", lambda _text: False)

    replies = iter([
        {"message": {"content": '{"thought":"click General","action":"CLICK","coordinates":[100,100],"subgoal_done":true}'}},
        {"message": {"content": '{"thought":"delete cube","action":"KEY","text":"x","subgoal_done":true}'}},
        {"message": {"content": '{"thought":"add plane","action":"CLICK","coordinates":[200,200],"subgoal_done":true}'}},
        {"message": {"content": '{"thought":"all visible","action":"FINISH"}'}},
    ])
    monkeypatch.setattr(
        agent, "_chat_with_image", lambda system, prompt, image, format_json=False: next(replies)
    )

    plan = TaskPlan(
        goal="project, cube, plane",
        subgoals=[
            Subgoal(index=1, text="make a new general project"),
            Subgoal(index=2, text="delete the default cube"),
            Subgoal(index=3, text="add a plane"),
        ],
    )

    result = agent.run_visual_task("project, cube, plane", plan=plan)

    assert "Task finished" in result, result
    assert all(step.done for step in plan.subgoals)
    assert len(agent.controller.actions) == 3
    assert "All steps are done." in agent._spoken


def _three_step_plan():
    return TaskPlan(
        goal="project, cube, plane",
        subgoals=[
            Subgoal(index=1, text="make a new general project"),
            Subgoal(index=2, text="delete the default cube"),
            Subgoal(index=3, text="add a plane"),
        ],
    )


def _quiet_loop_helpers(monkeypatch, agent):
    monkeypatch.setattr("agent.vision_agent.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("agent.checkpoint.record_progress", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_subgoal_complete", lambda *a, **k: True)
    monkeypatch.setattr(agent, "_app_already_open", lambda _text: False)
    monkeypatch.setattr(agent, "_launch_app_from_subgoal", lambda _text: False)


def test_one_transient_vlm_failure_does_not_abort_the_task(monkeypatch):
    agent = _agent(monkeypatch)
    _quiet_loop_helpers(monkeypatch, agent)
    replies = iter([
        {"message": {"content": '{"thought":"model blip","action":"FAIL"}'}},
        {"message": {"content": '{"thought":"click General","action":"CLICK","coordinates":[100,100],"subgoal_done":true}'}},
        {"message": {"content": '{"thought":"delete cube","action":"KEY","text":"x","subgoal_done":true}'}},
        {"message": {"content": '{"thought":"add plane","action":"CLICK","coordinates":[200,200],"subgoal_done":true}'}},
        {"message": {"content": '{"thought":"all visible","action":"FINISH"}'}},
    ])
    monkeypatch.setattr(
        agent, "_chat_with_image", lambda system, prompt, image, format_json=False: next(replies)
    )

    result = agent.run_visual_task("project, cube, plane", plan=_three_step_plan())

    assert "Task finished" in result, result


def test_subgoal_progress_works_when_model_omits_subgoal_done(monkeypatch):
    """Small local models often omit the flag; fresh-screen evidence must win."""
    agent = _agent(monkeypatch)
    _quiet_loop_helpers(monkeypatch, agent)
    replies = iter([
        {"message": {"content": '{"thought":"click General","action":"CLICK","coordinates":[100,100]}'}},
        {"message": {"content": '{"thought":"delete cube","action":"KEY","text":"x"}'}},
        {"message": {"content": '{"thought":"add plane","action":"CLICK","coordinates":[200,200]}'}},
        {"message": {"content": '{"thought":"all visible","action":"FINISH"}'}},
    ])
    monkeypatch.setattr(
        agent, "_chat_with_image", lambda system, prompt, image, format_json=False: next(replies)
    )

    plan = _three_step_plan()
    result = agent.run_visual_task("project, cube, plane", plan=plan)

    assert "Task finished" in result, result
    assert all(step.done for step in plan.subgoals)
