"""Cross-platform window listing and management for Murmur AI.

Works on Windows (pygetwindow / Win32), macOS (osascript, optional Quartz) and
Linux (wmctrl / xdotool, with a graceful message on Wayland). All external
commands are lazy and bounded, so the tools degrade to an actionable message
instead of crashing when a helper is missing.

Monitor geometry comes from mss when available. Monitor indices are 1-based to
match how people speak ("my second monitor"). Negative left/top offsets are
preserved, which matters when a display is placed left of the primary.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("murmur_ai.tools.window_tools")

VALID_ACTIONS = ("focus", "maximize", "minimize", "close", "move_to_primary_monitor")
MAX_SPOKEN_WINDOWS = 12


@dataclass
class WindowInfo:
    title: str
    app: str
    monitor_index: int
    left: int
    top: int
    width: int
    height: int
    focused: bool
    minimized: bool = False
    maximized: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "app": self.app,
            "monitor_index": self.monitor_index,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "focused": self.focused,
            "minimized": self.minimized,
            "maximized": self.maximized,
        }


# ---------------------------------------------------------------------------
# Monitor geometry
# ---------------------------------------------------------------------------

def get_monitors() -> list[dict[str, int]]:
    """Return 1-based monitors ``{index,left,top,width,height}`` via mss."""
    try:  # pragma: no cover - optional dependency
        import mss

        with mss.mss() as sct:
            raw = sct.monitors
    except Exception:
        raw = None

    if not raw or len(raw) <= 1:
        # Conservative single-display fallback.
        return [{"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080}]

    # mss.monitors[0] is the virtual rectangle spanning all displays.
    result = []
    for index, mon in enumerate(raw[1:], start=1):
        result.append({
            "index": index,
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        })
    return result


def monitor_for_rect(
    left: int, top: int, width: int, height: int,
    monitors: Optional[list[dict[str, int]]] = None,
) -> int:
    """Return the 1-based index of the monitor containing a window rect.

    Uses the rect center; ties fall back to the display with the largest
    overlap. Works with negative coordinates (monitor left of primary).
    """
    monitors = monitors or get_monitors()
    cx, cy = left + width // 2, top + height // 2
    for mon in monitors:
        if (mon["left"] <= cx < mon["left"] + mon["width"]
                and mon["top"] <= cy < mon["top"] + mon["height"]):
            return mon["index"]

    best_index, best_area = monitors[0]["index"], -1
    for mon in monitors:
        ix = max(0, min(left + width, mon["left"] + mon["width"]) - max(left, mon["left"]))
        iy = max(0, min(top + height, mon["top"] + mon["height"]) - max(top, mon["top"]))
        area = ix * iy
        if area > best_area:
            best_index, best_area = mon["index"], area
    return best_index


def primary_monitor(monitors: Optional[list[dict[str, int]]] = None) -> dict[str, int]:
    """Return the primary monitor (mss lists it first after the virtual rect)."""
    monitors = monitors or get_monitors()
    for mon in monitors:
        if mon["index"] == 1:
            return mon
    return monitors[0]


# ---------------------------------------------------------------------------
# Platform-specific enumeration (all results normalized to WindowInfo)
# ---------------------------------------------------------------------------

def _run(command: list[str], timeout: float = 6.0) -> str:
    """Run a helper command and return stdout, or '' on any failure."""
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.stdout.strip()
    except Exception:  # pragma: no cover - environment dependent
        return ""


def _app_from_title(title: str) -> str:
    """Best-effort app name from a window title."""
    for separator in (" - ", " \u2014 ", " \u2013 "):
        if separator in title:
            return title.rsplit(separator, 1)[-1].strip() or title
    return title.strip()


def _windows_platform() -> list[WindowInfo]:
    try:  # pragma: no cover - platform specific
        import pygetwindow as gw
    except Exception:
        return []

    monitors = get_monitors()
    try:
        active = gw.getActiveWindow()
    except Exception:
        active = None
    active_title = getattr(active, "title", "") if active else ""

    result = []
    for w in gw.getWindowsWithTitle(""):
        title = (getattr(w, "title", "") or "").strip()
        if not title:
            continue
        left, top = int(w.left), int(w.top)
        width, height = int(w.width), int(w.height)
        result.append(WindowInfo(
            title=title,
            app=_app_from_title(title),
            monitor_index=monitor_for_rect(left, top, width, height, monitors),
            left=left, top=top, width=width, height=height,
            focused=(title == active_title),
            minimized=bool(getattr(w, "isMinimized", False)),
            maximized=bool(getattr(w, "isMaximized", False)),
        ))
    return result


def _macos_platform() -> list[WindowInfo]:
    names = _run([
        "osascript", "-e",
        'tell application "System Events" to get name of every process whose visible is true',
    ])
    frontmost = _run([
        "osascript", "-e",
        'tell application "System Events" to get name of first process whose frontmost is true',
    ])
    titles = [n.strip() for n in names.split(",") if n.strip()]
    monitors = get_monitors()
    result = []
    for index, title in enumerate(titles):
        bounds = _run([
            "osascript", "-e",
            f'tell application "System Events" to tell process "{title}" to get '
            '{position, size} of window 1',
        ])
        # AppleScript returns e.g. "0, 25, 1440, 900"
        numbers = [int(float(n.strip())) for n in bounds.split(",") if n.strip().lstrip("-").isdigit()]
        left, top, width, height = (numbers + [0, 25, 1280, 800])[:4]
        result.append(WindowInfo(
            title=title,
            app=title,
            monitor_index=monitor_for_rect(left, top, width, height, monitors),
            left=left, top=top, width=width, height=height,
            focused=(title == frontmost.strip()),
        ))
    return result


def _linux_platform() -> list[WindowInfo]:
    output = _run(["wmctrl", "-lG"])
    if not output and not shutil.which("wmctrl"):
        return []
    active = _run(["xdotool", "getactivewindow", "getwindowname"])
    monitors = get_monitors()
    result = []
    for line in output.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        try:
            left, top, width, height = (int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]))
        except ValueError:
            continue
        title = parts[7].strip()
        if not title:
            continue
        result.append(WindowInfo(
            title=title,
            app=_app_from_title(title),
            monitor_index=monitor_for_rect(left, top, width, height, monitors),
            left=left, top=top, width=width, height=height,
            focused=(title == active.strip()),
        ))
    return result


def list_windows() -> list[WindowInfo]:
    """Enumerate visible windows on the current platform."""
    system = platform.system()
    if system == "Windows":
        return _windows_platform()
    if system == "Darwin":
        return _macos_platform()
    return _linux_platform()


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def _speak(text: str, speak: bool) -> None:
    if not speak:
        return
    try:  # pragma: no cover - TTS is optional
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            speaker.speak(text)
    except Exception:
        logger.debug("Window summary speech failed", exc_info=True)


def _spoken_summary(windows: list[WindowInfo]) -> str:
    if not windows:
        return "I don't see any open windows."
    focused = next((w for w in windows if w.focused), None)
    parts = [f"You have {len(windows)} window{'s' if len(windows) != 1 else ''} open."]
    if focused:
        parts.append(
            f"The focused window is {focused.title} on monitor {focused.monitor_index}."
        )
    others = [w for w in windows if not w.focused][:MAX_SPOKEN_WINDOWS - 1]
    if others:
        parts.append(
            "Also open: "
            + "; ".join(f"{w.title} on monitor {w.monitor_index}" for w in others)
            + "."
        )
    return " ".join(parts)


def list_open_windows(speak: bool = True) -> str:
    """List open windows with titles, monitors and focus; optionally speak it."""
    windows = list_windows()
    summary = _spoken_summary(windows)
    _speak(summary, speak)
    return summary


def find_window(query: str, windows: Optional[list[WindowInfo]] = None) -> Optional[WindowInfo]:
    """Match a window by exact title, substring, or app name (case-insensitive)."""
    windows = windows if windows is not None else list_windows()
    needle = (query or "").strip().lower()
    if not needle:
        return None
    for w in windows:
        if w.title.lower() == needle or w.app.lower() == needle:
            return w
    for w in windows:
        if needle in w.title.lower() or needle in w.app.lower():
            return w
    return None


def _act_windows(window: WindowInfo, action: str) -> bool:  # pragma: no cover - platform specific
    import pygetwindow as gw

    match = [w for w in gw.getWindowsWithTitle("") if w.title == window.title]
    if not match:
        return False
    w = match[0]
    if action == "focus":
        w.activate()
    elif action == "maximize":
        w.maximize()
    elif action == "minimize":
        w.minimize()
    elif action == "close":
        w.close()
    elif action == "move_to_primary_monitor":
        mon = primary_monitor()
        w.left, w.top = int(mon["left"]), int(mon["top"])
    else:
        return False
    return True


def _act_macos(window: WindowInfo, action: str) -> bool:  # pragma: no cover - platform specific
    scripts = {
        "focus": f'tell application "{window.app}" to activate',
        "maximize": (
            f'tell application "System Events" to tell process "{window.app}" to '
            'set value of attribute "AXFullScreen" of window 1 to true'
        ),
        "minimize": (
            f'tell application "System Events" to tell process "{window.app}" to '
            'set value of attribute "AXMinimized" of window 1 to true'
        ),
        "close": f'tell application "{window.app}" to close window 1',
    }
    if action == "move_to_primary_monitor":
        mon = primary_monitor()
        script = (
            f'tell application "System Events" to tell process "{window.app}" to '
            f'set position of window 1 to {{{mon["left"]}, {mon["top"]}}}'
        )
    else:
        script = scripts.get(action)
    if not script:
        return False
    return _run(["osascript", "-e", script]) is not None


def _act_linux(window: WindowInfo, action: str) -> bool:  # pragma: no cover - platform specific
    if not shutil.which("wmctrl") and not shutil.which("xdotool"):
        return False
    title = window.title
    if action == "focus":
        _run(["wmctrl", "-a", title])
    elif action == "maximize":
        _run(["wmctrl", "-r", title, "-b", "add,maximized_vert,maximized_horz"])
    elif action == "minimize":
        _run(["xdotool", "search", "--name", title, "windowminimize"])
    elif action == "close":
        _run(["wmctrl", "-c", title])
    elif action == "move_to_primary_monitor":
        mon = primary_monitor()
        _run(["wmctrl", "-r", title, "-b", "remove,maximized_vert,maximized_horz"])
        _run(["wmctrl", "-r", title, "-e", f"0,{mon['left']},{mon['top']},-1,-1"])
    else:
        return False
    return True


def focus_or_manage_window(
    app_or_title: str, action: str, speak: bool = True
) -> str:
    """Focus, maximize, minimize, close, or move a window to the primary display."""
    action = (action or "").strip().lower()
    if action not in VALID_ACTIONS:
        return (
            f"Unknown window action {action or '(none)'}. "
            f"Supported actions: {', '.join(VALID_ACTIONS)}."
        )
    window = find_window(app_or_title)
    if window is None:
        message = f"I couldn't find a window called {app_or_title}."
        _speak(message, speak)
        return message

    system = platform.system()
    try:
        if system == "Windows":
            ok = _act_windows(window, action)
        elif system == "Darwin":
            ok = _act_macos(window, action)
        else:
            ok = _act_linux(window, action)
    except Exception:
        logger.exception("Window action %s failed", action)
        ok = False

    if ok:
        message = f"Done. {action.replace('_', ' ')} {window.title}."
    else:
        message = (
            f"I couldn't {action.replace('_', ' ')} {window.title}. "
            "That may need a helper tool like wmctrl, xdotool, or accessibility permission."
        )
    _speak(message, speak)
    return message


WINDOW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_open_windows",
            "description": (
                "List all open application windows with their titles, which "
                "monitor each is on, and which one has focus. The summary is "
                "spoken aloud for blind/low-vision users."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_or_manage_window",
            "description": (
                "Manage an application window by name or title across Windows, "
                "macOS and Linux. Actions: focus, maximize, minimize, close, "
                "move_to_primary_monitor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_or_title": {
                        "type": "string",
                        "description": "Application name or window title substring.",
                    },
                    "action": {
                        "type": "string",
                        "enum": list(VALID_ACTIONS),
                        "description": "What to do with the window.",
                    },
                },
                "required": ["app_or_title", "action"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_active_monitor",
            "description": (
                "Switch the screen/vision capture target to a specific monitor. "
                "Use when the user says 'look at my second monitor' or asks to "
                "switch displays. Monitor numbers are 1-based."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": "1-based monitor index to capture.",
                    }
                },
                "required": ["monitor"],
                "additionalProperties": False,
            },
        },
    },
]
