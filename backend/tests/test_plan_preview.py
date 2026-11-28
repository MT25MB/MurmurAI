"""Spoken plan-preview mode: parsing, formatting and single-use decisions."""

from __future__ import annotations

import json

import pytest

import agent.brain as brain
import agent.vision_agent as va
import main
from agent.state import SessionState
from agent.plan_preview import (
    PlanPreview,
    classify,
    extract_files,
    pick_engine,
    should_auto_preview,
)


def test_multi_step_gui_goal_is_detected_for_voice_commands():
    goal = (
        "open up the blender app, start a new project and name it fish, "
        "delete the default cube and add a sphere"
    )
    assert main._is_multi_step_gui_goal(goal) is True
    assert main._is_multi_step_gui_goal("open Blender") is False
    assert main._is_multi_step_gui_goal("rewrite notes.txt and save it") is False
    # Navigation verbs count as GUI actions: this prompt must use the visual
    # planner in one turn instead of doing two calls and asking a question.
    assert main._is_multi_step_gui_goal(
        "open firefox, search up apple, go to images, go to the link of one of the images"
    ) is True


def test_preview_phrase_extracts_the_goal():
    decision = classify("Preview what you'd do to open Blender and delete the cube")

    assert decision.kind == "preview"
    assert "open Blender" in decision.goal
    assert "delete the cube" in decision.goal


def test_decision_phrases_are_recognized():
    assert classify("Go ahead").kind == "approve"
    assert classify("Yes, confirm").kind == "approve"
    assert classify("Execute the plan").kind == "approve"
    # A preview prompt ends by asking "are you ready?" - a bare "yes" must
    # approve it instead of discarding the plan and re-asking the model.
    for phrase in ("Yes", "yes.", "yeah", "yep", "yup", "ok", "okay", "sure",
                   "yes please", "go for it", "let's do it", "do that"):
        assert classify(phrase).kind == "approve", phrase
    assert classify("Skip step two").numbers == [2]
    assert classify("Skip steps 2 and 4").numbers == [2, 4]
    assert classify("Cancel").kind == "cancel"
    assert classify("Never mind").kind == "cancel"
    assert classify("What time is it?").kind == "none"


def test_file_targets_are_extracted_from_text():
    found = extract_files("edit report.docx then save /tmp/notes.txt")

    assert "report.docx" in found
    assert "notes.txt" in found


def test_spoken_preview_lists_steps_tools_and_next_choices():
    preview = PlanPreview(
        goal="rewrite report.docx",
        steps=["open report.docx", "rewrite the summary", "save the file"],
        tools=["manage_files"],
        files=["report.docx"],
        engine="brain",
    )

    spoken = preview.spoken()

    assert "Step 1" in spoken and "Step 3" in spoken
    assert "report.docx" in spoken
    assert "manage_files" in spoken
    assert "go ahead" in spoken.lower()
    assert "skip step" in spoken.lower()
    assert "cancel" in spoken.lower()


def test_skip_step_removes_it_from_execution():
    preview = PlanPreview(
        goal="do three things",
        steps=["first", "second", "third"],
        tools=[],
        files=[],
        engine="brain",
    )

    announcement = preview.skip([2])

    assert "step 2" in announcement.lower()
    assert preview.active_steps() == ["first", "third"]
    assert 2 in preview.skipped


def test_auto_preview_only_for_multi_step_or_file_tasks():
    multi = "open Blender and delete the cube"
    assert should_auto_preview(multi, {"preview_plans": True})
    assert should_auto_preview("rewrite notes.txt", {"preview_plans": True})
    assert not should_auto_preview("what time is it", {"preview_plans": True})
    assert not should_auto_preview(multi, {"preview_plans": False})


def test_engine_selection_prefers_vision_for_gui_goals():
    assert pick_engine("open Blender and delete the cube") == "vision"
    assert pick_engine("rewrite notes.txt") == "brain"


def test_preview_plans_defaults_off_and_toggles_by_voice(monkeypatch, tmp_path):
    import system.settings_tools as st

    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "_CACHE", None)

    assert st.load_settings()["preview_plans"] is False
    assert "preview" in st.handle_voice_command("preview plans on").lower()
    assert st.load_settings()["preview_plans"] is True
    st.handle_voice_command("preview plans off")
    assert st.load_settings()["preview_plans"] is False


def _sample_preview(engine="brain"):
    return PlanPreview(
        goal="rewrite report.docx",
        steps=["open report.docx", "rewrite the summary", "save the file"],
        tools=["manage_files"],
        files=["report.docx"],
        engine=engine,
    )


@pytest.fixture
def plan_env(monkeypatch):
    session = SessionState()
    sent: list = []

    async def send(message):
        sent.append(message)

    monkeypatch.setattr(main.app_state, "speaker", None)
    return session, send, sent


@pytest.mark.asyncio
async def test_preview_request_builds_and_speaks_a_plan_without_executing(
    plan_env, monkeypatch
):
    session, send, sent = plan_env
    built = []

    def fake_build(goal):
        built.append(goal)
        return _sample_preview()

    monkeypatch.setattr(main.app_state.brain, "build_preview", fake_build)
    brain_calls = []
    monkeypatch.setattr(
        main.app_state.brain, "think_and_act", lambda **kwargs: brain_calls.append(kwargs)
    )

    handled, routed = await main._route_plan_preview(
        session, send, "Preview what you'd do to rewrite report.docx"
    )

    assert handled is True and routed == ""
    assert built == ["rewrite report.docx"]
    assert brain_calls == []
    assert session.pending_plan is not None
    assert any("Preview:" in str(getattr(m, "text", "")) for m in sent)


@pytest.mark.asyncio
async def test_bare_yes_executes_the_preview_and_always_answers(plan_env, monkeypatch):
    """Screenshot regression: 'yes' to 'are you ready?' must run the GUI task."""
    session, send, sent = plan_env
    session.pending_plan = _sample_preview()
    executed = []
    monkeypatch.setattr(
        main.app_state.brain,
        "execute_preview",
        lambda preview: executed.append(preview) or "",
    )

    handled, _ = await main._route_plan_preview(session, send, "Yes")

    assert handled is True
    assert len(executed) == 1
    assert "nothing to report" in " ".join(
        str(getattr(m, "text", "")) for m in sent
    ).lower()


@pytest.mark.asyncio
async def test_go_ahead_executes_the_preview_once_then_clears_it(plan_env, monkeypatch):
    session, send, _ = plan_env
    session.pending_plan = _sample_preview()
    executed = []
    monkeypatch.setattr(
        main.app_state.brain,
        "execute_preview",
        lambda preview: executed.append(preview) or "Done.",
    )

    handled, routed = await main._route_plan_preview(session, send, "Go ahead")

    assert handled is True and routed == ""
    assert len(executed) == 1
    assert session.pending_plan is None
    # A replayed approval must not execute a second time.
    replayed, _ = await main._route_plan_preview(session, send, "Yes, confirm")
    assert replayed is False


@pytest.mark.asyncio
async def test_skip_step_two_adjusts_preview_without_executing(plan_env, monkeypatch):
    session, send, sent = plan_env
    session.pending_plan = _sample_preview()
    executed = []
    monkeypatch.setattr(
        main.app_state.brain, "execute_preview", lambda preview: executed.append(preview)
    )

    handled, _ = await main._route_plan_preview(session, send, "Skip step two")

    assert handled is True
    assert executed == []
    assert session.pending_plan.skipped == {2}
    assert any("Skipping step 2" in str(getattr(m, "text", "")) for m in sent)


@pytest.mark.asyncio
async def test_cancel_and_unrelated_speech_and_stop_phrase_discard_preview(plan_env):
    session, send, _ = plan_env

    session.pending_plan = _sample_preview()
    handled, _ = await main._route_plan_preview(session, send, "Cancel")
    assert handled is True and session.pending_plan is None

    session.pending_plan = _sample_preview()
    handled, routed = await main._route_plan_preview(session, send, "What time is it?")
    assert handled is False and routed == "What time is it?"
    assert session.pending_plan is None

    session.pending_plan = _sample_preview()
    handled, routed = await main._route_plan_preview(session, send, "Stop automation")
    assert handled is False and session.pending_plan is None


@pytest.mark.asyncio
async def test_auto_preview_for_opted_in_multi_step_task(plan_env, monkeypatch):
    session, send, _ = plan_env
    monkeypatch.setattr(main, "_preview_settings", lambda: {"preview_plans": True})

    def fake_build(goal):
        return _sample_preview()

    monkeypatch.setattr(main.app_state.brain, "build_preview", fake_build)

    handled, _ = await main._route_plan_preview(
        session, send, "rewrite report.docx and save it"
    )

    assert handled is True and session.pending_plan is not None


@pytest.mark.asyncio
async def test_preview_request_from_text_input_never_calls_the_brain(plan_env, monkeypatch):
    session, send, _ = plan_env

    def fake_build(goal):
        return _sample_preview()

    monkeypatch.setattr(main.app_state.brain, "build_preview", fake_build)

    def no_brain(**_kwargs):
        raise AssertionError("preview must not reach the model turn")

    monkeypatch.setattr(main.app_state.brain, "think_and_act", no_brain)
    await main.handle_text_input(session, send, "Preview what you'd do to rewrite report.docx")

    assert session.pending_plan is not None


def _tool_call(name, args):
    return {"function": {"name": name, "arguments": json.dumps(args)}}


def test_brain_dry_run_never_dispatches_a_tool(monkeypatch):
    agent = brain.Brain()
    calls = [_tool_call("manage_files", {"operation": "write", "path": "report.docx"})]
    monkeypatch.setattr(agent, "_chat", lambda *a, **k: {"message": {"tool_calls": calls}})
    dispatched = []
    monkeypatch.setattr(
        brain, "dispatch_tool", lambda *a, **k: dispatched.append(a) or "done"
    )

    reply = agent.think_and_act("rewrite report.docx", dry_run=True)

    assert dispatched == []
    assert "Step 1" in reply
    assert "manage_files" in reply
    assert "report.docx" in reply


def test_executing_a_preview_runs_only_the_non_skipped_calls(monkeypatch):
    agent = brain.Brain()
    calls = [
        _tool_call("first_tool", {"path": "a.txt"}),
        _tool_call("second_tool", {"path": "b.txt"}),
    ]
    monkeypatch.setattr(agent, "_chat", lambda *a, **k: {"message": {"tool_calls": calls}})
    preview = agent.build_preview("do two things")
    preview.skip([1])
    dispatched = []
    monkeypatch.setattr(
        brain,
        "dispatch_tool",
        lambda name, args, safety: dispatched.append(name) or "ok",
    )

    result = agent.execute_preview(preview)

    assert dispatched == ["second_tool"]
    assert "ok" in result


def test_vision_dry_run_previews_steps_without_capturing_or_clicking(monkeypatch):
    from types import SimpleNamespace

    from agent.task_plan import Subgoal

    spoken: list[str] = []
    monkeypatch.setattr(va.VisionAgent, "_speak", staticmethod(lambda text: spoken.append(text)))
    fake_plan = SimpleNamespace(
        subgoals=[Subgoal(0, "open Blender"), Subgoal(1, "delete the cube")]
    )
    monkeypatch.setattr(va, "build_plan", lambda goal, **kwargs: fake_plan)
    class NoCapture:
        def capture(self):
            raise AssertionError("dry run must not capture the screen")

    agent = va.VisionAgent(
        controller=NoCapture(), use_som=False, use_app_knowledge=False
    )

    preview = agent.run_visual_task("open Blender and delete the cube", dry_run=True)

    assert "Step 1" in preview and "delete the cube" in preview
    assert spoken
    assert agent.last_preview is not None
    assert agent.last_preview.engine == "vision"
