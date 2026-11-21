"""Safety gate for destructive shell commands and file deletions.

Any destructive action must require explicit spoken/UI confirmation before it
runs. Denied or timed-out confirmations are treated as ``no``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess  # module-level so execution can be mocked in tests
from typing import Callable

logger = logging.getLogger("murmur_ai.safety")

# Destructive command tokens. These always require confirmation.
DESTRUCTIVE_COMMANDS = {
    "rm", "del", "erase", "rd", "rmdir",
    "format", "mkfs", "fdisk",
    "sudo", "runas",
    "shutdown", "reboot", "halt",
    "kill", "taskkill",
    "chmod", "chown", "icacls",
}

# File-path deletion / overwrite operations.
DESTRUCTIVE_FILE_OPS = {"delete", "remove", "write", "overwrite"}

# Regex catching common rm/flags variants.
DESTRUCTIVE_SHELL_RE = re.compile(
    r"\b(rm|del|erase|rmdir|format|mkfs|shutdown|reboot|kill|taskkill|sudo|runas|chmod|chown|icacls)\b",
    re.IGNORECASE,
)


@dataclass
class SafetyDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str = ""


class SafetyGate:
    """Decides whether an action may run without confirmation and records it."""

    def __init__(self, confirm_callback: Callable[[str, str], bool] | None = None):
        """confirm_callback(description, command) -> bool (user approved?)."""
        self.confirm_callback = confirm_callback
        self.audit: list[dict] = []

    def shell_requires_confirmation(self, command: str) -> bool:
        """True if the shell command is destructive and needs approval."""
        shell = shlex.split(command)[0] if shlex.split(command) else ""
        if shell.lower() in DESTRUCTIVE_COMMANDS:
            return True
        if DESTRUCTIVE_SHELL_RE.search(command):
            return True
        return False

    def decide_shell(self, command: str) -> SafetyDecision:
        if not self.shell_requires_confirmation(command):
            return SafetyDecision(allowed=True, requires_confirmation=False)
        return SafetyDecision(allowed=False, requires_confirmation=True, reason="destructive shell command")

    def run_shell(self, command: str) -> str:
        """Run a shell command with confirmation gates. Returns stdout/stderr text."""
        decision = self.decide_shell(command)
        if decision.requires_confirmation:
            if self.confirm_callback is None:
                return (
                    "Confirmation required for destructive command: "
                    f"{command}. No confirmation callback is configured."
                )
            description = f"Shell command: {command}"
            if not self.confirm_callback(description, command):
                self.audit.append({"action": "shell", "command": command, "decision": "denied"})
                return "Action cancelled by user."
        self.audit.append({"action": "shell", "command": command, "decision": "approved"})
        return _run_command(command)

    def file_operation_requires_confirmation(self, operation: str, path: str) -> bool:
        op = (operation or "").lower()
        if op in DESTRUCTIVE_FILE_OPS:
            return True
        return False

    def decide_file(self, operation: str, path: str) -> SafetyDecision:
        if not self.file_operation_requires_confirmation(operation, path):
            return SafetyDecision(allowed=True, requires_confirmation=False)
        return SafetyDecision(
            allowed=False,
            requires_confirmation=True,
            reason=f"file operation '{operation}' on {path}",
        )

    def run_file_operation(self, operation: str, path: str, content: str | None = None) -> str:
        decision = self.decide_file(operation, path)
        if decision.requires_confirmation:
            if self.confirm_callback is None:
                return (
                    f"Confirmation required: {decision.reason}. No confirmation callback is configured."
                )
            if not self.confirm_callback(decision.reason, f"{operation} {path}"):
                self.audit.append({"action": "file", "operation": operation, "path": path, "decision": "denied"})
                return "Action cancelled by user."
        self.audit.append({"action": "file", "operation": operation, "path": path, "decision": "approved"})
        return _file_operation(operation, path, content)


def is_destructive(command: str | None = None, operation: str | None = None, path: str | None = None) -> bool:
    """Convenience check used by tool wrappers before execution."""
    if command and SafetyGate().shell_requires_confirmation(command):
        return True
    if operation and path and SafetyGate().file_operation_requires_confirmation(operation, path):
        return True
    return False


def _run_command(command: str) -> str:
    import subprocess

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


def _file_operation(operation: str, path: str, content: str | None = None) -> str:
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
            return "Organize not yet implemented; specify read/write/delete/search."
        return f"Unknown file operation: {operation}"
    except OSError as exc:
        return f"File operation error: {exc}"



