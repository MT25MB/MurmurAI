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
import time
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
from .event_bus import tool_bus
from . import undo_journal as journal

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

UNDO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "undo_last_action",
            "description": (
                "Undo the last action: reverse a recent file move when reversible, "
                "otherwise send the active app's undo shortcut."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }
]


def _undo_last_file_move() -> bool:
    return journal.undo_last()


def undo_last_action() -> str:
    """Reverse the last reversible move, or send the platform undo shortcut."""
    if _undo_last_file_move():
        return "Reverted the last file move."
    try:
        if platform.system() == "Darwin":
            pyautogui.hotkey("command", "z")
        else:
            pyautogui.hotkey("ctrl", "z")
        return "Sent undo to the active app."
    except Exception:  # pragma: no cover - platform dependent
        logger.debug("Undo shortcut failed", exc_info=True)
        return "I couldn't send undo to the active app."


def dispatch_tool(name: str, arguments: dict, safety: SafetyGate) -> str:
    """Call a registered OS tool by name with the given arguments."""
    from .a11y_tree import handle_a11y_tool
    from .memory_tools import handle_memory_tool
    from skills.pack_loader import handle_skill_tool

    skill_result = handle_skill_tool(name, arguments)
    if skill_result is not None:
        return skill_result

    from .tool_recipes import handle_recipe_tool
    from .text_edit_tools import handle_text_edit_tool

    a11y_result = handle_a11y_tool(name, arguments)
    if a11y_result is not None:
        return a11y_result

    recipe_result = handle_recipe_tool(name, arguments)
    if recipe_result is not None:
        return recipe_result
    memory_result = handle_memory_tool(name, arguments)
    if memory_result is not None:
        return memory_result
    text_edit_result = handle_text_edit_tool(name, arguments)
    if text_edit_result is not None:
        return text_edit_result
    if name == "undo_last_action":
        return undo_last_action()
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
    if name in ("open_url", "read_page_summary", "click_web_element", "fill_web_field"):
        from .browser_tool import (
            click_web_element,
            fill_web_field,
            open_url,
            read_page_summary,
        )

        if name == "open_url":
            return open_url(arguments.get("url", ""))
        if name == "read_page_summary":
            return read_page_summary()
        if name == "click_web_element":
            return click_web_element(arguments.get("label_or_role", ""))
        return fill_web_field(arguments.get("field_label", ""), arguments.get("text", ""))
    if name in ("list_open_windows", "focus_or_manage_window"):
        from .window_tools import focus_or_manage_window, list_open_windows

        if name == "list_open_windows":
            return list_open_windows()
        return focus_or_manage_window(
            arguments.get("app_or_title", ""), arguments.get("action", "focus")
        )
    if name == "set_active_monitor":
        from agent.vision_agent import set_active_monitor

        return set_active_monitor(arguments.get("monitor", 1))
    if name == "list_mcp_tools":
        from .mcp_manager import list_plugins

        return list_plugins()
    if name == "reload_mcp_plugins":
        from .mcp_manager import reload_plugins

        return reload_plugins().get("summary", "Plugins reloaded.")
    if name in ("read_clipboard", "write_clipboard", "inspect_recent_files"):
        from .context_tools import (
            inspect_recent_files,
            read_clipboard,
            write_clipboard,
        )

        if name == "read_clipboard":
            return read_clipboard()
        if name == "write_clipboard":
            return write_clipboard(arguments.get("text", ""))
        return inspect_recent_files(
            arguments.get("directory", "downloads"),
            int(arguments.get("limit", 5) or 5),
        )
    if name in ("find_files", "read_document_aloud", "organize_files"):
        from .file_tools import find_files, organize_files, read_document_aloud

        if name == "find_files":
            return find_files(
                arguments.get("query", ""),
                arguments.get("location", "home"),
                arguments.get("extension"),
                int(arguments.get("limit", 10) or 10),
            )
        if name == "read_document_aloud":
            return read_document_aloud(
                arguments.get("file_path", ""), arguments.get("section_or_query")
            )
        return organize_files(
            arguments.get("pattern_or_paths", []),
            arguments.get("destination_folder", ""),
            arguments.get("action", "move"),
        )
    if name == "add_pronunciation":
        from audio.pronunciation import add_pronunciation

        return add_pronunciation(
            arguments.get("word", ""), arguments.get("spoken_as", "")
        )
    if name == "start_demo":
        from system.demo import start_demo

        return start_demo()
    if name == "set_voice_profile":
        from audio.voice_profiles import apply_voice_profile

        return apply_voice_profile(arguments.get("profile", "default"))
    if name == "export_diagnostics":
        from system.diagnostics_bundle import export_diagnostics

        return export_diagnostics()
    if name == "run_diagnostics":
        from system.settings_tools import run_diagnostics

        return run_diagnostics()["summary"]
    if name == "get_settings":
        from system.settings_tools import settings_summary

        return settings_summary()
    if name == "set_setting":
        from system.settings_tools import settings_summary, update_settings

        update_settings(arguments.get("changes", {}))
        return settings_summary()
    if name.startswith("mcp__"):
        from .mcp_manager import call_mcp_tool

        return call_mcp_tool(name, arguments)
    return f"Unknown tool: {name}"


# ---- Cross-platform implementations ----


def _sys() -> str:
    return platform.system()


# Only apps that have no launchable file need a protocol hint. Everything else
# is discovered generically from Start Menu shortcuts, PATH and the OS shell.
WINDOWS_APP_ALIASES: dict[str, tuple[str, ...]] = {
    "calculator": ("ms-calculator:",),
    "calc": ("ms-calculator:",),
    "settings": ("ms-settings:",),
    "photos": ("ms-photos:",),
    "store": ("ms-windows-store:",),
    "mail": ("mailto:",),
}


def _windows_launch(name: str) -> bool:
    """Try shell aliases, Start Menu shortcuts, then a Start-menu search."""
    key = name.strip().lower().strip('"').strip("'")
    candidates = list(WINDOWS_APP_ALIASES.get(key, ()))
    candidates += [name, f"{name}.exe"]
    for target in candidates:
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        except Exception:
            continue

    # Start Menu .lnk shortcuts (including installed desktop apps).
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    for root in roots:
        if not root.exists():
            continue
        for shortcut in root.rglob("*.lnk"):
            if key in shortcut.stem.lower() or key.replace(" ", "") in shortcut.stem.lower().replace(" ", ""):
                try:
                    os.startfile(str(shortcut))  # type: ignore[attr-defined]
                    return True
                except Exception:
                    continue

    # Generic PATH lookup so we never need a per-app alias.
    try:
        found = subprocess.run(
            ["where.exe", f"{name}.exe"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in (found.stdout or "").splitlines():
            executable = line.strip()
            if executable and Path(executable).is_file():
                os.startfile(executable)  # type: ignore[attr-defined]
                return True
    except Exception:  # pragma: no cover - platform dependent
        pass

    # Let Windows resolve App Paths / shell associations itself.
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", name],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:  # pragma: no cover - platform dependent
        pass

    # Human-style fallback: Win key, type the app name, press Enter.
    if pyautogui is not None:
        try:
            pyautogui.press("win")
            time.sleep(0.35)
            pyautogui.write(name, interval=0.02)
            time.sleep(0.5)
            pyautogui.press("enter")
            return True
        except Exception:
            logger.exception("Start menu launch fallback failed")
    return False


def open_application(app_name: str) -> str:
    """Launch an app cross-platform."""
    name = (app_name or "").strip()
    if not name:
        return "No application name provided."
    try:
        system = _sys()
        if system == "Windows":
            if _windows_launch(name):
                return f"Opened {name}."
            return f"Could not find a way to open {name}. Check the app name and try again."
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


def _cursor_overlay_event(px: int, py: int, kind: str = "click") -> None:
    """Mark a real automated action on the optional click-through overlay."""
    try:
        from agent.state import ServerMessage
        from tools.event_bus import tool_bus

        tool_bus.emit(ServerMessage(type="cursor", x=int(px), y=int(py), kind=kind))
    except Exception:  # pragma: no cover - reporting must never block an action
        logger.debug("Cursor overlay event failed", exc_info=True)


def mouse_and_keyboard(action: str, x, y, text: str) -> str:
    """Control mouse and keyboard via pyautogui."""
    if pyautogui is None:
        return "pyautogui is not installed. Run: pip install pyautogui"
    try:
        if action == "click":
            if x is None or y is None:
                return "Click requires x and y coordinates."
            _cursor_overlay_event(int(x), int(y))
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
        description = f"Run shell command: {command}"
        if not tool_bus.request_confirmation(description, command):
            return "Action cancelled by user."
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
        command = f"{operation} {path}"
        if not tool_bus.request_confirmation(decision.reason, command):
            return "Action cancelled by user."
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
