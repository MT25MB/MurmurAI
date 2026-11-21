"""Cross-platform OS automation tools for Murmur AI.

All functions return short, plain-text strings suitable for voice output.
Destructive shell commands route through the safety gate.
"""

from __future__ import annotations

import logging
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

try:  # pragma: no cover - platform optional
    import pyautogui
except Exception:  # pragma: no cover - optional dep may be installed but unusable (headless/no PortAudio)
    pyautogui = None

try:  # pragma: no cover - platform optional
    import mss
except Exception:  # pragma: no cover - optional dep may be installed but unusable (headless/no PortAudio)
    mss = None

import base64

from .safety import SafetyGate

logger = logging.getLogger("murmur_ai.tools.os_tools")

# ---- JSON-schema tool definitions (for the LLM to call) ----

OS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Launch an application by name on the local machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the app to open, e.g. 'Notepad', 'Finder', 'Terminal'.",
                    }
                },
                "required": ["app_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_and_keyboard",
            "description": "Control mouse and keyboard: click, type, scroll, hotkeys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["click", "type", "scroll", "hotkey"],
                        "description": "What to do.",
                    },
                    "x": {
                        "type": "integer",
                        "description": "Screen X coordinate for clicks (px).",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Screen Y coordinate for clicks (px).",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type, or key names for hotkey (comma-separated).",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_screen",
            "description": "Take a compressed screenshot and return it as base64.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_terminal_command",
            "description": "Run a shell command. Destructive commands require confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run.",
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_files",
            "description": "Read, write, search, or remove local files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["read", "write", "delete", "search", "organize"],
                        "description": "File operation to perform.",
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory path.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content for write/search operations.",
                    },
                },
                "required": ["operation", "path"],
                "additionalProperties": False,
            },
        },
    },
]


def dispatch_tool(name: str, arguments: dict, safety: SafetyGate) -> str:
    """Call a registered OS tool by name with the given arguments."""
    if name == "open_application":
        return open_application(arguments.get("app_name", ""))
    if name == "mouse_and_keyboard":
        return mouse_and_keyboard(
            arguments.get("action", ""),
            arguments.get("x"),
            arguments.get("y"),
            arguments.get("text", ""),
        )
    if name == "capture_screen":
        return capture_screen()
    if name == "run_terminal_command":
        return run_terminal_command(arguments.get("command", ""), safety)
    if name == "manage_files":
        return manage_files(
            arguments.get("operation", ""),
            arguments.get("path", ""),
            arguments.get("content"),
            safety,
        )
    if name == "install_application":
        from .installer_tool import install_application

        return install_application(arguments.get("app_name", ""))
    if name == "describe_screen":
        from agent.vision_agent import describe_screen

        return describe_screen(arguments.get("focus", "overview"))
    return f"Unknown tool: {name}"


# ---- Cross-platform implementations ----


def _sys() -> str:
    return platform.system()


def open_application(app_name: str) -> str:
    """Launch an app cross-platform."""
    name = (app_name or "").strip()
    if not name:
        return "No application name provided."
    try:
        system = _sys()
        if system == "Windows":
            os.startfile(name)  # type: ignore[attr-defined]
            return f"Opened {name}."
        if system == "Darwin":
            subprocess.run(["open", "-a", name], check=False)
            return f"Opened {name}."
        # Linux: try common launchers.
        for cmd in (["xdg-open", name], ["gtk-launch", name]):
            try:
                subprocess.run(cmd, check=False)
                return f"Opened {name}."
            except FileNotFoundError:
                continue
        return f"Could not find a launcher for {name}."
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.exception("open_application failed")
        return f"Failed to open {name}: {exc}"


def mouse_and_keyboard(action: str, x, y, text: str) -> str:
    """Control mouse and keyboard via pyautogui."""
    if pyautogui is None:
        return "pyautogui is not installed. Run: pip install pyautogui"
    try:
        if action == "click":
            if x is None or y is None:
                return "Click requires x and y coordinates."
            pyautogui.click(int(x), int(y))
            return "Clicked."
        if action == "type":
            pyautogui.write(text or "")
            return "Typed."
        if action == "scroll":
            px = int(x) if x is not None else 0
            py = int(y) if y is not None else 0
            pyautogui.scroll(px, py)
            return "Scrolled."
        if action == "hotkey":
            keys = [k.strip() for k in (text or "").split(",") if k.strip()]
            if not keys:
                return "Hotkey requires a text list of keys."
            pyautogui.hotkey(*keys)
            return "Hotkey pressed."
        return f"Unknown mouse/keyboard action: {action}"
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.exception("mouse_and_keyboard failed")
        return f"Input failed: {exc}"


def capture_screen() -> str:
    """Take a compressed screenshot and return base64 data."""
    if mss is None:
        return "mss is not installed. Run: pip install mss"
    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            png = bytes(shot.rgb)
            return base64.b64encode(png).decode("ascii")
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.exception("capture_screen failed")
        return f"Screenshot failed: {exc}"


def run_terminal_command(command: str, safety: SafetyGate) -> str:
    """Run a shell command with confirmation gates for destructive actions."""
    if not command or not command.strip():
        return "No command provided."
    decision = safety.decide_shell(command)
    if decision.requires_confirmation:
        return (
            "Confirmation required before running destructive command: "
            f"{command}. Say 'yes' to approve or 'cancel' to deny."
        )
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        if proc.returncode != 0:
            return f"(exit {proc.returncode}) {err or out}".strip() or f"(exit {proc.returncode})"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30s."
    except OSError as exc:
        return f"OS error: {exc}"


def manage_files(operation: str, path: str, content: str | None, safety: SafetyGate) -> str:
    """Read, write, delete, search, or organize local files."""
    if not path:
        return "No file path provided."
    decision = safety.decide_file(operation, path)
    if decision.requires_confirmation:
        return (
            "Confirmation required before file operation: "
            f"{decision.reason}. Say 'yes' to approve or 'cancel' to deny."
        )
    p = Path(path)
    try:
        if operation == "read":
            if not p.exists():
                return f"Not found: {path}"
            return p.read_text(encoding="utf-8", errors="replace")
        if operation in ("write", "overwrite"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content or "", encoding="utf-8")
            return f"Wrote {len(content or '')} bytes to {path}"
        if operation in ("delete", "remove"):
            if p.is_dir():
                import shutil
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
            return f"Removed {path}"
        if operation == "search":
            if not p.exists():
                return f"Not found: {path}"
            needle = content or ""
            matches = []
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if needle in line:
                    matches.append(line)
            return "\n".join(matches[:50]) if matches else "No matches."
        if operation == "organize":
            return "Organize not yet implemented; use read/write/delete/search."
        return f"Unknown file operation: {operation}"
    except OSError as exc:
        return f"File operation error: {exc}"
