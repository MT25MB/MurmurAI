"""Tool schemas are valid, and destructive tools pause for confirmation."""

from __future__ import annotations

import pytest

from tools.os_tools import OS_TOOLS, dispatch_tool
from tools.installer_tool import INSTALL_TOOLS, install_application, detect_install_plan
from agent.brain import ALL_TOOLS, STOP_TOOL
from agent.vision_agent import DESCRIBE_TOOL


def _validate_schema(tool: dict):
    fn = tool["function"]
    assert {"name", "description", "parameters"} <= fn.keys()
    params = fn["parameters"]
    assert params["type"] == "object"
    assert isinstance(params["properties"], dict)
    assert isinstance(params.get("required", []), list)


def test_all_tool_schemas_valid():
    assert OS_TOOLS and INSTALL_TOOLS and STOP_TOOL and DESCRIBE_TOOL
    for tool in ALL_TOOLS:
        _validate_schema(tool)
    names = [t["function"]["name"] for t in ALL_TOOLS]
    assert len(names) == len(set(names)), "duplicate tool names"
    for expected in ("run_terminal_command", "manage_files", "install_application",
                     "describe_screen", "stop_automation"):
        assert expected in names


def test_dispatch_unknown_tool():
    assert "Unknown tool" in dispatch_tool("does_not_exist", {}, None)  # type: ignore[arg-type]


def test_dispatch_describe_screen_is_registered(monkeypatch):
    import tools.os_tools as os_tools

    called = {}
    def fake_describe(focus="overview"):
        called["focus"] = focus
        return "described"

    monkeypatch.setattr("agent.vision_agent.describe_screen", fake_describe, raising=False)
    result = dispatch_tool("describe_screen", {"focus": "dialogs"}, None)  # type: ignore[arg-type]
    assert result == "described"
    assert called["focus"] == "dialogs"


def test_installer_builds_winget_command(monkeypatch):
    import tools.installer_tool as it

    monkeypatch.setattr(it.shutil, "which", lambda name: "/usr/bin/winget" if name == "winget" else None)
    monkeypatch.setattr(
        it, "_run_capture",
        lambda cmd, timeout=30: "Name        Id                       Version\nBlender     BlenderFoundation.Blender  4.2.0",
    )
    plan = detect_install_plan("Blender")
    assert plan is not None and plan.manager == "winget"
    assert plan.package_id == "BlenderFoundation.Blender"
    assert "install" in plan.install_command and "--silent" in plan.install_command
    assert "--accept-package-agreements" in plan.install_command


def test_install_pauses_for_confirmation_when_denied(monkeypatch):
    import tools.installer_tool as it
    from tools.event_bus import ToolEventBus

    bus = ToolEventBus()
    # Replace request_confirmation with a deterministic denial recorder.
    seen = {}

    def fake_request(description, command, timeout=180):
        seen["description"] = description
        seen["command"] = command
        return False

    bus.request_confirmation = fake_request  # type: ignore[method-assign]
    it.tool_bus = bus
    it.detect_install_plan = lambda name: it.PackagePlan(  # type: ignore[assignment]
        manager="winget", package_id="Vendor.App", search_command=[],
        install_command=["winget", "install", "--id", "Vendor.App"], description="test",
    )
    result = install_application("FakeApp")
    assert "cancel" in result.lower()
    assert "FakeApp" in seen["description"]
    assert seen["command"], "exact command must be shown for approval"


def test_install_emits_confirmation_event_then_proceeds_on_approve(monkeypatch):
    import tools.installer_tool as it
    from tools.event_bus import ToolEventBus
    from agent.state import ServerMessage

    events = []
    bus = ToolEventBus()
    bus.emit = lambda m: events.append(json.loads(m.to_json()))  # type: ignore[method-assign]
    bus.request_confirmation = lambda description, command, timeout=180: True  # type: ignore[method-assign]
    it.tool_bus = bus
    it.detect_install_plan = lambda name: it.PackagePlan(  # type: ignore[assignment]
        manager="winget", package_id="Vendor.App", search_command=[],
        install_command=["cmd", "/c", "echo installing 45%"], description="test",
    )
    monkeypatch.setattr(
        it.subprocess, "Popen",
        lambda *a, **k: SimpleNamespace(
            stdout=iter(["installing 45%\n", "done\n"]),
            wait=lambda: 0,
        ),
    )
    result = install_application("FakeApp")
    assert "installed successfully" in result.lower()
    assert any(e["type"] == "progress" for e in events)
    assert any(e["type"] == "text_output" for e in events)


import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402
