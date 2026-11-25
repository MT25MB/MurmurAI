"""Privacy-safe local diagnostics bundles for GitHub issues.

Collects recent Murmur AI logs, a hardware/OS profile, localhost-only Ollama
status and the active config into a zip on the Desktop (or
~/.murmur-ai/diagnostics/). Anything that looks like a secret, credential,
custom path, email or environment value is redacted before it is written.
Never contacts an external network.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("murmur_ai.system.diagnostics_bundle")

CONFIG_PATH = Path.home() / ".murmur-ai" / "config.json"
MCP_CONFIG_PATH = Path.home() / ".murmur-ai" / "mcp_servers.json"
HOME_LOG_DIR = Path.home() / ".murmur-ai" / "logs"
BACKEND_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
DESKTOP_DIR = Path.home() / "Desktop"
FALLBACK_DIR = Path.home() / ".murmur-ai" / "diagnostics"

REDACTED = "<redacted>"
REDACTED_PATH = "<path redacted>"
SENSITIVE_KEY_WORDS = (
    "key", "token", "secret", "password", "passwd", "pass", "cred",
    "auth", "private", "api", "email", "phone", "user", "owner", "account",
    "address", "path", "dir", "folder", "home", "url", "endpoint", "host", "env",
)
LOG_MAX_AGE_DAYS = 7
LOG_MAX_BYTES = 5 * 1024 * 1024
MAX_LOG_FILES = 60


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def _looks_like_path(value: str) -> bool:
    stripped = value.strip()
    if "://" in stripped:  # URLs are handled by query-token redaction instead.
        return False
    return bool(
        stripped.startswith(("/", "~", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", stripped)
        or re.search(r"[\\/][^\s]+[\\/]", stripped)
    )


def sanitize_value(key: str, value: Any) -> Any:
    """Redact secrets and custom paths from a config key/value pair."""
    lowered = str(key).lower()
    if any(word in lowered for word in SENSITIVE_KEY_WORDS):
        return REDACTED
    if isinstance(value, dict):
        return {k: sanitize_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(key, item) for item in value]
    if isinstance(value, str):
        if not value:
            return value
        if _looks_like_path(value):
            return REDACTED_PATH
        # Strip query strings that may carry tokens.
        value = re.sub(r"([?&](?:token|key|sig|password|auth)=)[^&\s]+", r"\1" + REDACTED, value, flags=re.I)
        return value
    return value


def sanitize_config(data: dict[str, Any]) -> dict[str, Any]:
    return {str(k): sanitize_value(str(k), v) for k, v in (data or {}).items()}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect_log_files() -> list[Path]:
    """Recent, bounded-size log files from the two known local log dirs."""
    cutoff = time.time() - LOG_MAX_AGE_DAYS * 86400
    found: list[Path] = []
    for root in (HOME_LOG_DIR, BACKEND_LOG_DIR):
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".log", ".json", ".txt", ".jsonl"}:
                    continue
                # Visual-agent step logs and screen descriptions contain verbatim
                # on-screen text; a "privacy-safe" bundle must not include them.
                relative = path.relative_to(root).as_posix()
                if relative.startswith(("step_", "describe/")) or "/describe/" in relative:
                    continue
                stat = path.stat()
                if stat.st_mtime < cutoff or stat.st_size > LOG_MAX_BYTES:
                    continue
                found.append(path)
        except OSError:
            continue
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[:MAX_LOG_FILES]


def _hardware_profile() -> dict[str, Any]:
    from system.profiler import detect_hardware, recommend_config

    profile = detect_hardware()
    return {
        "hardware": profile.to_dict(),
        "recommendation": recommend_config(profile),
    }


def _ollama_status() -> dict[str, Any]:
    import setup as setup_module

    try:
        status = setup_module.ollama_status()
    except Exception:  # pragma: no cover - localhost only, non-fatal
        status = {"running": False, "error": "status check failed"}
    # Install paths are custom paths; scrub them.
    return sanitize_config(status)


def build_manifest() -> dict[str, Any]:
    config = _read_json(CONFIG_PATH)
    mcp_config = _read_json(MCP_CONFIG_PATH)
    from system.settings_tools import load_settings
    from security.secret_vault import secret_status_payload

    settings = load_settings()
    return {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_version": "1.2.40",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "redaction": (
            "Secrets, credentials, custom paths, env values, emails and user "
            "identifiers are replaced with <redacted>/<path redacted>. Keychain "
            "secrets are reported only as configured/missing; their values are "
            "never read into this bundle."
        ),
        "hardware": _hardware_profile(),
        "ollama": _ollama_status(),
        "config": sanitize_config({**settings, **config}),
        "mcp_servers": sanitize_config(mcp_config),
        # Status only: the vault helper never retrieves a secret value.
        "secrets": secret_status_payload(),
        "environment_whitelist": {
            key: REDACTED
            for key in ("OLLAMA_MODEL", "OLLAMA_VISION_MODEL", "WHISPER_MODEL")
            if key in os.environ
        },
    }


def export_diagnostics(output_dir: Optional[Path | str] = None, speak: bool = True) -> str:
    """Create a local zip bundle and return its exact absolute path."""
    destination = Path(output_dir).expanduser() if output_dir else (
        DESKTOP_DIR if DESKTOP_DIR.is_dir() else FALLBACK_DIR
    )
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    archive_path = destination / f"murmur-diagnostics-{timestamp}.zip"

    manifest = build_manifest()
    logs = collect_log_files()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for path in logs:
            try:
                arcname = f"logs/{path.name}"
                bundle.write(path, arcname)
            except OSError:
                continue
        bundle.writestr(
            "README.txt",
            "Murmur AI diagnostics bundle. All user paths and credentials are redacted.\n"
            "Keychain secrets are reported by name/status only; values are never exported.\n"
            "Attach this zip to a GitHub issue to help reproduce a bug.\n",
        )

    if speak:
        _speak(f"Diagnostics exported to {archive_path}")
    return str(archive_path)


def _speak(text: str) -> None:
    try:  # pragma: no cover - TTS optional
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            speaker.speak(text)
    except Exception:
        logger.debug("Diagnostics export announcement failed", exc_info=True)


DIAGNOSTICS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "export_diagnostics",
            "description": (
                "Create a privacy-safe local diagnostics zip (logs, hardware "
                "profile, Ollama status and sanitized config) and speak its exact "
                "path. Use when the user wants to report a bug or attach a log."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]
