"""Local app knowledge base for the Murmur AI visual agent.

Detects the currently active foreground window (via pygetwindow / OS tools)
and injects that app's keyboard-shortcut cheat-sheet into the VLM system prompt,
so the agent prefers fast hotkeys (Shift+A, Ctrl+B, S, G, R, ...) over slow
mouse hunting in heavy apps like Blender and DaVinci Resolve.

Everything is local. No network calls. Shortcuts are stored in `shortcuts.json`
next to this file and can be edited by the user.
"""

from __future__ import annotations

import json
import logging
import platform
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("murmur_ai.agent.app_knowledge")

SHORTCUTS_PATH = Path(__file__).with_name("shortcuts.json")

# Default knowledge. Also written to shortcuts.json on first load so the user
# can extend it without touching code.
DEFAULT_SHORTCUTS: dict[str, dict] = {
    "blender": {
        "match": ["blender"],
        "label": "Blender",
        "workflows": {
            "Start a new project": "Ctrl+N then choose New General File; the scene resets to the default cube.",
            "Name the project": "Ctrl+Shift+S (Save As), type the name in the file name field, then Enter.",
            "Add object": "Shift+A -> Mesh -> UV Sphere for a sphere.",
            "Add a sphere": "Shift+A -> Mesh -> UV Sphere, or Shift+F4 for the Python console: bpy.ops.mesh.primitive_uv_sphere_add().",
            "Move object": "G then X/Y/Z to constrain axis.",
            "Rotate object": "R then X/Y/Z.",
            "Scale object": "S then X/Y/Z.",
            "Delete selection": "X then confirm.",
            "Delete the default cube": "Select the cube in the Outliner, press X and confirm; or in the Python console (Shift+F4): bpy.data.objects.remove(bpy.data.objects['Cube'], do_unlink=True).",
            "Enter Edit Mode": "Tab.",
            "Select all / deselect": "A / Alt+A.",
            "Frame selection": "Numpad . (period).",
            "Toggle wireframe": "Z.",
            "Open shader editor": "Switch an area to Shading workspace.",
            "Render image": "F12.",
            "Save file": "Ctrl+S.",
            "Undo": "Ctrl+Z.",
        },
        "hint": "Prefer keyboard shortcuts; Blender's viewport is keyboard-driven.",
    },
    "davinci resolve": {
        "match": ["davinci", "resolve"],
        "label": "DaVinci Resolve",
        "workflows": {
            "Import media": "Ctrl+I, then drag clips to the timeline.",
            "Play / pause": "Spacebar.",
            "Ripple delete": "Ctrl+Backspace or Delete/X.",
            "Add edit at playhead": "Ctrl+B.",
            "Split clips": "S at playhead.",
            "Undo": "Ctrl+Z.",
            "Zoom timeline": "- / +.",
            "Open Color page": "Ctrl+PageDown or click Color tab.",
            "Open Fairlight": "Ctrl+PageDown (audio).",
            "Render": "Ctrl+R, add to queue.",
            "Save project": "Ctrl+S.",
        },
        "hint": "Use Spacebar to play, S to split, Ctrl+B to add edits; avoid dragging when a hotkey exists.",
    },
    "vs code": {
        "match": ["visual studio code", "vscode", "code"],
        "label": "VS Code",
        "workflows": {
            "Quick Open file": "Ctrl+P then type filename.",
            "Command Palette": "Ctrl+Shift+P.",
            "Go to line": "Ctrl+G.",
            "Save": "Ctrl+S.",
            "Find": "Ctrl+F; Replace Ctrl+H.",
            "Toggle terminal": "Ctrl+` (backtick).",
            "Comment line": "Ctrl+/.",
            "Format document": "Shift+Alt+F.",
            "Multi-cursor": "Alt+Click or Ctrl+Alt+Down.",
            "Split editor": "Ctrl+\\.",
        },
        "hint": "Use the Command Palette (Ctrl+Shift+P) for almost any command.",
    },
    "file explorer": {
        "match": ["explorer", "file manager", "finder", "nautilus", "dolphin"],
        "label": "File Manager",
        "workflows": {
            "Open location": "Ctrl+L (Windows/Linux) or Cmd+Shift+G (macOS), then type path.",
            "New folder": "Ctrl+Shift+N.",
            "Rename": "F2.",
            "Delete": "Delete (to Recycle Bin); Shift+Delete permanently (needs confirmation).",
            "Select all": "Ctrl+A.",
            "Go up": "Alt+Up.",
            "Search": "Ctrl+F.",
        },
        "hint": "Use the location bar (Ctrl+L) to jump directly to paths instead of clicking through folders.",
    },
    "browser": {
        "match": ["chrome", "firefox", "edge", "safari", "browser"],
        "label": "Web Browser",
        "workflows": {
            "Focus address bar": "Ctrl+L / Cmd+L.",
            "New tab": "Ctrl+T.",
            "Close tab": "Ctrl+W.",
            "Find in page": "Ctrl+F.",
            "Reload": "Ctrl+R / F5.",
            "Back / forward": "Alt+Left / Alt+Right.",
            "Developer tools": "Ctrl+Shift+I.",
        },
        "hint": "Use Ctrl+L to navigate directly to URLs.",
    },
}


def _load_shortcuts() -> dict[str, dict]:
    """Load shortcuts.json (creating it from defaults on first run)."""
    if SHORTCUTS_PATH.exists():
        try:
            data = json.loads(SHORTCUTS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except json.JSONDecodeError:
            logger.warning("shortcuts.json is invalid; using defaults")
    try:
        SHORTCUTS_PATH.write_text(
            json.dumps(DEFAULT_SHORTCUTS, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return DEFAULT_SHORTCUTS


def get_foreground_title() -> str:
    """Return the active foreground window title, or '' if unavailable."""
    system = platform.system()
    try:
        if system == "Windows":
            try:
                import win32gui  # type: ignore

                hwnd = win32gui.GetForegroundWindow()
                return win32gui.GetWindowText(hwnd)
            except ImportError:
                pass
            try:
                import pygetwindow as gw  # type: ignore

                win = gw.getActiveWindow()
                return win.title if win else ""
            except Exception:
                return ""
        if system == "Darwin":
            try:
                from AppKit import NSWorkspace  # type: ignore

                return NSWorkspace.sharedWorkspace().activeApplication()["NSApplicationName"]
            except Exception:
                return ""
        # Linux
        try:
            import subprocess

            out = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return out.stdout.strip()
        except Exception:
            return ""
    except Exception:  # pragma: no cover - defensive
        logger.exception("Foreground window detection failed")
        return ""


def match_app(title: str, shortcuts: dict[str, dict] | None = None) -> dict | None:
    """Match a window title to a known app profile."""
    if not title:
        return None
    kb = shortcuts or _load_shortcuts()
    lowered = title.lower()
    best: dict | None = None
    best_score = 0
    for profile in kb.values():
        score = 0
        for token in profile.get("match", []):
            if token.lower() in lowered:
                score += len(token)
        if score > best_score:
            best = profile
            best_score = score
    return best


def build_prompt_section(title: str) -> str:
    """Build the system-prompt section for the currently active app."""
    profile = match_app(title)
    if profile is None:
        return ""

    lines = [f"\n=== ACTIVE APP: {profile.get('label', title)} ==="]
    if profile.get("hint"):
        lines.append(f"Hint: {profile['hint']}")
    lines.append("Prefer these shortcuts over mouse clicks when relevant:")
    for workflow, keys in profile.get("workflows", {}).items():
        lines.append(f"- {workflow}: {keys}")
    lines.append("=== END APP CHEAT SHEET ===\n")
    return "\n".join(lines)


# Dense creative interfaces benefit from dynamic-resolution captures: small
# icons, timeline cells and node wires are otherwise lost to downscaling.
DENSE_CREATIVE_MATCHES = (
    "blender", "davinci", "resolve", "after effects", "premiere",
    "final cut", "photoshop", "illustrator", "nuke", "houdini", "unity",
    "unreal", "timeline", "node editor", "shader editor",
)


def is_dense_creative_app(title: str) -> bool:
    """True when the foreground window is a dense creative/timeline UI."""
    lowered = (title or "").lower()
    if not lowered:
        return False
    profile = match_app(lowered)
    label = (profile or {}).get("label", "").lower()
    return any(token in lowered for token in DENSE_CREATIVE_MATCHES) or any(
        token in label for token in ("blender", "davinci resolve")
    )


@dataclass
class AppContext:
    title: str
    profile_label: str = ""
    prompt_section: str = ""


def detect_app_context() -> AppContext:
    """Detect the active app and build the injectable prompt section."""
    title = get_foreground_title()
    profile = match_app(title)
    return AppContext(
        title=title,
        profile_label=(profile or {}).get("label", ""),
        prompt_section=build_prompt_section(title),
    )
