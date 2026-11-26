"""Agent brain ReAct loop, tool schemas, describe_screen, installer selection,
and strict confirmation gating for destructive actions.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.brain import ALL_TOOLS, Brain
from tools.installer_tool import detect_install_plan
from tools.safety import SafetyGate


def test_windows_calculator_resolves_to_a_store_protocol(monkeypatch):
    """Spoken app names must work on Windows without guessing an .exe path."""
    import tools.os_tools as os_tools

    opened = []
    monkeypatch.setattr(os_tools, "_sys", lambda: "Windows")
    monkeypatch.setattr(
        os_tools.os, "startfile", lambda target: opened.append(target), raising=False
    )

    assert os_tools.open_application("calculator") == "Opened calculator."
    assert opened[0] == "ms-calculator:"


def test_activity_callback_reports_steps():
    from agent import brain as brain_module

    seen = []
    brain_module.set_activity_callback(seen.append)
    try:
        brain_module._activity("Running open_application…")
    finally:
        brain_module.set_activity_callback(None)
    assert seen == ["Running open_application…"]


def test_cursor_event_reports_real_action_coordinates(monkeypatch):
    import agent.vision_agent as va
    from tools.event_bus import tool_bus

    emitted = []
    monkeypatch.setattr(tool_bus, "emit", emitted.append)
    va.ScreenController._cursor_event(120, 340, "click")
    assert emitted[0].type == "cursor"
    assert (emitted[0].x, emitted[0].y, emitted[0].kind) == (120, 340, "click")


def test_wrapped_destructive_shell_commands_need_confirmation():
    from tools.safety import SafetyGate

    gate = SafetyGate()
    assert gate.shell_requires_confirmation("cmd /c rd /s /q C:\\data")
    assert gate.shell_requires_confirmation('powershell -c "Remove-Item -Recurse -Force C:\\data"')
    assert gate.shell_requires_confirmation("python -c \"import shutil; shutil.rmtree('data')\"")
    assert not gate.shell_requires_confirmation("dir C:\\")


def test_destructive_terminal_command_waits_for_confirmation(monkeypatch):
    import tools.os_tools as os_tools
    from tools.event_bus import tool_bus
    from tools.safety import SafetyGate

    monkeypatch.setattr(tool_bus, "request_confirmation", lambda *_a: False)
    monkeypatch.setattr(os_tools.subprocess, "run", lambda *_a, **_k: pytest.fail("ran without approval"))

    result = os_tools.run_terminal_command("rd /s /q C:\\data", SafetyGate())
    assert "cancelled" in result.lower()


def test_any_named_app_uses_generic_launch_resolution(monkeypatch):
    import tools.os_tools as os_tools

    opened = []
    monkeypatch.setattr(os_tools, "_sys", lambda: "Windows")
    # os.startfile only exists on Windows; add it for this Linux CI run too.
    monkeypatch.setattr(
        os_tools.os, "startfile", lambda target: opened.append(target), raising=False
    )
    monkeypatch.setattr(os_tools, "_app_paths_target", lambda name: None)
    monkeypatch.setattr(os_tools, "_start_menu_targets", lambda name: [])
    monkeypatch.setattr(os_tools, "_start_apps_id", lambda name: None)
    monkeypatch.setattr(os_tools, "subprocess", type("S", (), {"run": lambda *_a, **_k: None})())
    monkeypatch.setattr(os_tools, "pyautogui", None)
    assert "steam" not in os_tools.WINDOWS_APP_ALIASES
    assert "epic games launcher" not in os_tools.WINDOWS_APP_ALIASES

    assert os_tools.open_application("Some Installed App") == "Opened Some Installed App."
    assert opened == ["Some Installed App"]


def test_windows_launch_finds_fuzzy_start_menu_shortcut(monkeypatch, tmp_path):
    import tools.os_tools as os_tools

    root = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    root.mkdir(parents=True)
    shortcut = root / "Epic Games Launcher.lnk"
    shortcut.write_text("shortcut", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setattr(os_tools, "_app_paths_target", lambda name: None)
    monkeypatch.setattr(os_tools, "_start_apps_id", lambda name: None)
    monkeypatch.setattr(os_tools, "subprocess", type("S", (), {"run": lambda *_a, **_k: None})())
    monkeypatch.setattr(os_tools, "pyautogui", None)

    opened = []

    def startfile(target):
        text = str(target)
        # A bare spoken name is not a valid shell target; the shortcut is.
        if "\\" not in text and "/" not in text:
            raise OSError("not found")
        opened.append(text)

    monkeypatch.setattr(os_tools.os, "startfile", startfile, raising=False)
    # The model may say "epic games" while the shortcut says "Epic Games Launcher".
    assert os_tools._windows_launch("epic games") is True
    assert str(shortcut) in opened


def test_windows_launch_uses_start_apps_id_for_store_apps(monkeypatch):
    import tools.os_tools as os_tools

    monkeypatch.setattr(os_tools, "_app_paths_target", lambda name: None)
    monkeypatch.setattr(os_tools, "_start_menu_targets", lambda name: [])
    monkeypatch.setattr(
        os_tools, "_start_apps_id", lambda name: "Contoso.PhotoEditor_1.2!App"
    )
    monkeypatch.setattr(os_tools, "subprocess", type("S", (), {"run": lambda *_a, **_k: None})())
    monkeypatch.setattr(os_tools, "pyautogui", None)
    opened = []

    def startfile(target):
        text = str(target)
        if "\\" not in text and "/" not in text:
            raise OSError("not found")
        opened.append(text)

    monkeypatch.setattr(os_tools.os, "startfile", startfile, raising=False)

    assert os_tools._windows_launch("Photo Editor") is True
    assert any("shell:AppsFolder" in target for target in opened)


def test_start_apps_id_parses_powershell_output(monkeypatch):
    import tools.os_tools as os_tools

    class Result:
        stdout = "Photo Editor|Contoso.PhotoEditor_1.2!App\nMusic|Contoso.Music!App\n"

    monkeypatch.setattr(os_tools, "subprocess", type("S", (), {"run": lambda *_a, **_k: Result()})())
    assert os_tools._start_apps_id("photo editor") == "Contoso.PhotoEditor_1.2!App"


def test_windows_launch_never_reports_false_success(monkeypatch):
    import tools.os_tools as os_tools

    monkeypatch.setattr(os_tools, "_sys", lambda: "Windows")

    def refuse(_target):
        raise OSError("not found")

    monkeypatch.setattr(os_tools.os, "startfile", refuse, raising=False)
    monkeypatch.setattr(os_tools, "_app_paths_target", lambda name: None)
    monkeypatch.setattr(os_tools, "_start_menu_targets", lambda name: [])
    monkeypatch.setattr(os_tools, "_start_apps_id", lambda name: None)
    monkeypatch.setattr(os_tools, "subprocess", type("S", (), {"run": lambda *_a, **_k: None})())
    monkeypatch.setattr(os_tools, "pyautogui", None)

    assert os_tools._windows_launch("Definitely Not Installed XYZ") is False
    assert "Could not find" in os_tools.open_application("Definitely Not Installed XYZ")


def test_app_match_score_rejects_uninstall_and_accepts_fuzzy_names():
    import tools.os_tools as os_tools

    assert os_tools._app_match_score("Epic Games Launcher", "Epic Games Launcher") >= 100
    assert os_tools._app_match_score("Notepad++", "Notepad++") > os_tools._app_match_score("Notepad++", "Notepad")
    assert os_tools._app_match_score("epic games", "Epic Games Launcher") > 0
    assert os_tools._app_match_score("chrome", "Google Chrome") > 0
    assert os_tools._app_match_score("chrome", "Uninstall Google Chrome") == 0


# ---- tool schemas ----

def test_all_tool_schemas_valid():
    names = []
    for tool in ALL_TOOLS:
        fn = tool["function"]
        assert {"name", "description", "parameters"} <= fn.keys()
        p = fn["parameters"]
        assert p["type"] == "object" and isinstance(p["properties"], dict)
        names.append(fn["name"])
    assert len(names) == len(set(names))
    for expected in ("run_terminal_command", "manage_files", "install_application",
                     "describe_screen", "stop_automation"):
        assert expected in names


# ---- ReAct loop with mocked Ollama ----

def test_react_direct_reply(monkeypatch):
    brain = Brain()
    brain._chat = lambda messages, **k: {"message": {"content": "Hello there."}}
    reply = brain.think_and_act("hi")
    assert reply == "Hello there."


def test_react_executes_tool_then_replies(monkeypatch):
    brain = Brain()
    calls = []

    def fake_chat(messages, **k):
        # First pass requests a tool; second pass produces the final answer.
        if k.get("tools"):
            return {"message": {"tool_calls": [{
                "function": {"name": "open_application",
                             "arguments": json.dumps({"app_name": "Notepad"})},
            }]}}
        return {"message": {"content": "Opened it."}}

    brain._chat = fake_chat
    monkeypatch.setattr("agent.brain.dispatch_tool",
                        lambda name, args, safety: calls.append((name, args)) or "launched")
    reply = brain.think_and_act("open notepad")
    assert calls == [("open_application", {"app_name": "Notepad"})]
    assert reply == "Opened it."


def test_react_confirmation_required_surfaces_without_execution(monkeypatch):
    brain = Brain()
    brain._chat = lambda messages, **k: {"message": {"tool_calls": [{
        "function": {"name": "run_terminal_command",
                     "arguments": json.dumps({"command": "rm -rf /"})},
    }]}} if k.get("tools") else {"message": {"content": "never"}}
    monkeypatch.setattr("agent.brain.dispatch_tool",
                        lambda *a: "Confirmation required for destructive command")
    reply = brain.think_and_act("delete everything")
    assert "confirmation required" in reply.lower()


def test_low_confidence_asks_for_confirmation():
    from agent.brain import clarify_low_confidence

    question = clarify_low_confidence("open blender", asr_confidence="low",
                                      controls=["Blender", "Notepad"])
    assert question is not None
    assert "Did you mean" in question
    assert "Blender" in question


def test_high_confidence_does_not_clarify():
    from agent.brain import clarify_low_confidence

    assert clarify_low_confidence("open blender", asr_confidence="high",
                                  controls=["Blender"]) is None


def test_close_control_names_get_disambiguated():
    from agent.brain import clarify_low_confidence

    question = clarify_low_confidence("save", asr_confidence="high",
                                      controls=["Save", "Save As", "Close"])
    assert question is not None
    assert "Save" in question and "Save As" in question


def test_undo_last_action_uses_shortcut(monkeypatch):
    import tools.os_tools as os_tools

    seen = []
    monkeypatch.setattr(os_tools, "_undo_last_file_move", lambda: False)
    # Patch the module's own reference: in CI pyautogui is an optional dep and
    # may be None, so patching the global module would not affect this code.
    monkeypatch.setattr(
        os_tools, "pyautogui",
        type("P", (), {"hotkey": staticmethod(lambda *keys: seen.append(keys))})(),
        raising=False,
    )

    result = os_tools.dispatch_tool("undo_last_action", {}, None)
    assert "undo" in result.lower()
    assert ("ctrl", "z") in seen or ("command", "z") in seen


def test_undo_reverses_last_file_move(tmp_path, monkeypatch):
    import tools.os_tools as os_tools
    import tools.undo_journal as journal

    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("x", encoding="utf-8")
    monkeypatch.setattr(journal, "JOURNAL_PATH", tmp_path / "journal.json")
    journal.record_move(str(src), str(dst))
    src.unlink()  # the move removed the original
    dst.write_text("x", encoding="utf-8")

    monkeypatch.setattr(os_tools.journal, "JOURNAL_PATH", tmp_path / "journal.json")
    result = os_tools.dispatch_tool("undo_last_action", {}, None)
    assert "reverted" in result.lower() or "moved back" in result.lower()
    assert src.exists() and not dst.exists()


def test_clean_for_voice_strips_markdown():
    text = "**Bold** `code`\n- item one\n- item two\n```python\nprint(1)\n```"
    cleaned = Brain._clean_for_voice(text)
    assert "**" not in cleaned and "```" not in cleaned and "`" not in cleaned
    assert "item one" in cleaned and "item two" in cleaned


# ---- describe_screen blind-accessibility output ----

def test_describe_screen_speaks_and_returns_text(monkeypatch):
    import agent.vision_agent as va

    spoken = []
    monkeypatch.setattr(va, "ScreenController", lambda: SimpleNamespace())
    monkeypatch.setattr(va.VisionAgent, "describe", lambda self, focus="overview":
                        "WINDOW: Blender\nFOCUS: Cube\nNEXT: press X")
    monkeypatch.setattr("audio.speaker_provider.get_speaker",
                        lambda: SimpleNamespace(speak=spoken.append))
    result = va.describe_screen("focus")
    assert "WINDOW:" in result and "NEXT:" in result
    assert spoken and spoken[0] == result


def test_describe_screen_without_speaker_still_returns(monkeypatch):
    import agent.vision_agent as va
    monkeypatch.setattr(va, "ScreenController", lambda: SimpleNamespace())
    monkeypatch.setattr(va.VisionAgent, "describe", lambda self, focus="overview": "description")
    monkeypatch.setattr("audio.speaker_provider.get_speaker", lambda: None)
    assert va.describe_screen() == "description"


# ---- installer selection across package managers ----

@pytest.mark.parametrize("system,manager,existing,expected_id,expected_flags", [
    ("Windows", "winget", ["winget"], "Vendor.App", ["--silent", "--accept-package-agreements"]),
    ("Darwin", "brew-cask", ["brew"], "blender", ["--cask"]),
    ("Linux", "flatpak", ["flatpak"], "org.blender.Blender", ["-y"]),
    ("Linux", "apt", ["apt-get"], "blender", ["-y"]),
    ("Linux", "dnf", ["dnf"], "blender", ["-y"]),
    ("Linux", "pacman", ["pacman"], "blender", ["--noconfirm"]),
])
def test_installer_selects_package_manager(monkeypatch, system, manager, existing,
                                           expected_id, expected_flags):
    import tools.installer_tool as it
    monkeypatch.setattr(it.platform, "system", lambda: system)
    monkeypatch.setattr(it.shutil, "which", lambda n: f"/usr/bin/{n}" if n in existing else None)

    def fake_capture(cmd, timeout=30):
        if system == "Windows":
            return "Name    Id         Version\nBlender Vendor.App 1.0"
        if system == "Darwin":
            return "blender\nblender-extra"
        return f"blender 1.0\n{expected_id} app"

    monkeypatch.setattr(it, "_run_capture", fake_capture)
    plan = detect_install_plan("blender")
    assert plan is not None and plan.manager == manager, (plan, manager)
    for flag in expected_flags:
        assert flag in plan.install_command, plan.install_command


def test_installer_no_manager_falls_back(monkeypatch):
    import tools.installer_tool as it
    monkeypatch.setattr(it.platform, "system", lambda: "Linux")
    monkeypatch.setattr(it.shutil, "which", lambda n: None)
    assert detect_install_plan("anything") is None


# ---- confirmation gating ----

def test_destructive_shell_pauses_for_confirmation(monkeypatch):
    gate = SafetyGate(confirm_callback=None)
    result = gate.run_shell("rm -rf /")
    assert "confirmation required" in result.lower()
    assert gate.audit == []  # nothing executed


def test_file_deletion_denied_does_not_execute(monkeypatch):
    import tools.safety as safety
    called = {"n": 0}
    monkeypatch.setattr(safety.shutil, "rmtree", lambda *a: called.__setitem__("n", 1))
    monkeypatch.setattr(safety.Path, "unlink", lambda *a, **k: called.__setitem__("n", 1))
    gate = SafetyGate(confirm_callback=lambda d, c: False)
    result = gate.run_file_operation("delete", "/tmp/whatever")
    assert "cancelled" in result.lower() and called["n"] == 0
    assert gate.audit[-1]["decision"] == "denied"


def test_safe_file_read_needs_no_confirmation(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("hello", encoding="utf-8")
    gate = SafetyGate(confirm_callback=None)
    assert gate.run_file_operation("read", str(p)) == "hello"


def test_installation_emits_confirmation_then_waits(monkeypatch):
    import tools.installer_tool as it
    from tools.event_bus import ToolEventBus

    events = []
    bus = ToolEventBus()
    bus.emit = lambda m: events.append(json.loads(m.to_json()))
    seen = {}
    def fake_request(description, command, timeout=180):
        seen["description"] = description
        seen["command"] = command
        return False
    bus.request_confirmation = fake_request
    it.tool_bus = bus
    it.detect_install_plan = lambda name: it.PackagePlan(
        manager="winget", package_id="Vendor.App", search_command=[],
        install_command=["winget", "install", "--id", "Vendor.App", "--silent"],
        description="test",
    )
    result = it.install_application("FakeApp")
    assert "cancel" in result.lower()
    assert "FakeApp" in seen["description"]
    assert "--silent" in seen["command"]
    # request_confirmation is faked here, so no confirmation_required frame is
    # emitted by the bus itself. The real emission path is covered in test_tools.py.
