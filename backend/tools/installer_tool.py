"""Cross-platform application installer for Murmur AI.

Strategy (per AGENTS.md: local, confirmed, no silent destructive actions):
  1. Detect the best available native CLI package manager for the OS.
  2. Search for an exact package id, build a silent/non-interactive command.
  3. Emit CONFIRMATION_REQUIRED to the HUD and block until the user approves.
  4. Stream stdout/stderr progress to the HUD as `progress` events.
  5. If nothing is found in any CLI manager, hand the goal off to the visual
     agent (vision_agent.py) to download from the official website in a browser.
"""

from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .event_bus import tool_bus

logger = logging.getLogger("murmur_ai.tools.installer")

# ---- JSON-schema tool definition (registered with the brain) ----

INSTALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "install_application",
            "description": (
                "Install an application on the local machine using native silent "
                "package managers (winget/choco/brew/flatpak/snap/apt/dnf/pacman). "
                "Asks the user for confirmation before installing. Falls back to "
                "visually downloading from the official website if not found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the application to install, e.g. 'Blender'.",
                    }
                },
                "required": ["app_name"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass
class PackagePlan:
    """A resolved, ready-to-run installation plan."""

    manager: str
    package_id: str
    search_command: list[str]
    install_command: list[str]
    description: str


# ---- cross-platform detection ----

def _run_capture(command: list[str], timeout: int = 30) -> str:
    """Run a read-only command and return combined output (never raises)."""
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return ""
    except subprocess.TimeoutExpired:
        return ""
    except OSError:
        return ""


def _first_exact_match(output: str, app_name: str) -> Optional[str]:
    """Pick the best package id token from search output."""
    needle = app_name.strip().lower()
    lines = [ln for ln in output.splitlines() if ln.strip()]
    # Prefer exact full-token matches.
    for ln in lines:
        for token in re.split(r"\s+", ln.strip()):
            if token.lower() == needle:
                return token
    # Winget IDs often look like "Publisher.App".
    for ln in lines:
        for token in re.split(r"\s+", ln.strip()):
            if needle in token.lower() and "." in token:
                return token
    # Any token containing the app name.
    for ln in lines:
        for token in re.split(r"\s+", ln.strip()):
            if needle in token.lower() and len(token) < 60:
                return token
    return None


def _parse_winget_id(output: str, app_name: str) -> Optional[str]:
    """Parse the ID column from `winget search` table output."""
    needle = app_name.strip().lower()
    for line in output.splitlines():
        if not line.strip() or line.lstrip().lower().startswith(("name", "-", "no package")):
            continue
        columns = re.split(r"\s{2,}", line.strip())
        if len(columns) >= 2:
            name, pid = columns[0], columns[1]
            if needle in name.lower() or needle in pid.lower():
                return pid
    return None


def _detect_windows(app_name: str) -> Optional[PackagePlan]:
    """winget first, then choco."""
    if shutil.which("winget"):
        out = _run_capture(
            ["winget", "search", "--name", app_name, "--accept-source-agreements"]
        )
        pid = _parse_winget_id(out, app_name) or _first_exact_match(out, app_name)
        if pid:
            return PackagePlan(
                manager="winget",
                package_id=pid,
                search_command=["winget", "search", "--name", app_name],
                install_command=[
                    "winget", "install", "--id", pid,
                    "--silent", "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                description=f"Install {app_name} ({pid}) with winget",
            )
    if shutil.which("choco"):
        out = _run_capture(["choco", "search", app_name, "--no-progress"])
        pid = _first_exact_match(out, app_name)
        if pid:
            return PackagePlan(
                manager="choco",
                package_id=pid,
                search_command=["choco", "search", app_name],
                install_command=["choco", "install", pid, "-y", "--no-progress"],
                description=f"Install {app_name} ({pid}) with Chocolatey",
            )
    return None


def _detect_macos(app_name: str) -> Optional[PackagePlan]:
    if not shutil.which("brew"):
        return None
    token = re.sub(r"[^a-z0-9-]", "", app_name.lower())
    # Try cask first (GUI apps), then formula.
    cask_out = _run_capture(["brew", "search", "--cask", token])
    if _first_exact_match(cask_out, token):
        return PackagePlan(
            manager="brew-cask",
            package_id=token,
            search_command=["brew", "search", "--cask", token],
            install_command=["brew", "install", "--cask", token],
            description=f"Install {app_name} with Homebrew Cask",
        )
    formula_out = _run_capture(["brew", "search", token])
    if _first_exact_match(formula_out, token):
        return PackagePlan(
            manager="brew",
            package_id=token,
            search_command=["brew", "search", token],
            install_command=["brew", "install", token],
            description=f"Install {app_name} with Homebrew",
        )
    return None


def _detect_linux(app_name: str) -> Optional[PackagePlan]:
    """Auto-detect in order: flatpak, snap, apt, dnf, pacman."""
    token = re.sub(r"[^a-z0-9.\-]", "", app_name.lower())

    if shutil.which("flatpak"):
        out = _run_capture(["flatpak", "search", app_name])
        pid = _first_exact_match(out, app_name)
        if pid:
            return PackagePlan(
                manager="flatpak",
                package_id=pid,
                search_command=["flatpak", "search", app_name],
                install_command=["flatpak", "install", "-y", "flathub", pid],
                description=f"Install {app_name} ({pid}) with Flatpak",
            )

    if shutil.which("snap"):
        out = _run_capture(["snap", "find", app_name])
        pid = _first_exact_match(out, app_name)
        if pid:
            return PackagePlan(
                manager="snap",
                package_id=pid,
                search_command=["snap", "find", app_name],
                install_command=["snap", "install", pid],
                description=f"Install {app_name} ({pid}) with Snap",
            )

    if shutil.which("apt-get"):
        out = _run_capture(["apt-cache", "search", app_name]) if shutil.which("apt-cache") else ""
        pid = _first_exact_match(out, app_name) or token
        if pid:
            return PackagePlan(
                manager="apt",
                package_id=pid,
                search_command=["apt-cache", "search", app_name],
                install_command=[
                    "sudo", "env", "DEBIAN_FRONTEND=noninteractive",
                    "apt-get", "install", "-y", pid,
                ],
                description=f"Install {app_name} ({pid}) with apt",
            )

    if shutil.which("dnf"):
        out = _run_capture(["dnf", "search", app_name])
        pid = _first_exact_match(out, app_name) or token
        if pid:
            return PackagePlan(
                manager="dnf",
                package_id=pid,
                search_command=["dnf", "search", app_name],
                install_command=["sudo", "dnf", "install", "-y", pid],
                description=f"Install {app_name} ({pid}) with dnf",
            )

    if shutil.which("pacman"):
        out = _run_capture(["pacman", "-Ss", app_name])
        pid = _first_exact_match(out, app_name) or token
        if pid:
            return PackagePlan(
                manager="pacman",
                package_id=pid,
                search_command=["pacman", "-Ss", app_name],
                install_command=["sudo", "pacman", "-S", "--noconfirm", pid],
                description=f"Install {app_name} ({pid}) with pacman",
            )
    return None


def detect_install_plan(app_name: str) -> Optional[PackagePlan]:
    """Detect the best native install plan for the current OS."""
    system = platform.system()
    if system == "Windows":
        return _detect_windows(app_name)
    if system == "Darwin":
        return _detect_macos(app_name)
    return _detect_linux(app_name)


# ---- progress streaming ----

_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


def _extract_percent(line: str) -> Optional[int]:
    match = _PERCENT_RE.search(line)
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 100 else None


def _stream_install(plan: PackagePlan, app_name: str) -> tuple[bool, str]:
    """Run the install command, streaming progress. Returns (success, detail)."""
    tool_bus.progress(f"Installing {app_name} with {plan.manager}…")
    logger.info("Running install command: %s", " ".join(plan.install_command))
    try:
        proc = subprocess.Popen(
            plan.install_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return False, f"Could not start installer: {exc}"

    last_lines: list[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        last_lines.append(line)
        if len(last_lines) > 8:
            last_lines.pop(0)
        percent = _extract_percent(line)
        # Keep the HUD message short and useful for voice/text display.
        preview = line if len(line) <= 90 else line[:87] + "..."
        tool_bus.progress(preview, percent)

    return_code = proc.wait()
    if return_code == 0:
        return True, f"{app_name} installed successfully with {plan.manager}."
    detail = " | ".join(last_lines[-3:])
    return False, f"Installer exited with code {return_code}. {detail}".strip()


# ---- vision handoff ----

def _vision_handoff(app_name: str) -> str:
    """Open a browser and install from the official site via the visual agent."""
    tool_bus.progress(
        f"Couldn't find {app_name} in any package manager. "
        "Opening a browser to install it from the official website."
    )
    try:
        from agent.vision_agent import VisionAgent

        agent = VisionAgent()
        goal = f"Download and install {app_name} from its official website"
        result = agent.run_visual_task(goal)
        return f"Visual install handoff finished: {result}"
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.exception("Vision handoff failed")
        return (
            f"I couldn't install {app_name} automatically and the visual "
            f"handoff failed: {exc}"
        )


# ---- public tool ----

def install_application(app_name: str) -> str:
    """Install an application, with confirmation + progress + vision fallback."""
    app_name = (app_name or "").strip()
    if not app_name:
        return "Please tell me which application to install."

    tool_bus.progress(f"Looking for {app_name} in local package managers…")
    plan = detect_install_plan(app_name)

    if plan is None:
        return _vision_handoff(app_name)

    # Safety gate: exact package name + command, explicit approval required.
    approved = tool_bus.request_confirmation(
        description=f"Install {app_name} ({plan.package_id}) using {plan.manager}?",
        command=" ".join(plan.install_command),
    )
    if not approved:
        return "Installation cancelled. Nothing was installed."

    success, detail = _stream_install(plan, app_name)

    # Speak the outcome aloud via the HUD (the brain also turns this into voice).
    from agent.state import ServerMessage
    tool_bus.emit(
        ServerMessage(
            type="text_output",
            text=detail if success else f"Install failed. {detail}",
        )
    )
    return detail
