"""Subgoal planning, bounded history, loop detection and abort tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import agent.task_plan as task_plan
from agent.task_plan import (
    TaskPlan, Subgoal, build_plan, format_history, _fallback_split, _is_multistep,
)
from agent.loop_detector import LoopDetector, action_fingerprint, hamming, screen_hash
from agent.abort import abort_controller, is_abort_phrase
from agent.vision_agent import VisionAgent


def test_fallback_split_multistep():
    parts = _fallback_split("Open Blender, delete the cube, add a monkey, and subdivide twice")
    assert len(parts) >= 4
    assert parts[0].startswith("Open Blender")


def test_user_style_multistep_goal_decomposes():
    goal = (
        "open up the blender app, start a new project and name it fish, "
        "delete the default cube and add a sphere"
    )
    parts = _fallback_split(goal)
    assert len(parts) >= 4
    assert "blender" in parts[0].lower()
    assert any("fish" in part.lower() for part in parts)
    assert any("cube" in part.lower() for part in parts)
    assert any("sphere" in part.lower() for part in parts)


def test_collapsed_multistep_goal_falls_back_to_split(monkeypatch):
    """A local model that returns one step cannot swallow the later actions."""
    goal = "open blender, make a new general project, delete the default cube, and add a sphere"
    assert _is_multistep(goal)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": json.dumps({"subgoals": [goal]})}}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return _Resp()

    monkeypatch.setattr(task_plan.httpx, "Client", lambda **_kwargs: _Client())
    plan = build_plan(goal)
    assert len(plan.subgoals) >= 4
    assert plan.subgoals[0].text.lower().startswith("open blender")
    assert any("cube" in s.text.lower() for s in plan.subgoals)
    assert any("sphere" in s.text.lower() for s in plan.subgoals)


def test_launch_subgoal_is_resolved_by_os_tool(monkeypatch):
    import tools.os_tools as os_tools

    seen = []
    monkeypatch.setattr(
        os_tools, "open_application", lambda app: seen.append(app) or f"Opened {app}."
    )
    assert VisionAgent._launch_app_from_subgoal("Open up the Blender app") is True
    assert seen == ["Blender"]
    seen.clear()
    # Multi-action subgoals must not be mistaken for an app launch.
    assert VisionAgent._launch_app_from_subgoal(
        "start a new project and name it fish"
    ) is False
    assert seen == []


def test_plan_progress_tracking():
    plan = TaskPlan(goal="a,b", subgoals=[Subgoal(0, "a"), Subgoal(1, "b")])
    assert plan.current().text == "a"
    plan.complete_current()
    assert plan.current().text == "b" and not plan.all_done
    plan.complete_current()
    assert plan.all_done
    assert "FOCUS ON SUBGOAL" in TaskPlan(goal="x", subgoals=[Subgoal(0, "x")]).progress_section()


def test_history_is_bounded_and_brief():
    recs = [SimpleNamespace(step=i, action="CLICK", element_id=None,
                            coordinates=[10, 20], text=None, result="executed")
            for i in range(12)]
    lines = format_history(recs).splitlines()
    assert len(lines) == 6
    assert "CLICK" in lines[0]


def test_action_fingerprint_groups_near_identical():
    a = action_fingerprint("CLICK", None, [100, 200], None)
    b = action_fingerprint("CLICK", None, [101, 199], None)
    assert a == b
    assert action_fingerprint("KEY", None, None, "shift+a") != a


def test_loop_detector_repeated_action_and_progress_reset():
    ld = LoopDetector(repeat_threshold=3)
    fp = action_fingerprint("CLICK", None, [100, 200], None)
    for _ in range(3):
        ld.record(fp, None, 0)
    status = ld.assess(0)
    assert status.stuck and status.kind == "repeat_action"
    ld.mark_progress(1)
    assert not ld.assess(1).stuck


def test_screen_hash_and_hamming():
    import io
    from PIL import Image

    img = Image.new("L", (64, 64), 0)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    h1 = screen_hash(buf.getvalue())
    h2 = screen_hash(buf.getvalue())
    assert h1 is not None and h1 == h2
    assert hamming(h1, h1) == 0
    assert hamming(0b1010, 0b1000) == 1


def test_abort_controller_and_listener():
    abort_controller.reset()
    seen = []
    abort_controller.add_listener(lambda r: seen.append(r))
    abort_controller.abort("test")
    assert abort_controller.is_aborted() and seen == ["test"]
    abort_controller.reset()
    assert not abort_controller.is_aborted()


def test_abort_phrases():
    assert is_abort_phrase("stop automation")
    assert is_abort_phrase("abort task")
    assert not is_abort_phrase("what time is it")


def test_parse_vlm_json_subgoal_done():
    parsed = VisionAgent._parse_vlm_json(
        '{"thought":"x","action":"CLICK","coordinates":[100,200],"subgoal_done":true}'
    )
    assert len(parsed) == 7 and parsed[-1] is True
    assert parsed[1] == "CLICK" and parsed[3] == [100.0, 200.0]
