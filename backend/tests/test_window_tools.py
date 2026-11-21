"""Multi-monitor geometry and cross-platform window action tests.

No real windows are touched: platform helpers are monkeypatched and mss/pyautogui
are faked so the suite is identical on every OS.
"""

from __future__ import annotations

import sys

import pytest

import agent.vision_agent as va
import tools.window_tools as wt
from agent.brain import ALL_TOOLS
from tools.os_tools import dispatch_tool
from tools.window_tools import (
    WINDOW_TOOLS,
    WindowInfo,
    find_window,
    focus_or_manage_window,
    get_monitors,
    list_open_windows,
    monitor_for_rect,
    primary_monitor,
)

# Primary at 0,0 and a secondary to the LEFT (negative x), as commonly configured.
MONITORS = [
    {"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080},
    {"index": 2, "left": -1920, "top": 0, "width": 1920, "height": 1080},
]


def win(title, left, top, width=1920, height=1080, focused=False, app=None):
    return WindowInfo(
        title=title,
        app=app or title.split(" - ")[0],
        monitor_index=monitor_for_rect(left, top, width, height, MONITORS),
        left=left, top=top, width=width, height=height,
        focused=focused,
    )


@pytest.fixture(autouse=True)
def _reset_monitor_choice():
    va.reset_active_monitor()
    yield
    va.reset_active_monitor()


# ---- monitor geometry ----

def test_get_monitors_uses_ones_based_indices(monkeypatch):
    class FakeSct:
        monitors = [
            {"left": -1920, "top": 0, "width": 3840, "height": 1080},  # virtual
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": -1920, "top": 0, "width": 1920, "height": 1080},
        ]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake_module = type("M", (), {"mss": staticmethod(lambda: FakeSct())})()
    monkeypatch.setitem(sys.modules, "mss", fake_module)

    monitors = get_monitors()
    assert [m["index"] for m in monitors] == [1, 2]
    assert monitors[1]["left"] == -1920


def test_monitor_for_rect_negative_offset():
    assert monitor_for_rect(0, 0, 1920, 1080, MONITORS) == 1
    assert monitor_for_rect(-1920, 0, 1920, 1080, MONITORS) == 2
    assert monitor_for_rect(-300, 100, 200, 200, MONITORS) == 2


def test_monitor_for_rect_uses_overlap_fallback():
    # Window straddling both displays; center exactly on the boundary -> first
    # matching monitor wins, no crash or index 0.
    index = monitor_for_rect(-960, 0, 1920, 1080, MONITORS)
    assert index in (1, 2)


def test_primary_monitor():
    assert primary_monitor(MONITORS) == MONITORS[0]


def test_screen_controller_global_coordinate_translation():
    """Normalized 0-1000 coords map to GLOBAL pixels including negative x."""
    sc = object.__new__(va.ScreenController)
    sc._width, sc._height = 1920, 1080
    sc._left, sc._top = -1920, 0
    sc.monitor_index = 2

    assert sc.norm_to_global(0, 0) == (-1920, 0)
    assert sc.norm_to_global(500, 500) == (-960, 540)
    assert sc.norm_to_global(1000, 1000) == (0, 1080)


def test_screen_controller_click_uses_global_coordinates(monkeypatch):
    clicks = []
    monkeypatch.setattr(va, "pyautogui", type("P", (), {
        "click": staticmethod(lambda x, y: clicks.append((x, y))),
        "doubleClick": staticmethod(lambda x, y: clicks.append((x, y))),
        "rightClick": staticmethod(lambda x, y: clicks.append((x, y))),
        "moveTo": staticmethod(lambda x, y: None),
        "dragTo": staticmethod(lambda x, y: None),
    })())

    sc = object.__new__(va.ScreenController)
    sc._width, sc._height, sc._left, sc._top = 1920, 1080, -1920, 0
    sc.click(500, 500)
    sc.right_click(0, 0)
    assert clicks == [(-960, 540), (-1920, 0)]


def test_screen_controller_discovers_monitors(monkeypatch):
    class FakeSct:
        monitors = [
            {"left": -1920, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": -1920, "top": 0, "width": 1920, "height": 1080},
        ]
        def grab(self, mon): return mon

    sc = object.__new__(va.ScreenController)
    sc._sct = FakeSct()
    monitors = sc._discover_monitors()
    assert [m["index"] for m in monitors] == [1, 2]
    assert monitors[1]["left"] == -1920

    sc.monitors = monitors
    sc.follow_focused = False
    sc.select_monitor(2)
    assert sc._left == -1920 and sc.monitor_index == 2


# ---- monitor selection phrases ----

@pytest.mark.parametrize("phrase,expected", [
    ("look at my second monitor", 2),
    ("switch to monitor 2", 2),
    ("show me the primary display", 1),
    ("look at the third screen", 3),
    ("what time is it", None),
])
def test_parse_monitor_phrase(phrase, expected):
    assert va.parse_monitor_phrase(phrase) == expected


def test_set_active_monitor_updates_global(monkeypatch):
    monkeypatch.setattr(wt, "get_monitors", lambda: MONITORS)
    # vision_agent imports get_monitors lazily from window_tools, so patch there.
    assert "Watching monitor 2" in va.set_active_monitor(2)
    assert va.get_active_monitor() == 2
    assert "does not exist" in va.set_active_monitor(9)
    va.reset_active_monitor()
    assert va.get_active_monitor() is None


# ---- listing / speaking ----

def test_list_windows_summary_and_speech(monkeypatch):
    windows = [
        win("Blender", 0, 0, focused=True, app="Blender"),
        win("Chrome", -1920, 0, app="Chrome"),
        win("DaVinci Resolve", 0, 100, app="DaVinci Resolve"),
    ]
    monkeypatch.setattr(wt, "list_windows", lambda: windows)
    spoken = []
    import audio.speaker_provider as sp
    monkeypatch.setattr(sp, "get_speaker", lambda: type("S", (), {"speak": spoken.append})())

    summary = list_open_windows()
    assert "3 windows open" in summary
    assert "Blender on monitor 1" in summary
    assert "Chrome on monitor 2" in summary
    assert spoken and spoken[0] == summary


def test_list_windows_empty(monkeypatch):
    monkeypatch.setattr(wt, "list_windows", lambda: [])
    assert "open windows" in list_open_windows(speak=False).lower()


def test_find_window_exact_then_partial():
    windows = [win("Blender 4.2 - scene.blend", 0, 0, app="Blender")]
    assert find_window("blender", windows).title.startswith("Blender")
    assert find_window("scene.blend", windows) is not None
    assert find_window("missing", windows) is None


# ---- window state actions ----

@pytest.mark.parametrize("action", list(wt.VALID_ACTIONS))
def test_focus_or_manage_window_dispatches_each_action(monkeypatch, action):
    windows = [win("Blender", 0, 0, app="Blender")]
    monkeypatch.setattr(wt, "list_windows", lambda: windows)
    monkeypatch.setattr(wt.platform, "system", lambda: "Windows")
    called = {}
    monkeypatch.setattr(wt, "_act_windows", lambda w, a: called.update(w=w.title, action=a) or True)

    result = focus_or_manage_window("Blender", action, speak=False)
    assert "Done" in result and called == {"w": "Blender", "action": action}


def test_invalid_window_action():
    result = focus_or_manage_window("Blender", "explode", speak=False)
    assert "Unknown window action" in result


def test_window_not_found():
    result = focus_or_manage_window("Nothing", "focus", speak=False)
    assert "couldn't find" in result.lower()


def test_actions_are_platform_specific(monkeypatch):
    windows = [win("Blender", 0, 0, app="Blender")]
    monkeypatch.setattr(wt, "list_windows", lambda: windows)
    seen = []
    monkeypatch.setattr(wt.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(wt, "_act_macos", lambda w, a: seen.append("mac") or True)
    focus_or_manage_window("Blender", "focus", speak=False)
    monkeypatch.setattr(wt.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wt, "_act_linux", lambda w, a: seen.append("linux") or True)
    focus_or_manage_window("Blender", "maximize", speak=False)
    assert seen == ["mac", "linux"]


def test_action_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(wt, "list_windows", lambda: [win("Blender", 0, 0)])
    monkeypatch.setattr(wt.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wt, "_act_linux", lambda w, a: False)
    result = focus_or_manage_window("Blender", "focus", speak=False)
    assert "couldn't" in result.lower() and "wmctrl" in result


# ---- registration / routing ----

def test_window_tools_registered_in_brain():
    names = [t["function"]["name"] for t in WINDOW_TOOLS]
    assert set(names) == {"list_open_windows", "focus_or_manage_window", "set_active_monitor"}
    brain_names = [t["function"]["name"] for t in ALL_TOOLS]
    for name in names:
        assert name in brain_names


def test_dispatch_window_tools(monkeypatch):
    monkeypatch.setattr(wt, "list_open_windows", lambda: "windows")
    monkeypatch.setattr(wt, "focus_or_manage_window", lambda a, action: f"managed {a}")
    monkeypatch.setattr(va, "set_active_monitor", lambda m: f"monitor {m}")

    assert dispatch_tool("list_open_windows", {}, None) == "windows"
    assert dispatch_tool("focus_or_manage_window", {"app_or_title": "Blender", "action": "focus"}, None) == "managed Blender"
    assert dispatch_tool("set_active_monitor", {"monitor": 2}, None) == "monitor 2"
