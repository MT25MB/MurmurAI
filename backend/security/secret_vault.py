"""OS-native credential storage for Murmur AI, with an encrypted local fallback.

Optional provider keys and MCP environment tokens belong in the operating
system's credential store, never in ~/.murmur-ai/config.json or
mcp_servers.json:

  * Windows  -> Credential Manager (via ``keyring``)
  * macOS    -> Keychain (via ``keyring``)
  * Linux    -> Secret Service / libsecret (via ``keyring``)
  * headless -> authenticated encrypted file under ~/.murmur-ai/ with a
    user-only 0600 key, used when no keyring daemon is reachable.

``keyring`` is imported lazily so the control plane still boots without it.
The fallback uses a stdlib encrypt-then-MAC construction (SHA-256 counter-mode
keystream + HMAC-SHA256), so it needs no third-party crypto package.

Privacy rule: status helpers (``secret_state``, ``configured_secrets``,
``secret_status_payload``) check only the *name index* and never retrieve a
secret value. Diagnostics bundles and audit logs can therefore report
"configured"/"missing" without ever touching a secret. ``get_secret`` is for
internal resolution at launch time only: never speak, log or serialize its
result.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("murmur_ai.security.secret_vault")

SERVICE_NAME = "MurmurAI"
VAULT_DIR = Path.home() / ".murmur-ai"
NAMES_PATH = VAULT_DIR / "secret_names.json"
FALLBACK_PATH = VAULT_DIR / "secrets.enc.json"
FALLBACK_KEY_PATH = VAULT_DIR / "secrets.key"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PROBE_NAME = "__murmur_vault_probe__"
_REFERENCE_RE = re.compile(r"^(?:\$\{secret:|keyring:)([A-Za-z0-9_.:-]+)\}$|^(?:keyring:)([A-Za-z0-9_.:-]+)$")

_state: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _restrict(path: Path) -> None:
    """Best-effort owner-only permissions for local fallback files."""
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - Windows ignores POSIX mode bits
        pass


def _usable_keyring():
    """Return a working keyring backend, or None for the encrypted fallback."""
    if "backend" in _state:
        return _state["backend"]
    backend = None
    try:
        import keyring  # type: ignore

        candidate = keyring.get_keyring()
        if candidate is not None:
            cls = candidate.__class__.__name__.lower()
            if "fail" not in cls and "null" not in cls:
                if any(native in cls for native in ("win", "osx", "mac")):
                    # Native OS stores are reliable; avoid a needless Keychain
                    # permission prompt just to probe them.
                    backend = candidate
                else:
                    # A real round trip is the only reliable way to detect a
                    # headless Linux box with no Secret Service daemon.
                    candidate.set_password(SERVICE_NAME, _PROBE_NAME, "probe")
                    if candidate.get_password(SERVICE_NAME, _PROBE_NAME) == "probe":
                        backend = candidate
                    try:
                        candidate.delete_password(SERVICE_NAME, _PROBE_NAME)
                    except Exception:
                        pass
    except Exception:  # pragma: no cover - optional dependency / no daemon
        logger.debug("No usable OS keyring; using encrypted local vault", exc_info=True)
    _state["backend"] = backend
    return backend


def backend_name() -> str:
    """Human-readable backend label for settings/diagnostics (never a value)."""
    backend = _usable_keyring()
    if backend is None:
        return "encrypted local vault"
    cls = backend.__class__.__name__.lower()
    if "win" in cls:
        return "Windows Credential Manager"
    if "osx" in cls or "mac" in cls:
        return "macOS Keychain"
    if "secret" in cls:
        return "Linux Secret Service"
    return f"OS keyring ({backend.__class__.__name__})"


# ---------------------------------------------------------------------------
# Name index (names only, never values)
# ---------------------------------------------------------------------------

def _validate_name(name: str) -> str:
    value = str(name or "").strip()
    if not NAME_RE.fullmatch(value):
        raise ValueError("Secret names use letters, numbers, dot, colon, dash and underscore only.")
    return value


def _read_names() -> set[str]:
    names: set[str] = set()
    try:
        loaded = json.loads(NAMES_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            names = {str(n) for n in loaded if NAME_RE.fullmatch(str(n))}
    except (OSError, json.JSONDecodeError):
        pass
    # The encrypted fallback also stores names inside its entries; include
    # them so listing survives a missing/partially written index.
    names.update(_read_entries().keys())
    names.discard(_PROBE_NAME)
    return names


def _write_names(names: set[str]) -> None:
    NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NAMES_PATH.write_text(
        json.dumps(sorted(names), indent=2), encoding="utf-8"
    )
    _restrict(NAMES_PATH)


# ---------------------------------------------------------------------------
# Encrypted local fallback (stdlib encrypt-then-MAC)
# ---------------------------------------------------------------------------

def _load_key() -> bytes:
    try:
        existing = FALLBACK_KEY_PATH.read_bytes()
        if len(existing) == 32:
            return existing
    except OSError:
        pass
    key = secrets.token_bytes(32)
    FALLBACK_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_KEY_PATH.write_bytes(key)
    _restrict(FALLBACK_KEY_PATH)
    return key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = (length + 31) // 32
    return b"".join(
        hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        for counter in range(blocks)
    )


def _encrypt(value: str) -> str:
    key = _load_key()
    nonce = secrets.token_bytes(16)
    data = value.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + cipher + tag).decode("ascii")


def _decrypt(blob: str) -> Optional[str]:
    try:
        raw = base64.urlsafe_b64decode(str(blob).encode("ascii"))
        if len(raw) < 48:
            return None
        nonce, cipher, tag = raw[:16], raw[16:-32], raw[-32:]
        key = _load_key()
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return None  # tampered or wrong key: treat as missing
        plain = bytes(a ^ b for a, b in zip(cipher, _keystream(key, nonce, len(cipher))))
        return plain.decode("utf-8")
    except Exception:  # pragma: no cover - corrupt local file
        return None


def _read_entries() -> dict[str, str]:
    try:
        data = json.loads(FALLBACK_PATH.read_text(encoding="utf-8"))
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        if isinstance(entries, dict):
            return {str(k): str(v) for k, v in entries.items() if NAME_RE.fullmatch(str(k))}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_entries(entries: dict[str, str]) -> None:
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_PATH.write_text(
        json.dumps({"version": 1, "entries": entries}, indent=2), encoding="utf-8"
    )
    _restrict(FALLBACK_PATH)


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def set_secret(name: str, value: str) -> bool:
    """Store a secret. The value is never logged or returned."""
    key = _validate_name(name)
    if value is None or not str(value):
        raise ValueError("Secret value cannot be empty.")
    backend = _usable_keyring()
    if backend is not None:
        backend.set_password(SERVICE_NAME, key, str(value))
    else:
        entries = _read_entries()
        entries[key] = _encrypt(str(value))
        _write_entries(entries)
    names = _read_names()
    names.add(key)
    _write_names(names)
    logger.info("Stored secret reference %s in %s", key, backend_name())
    return True


def get_secret(name: str) -> Optional[str]:
    """Resolve a secret for internal use only. NEVER speak or serialize this."""
    try:
        key = _validate_name(name)
    except ValueError:
        return None
    backend = _usable_keyring()
    if backend is not None:
        return backend.get_password(SERVICE_NAME, key)
    return _decrypt(_read_entries().get(key, ""))


def delete_secret(name: str) -> bool:
    """Remove a secret by name. Returns False when it was not configured."""
    key = _validate_name(name)
    known = key in _read_names()
    backend = _usable_keyring()
    if backend is not None:
        try:
            backend.delete_password(SERVICE_NAME, key)
        except Exception:  # pragma: no cover - some backends raise if absent
            pass
    else:
        entries = _read_entries()
        if key in entries:
            entries.pop(key)
            _write_entries(entries)
    names = _read_names()
    names.discard(key)
    _write_names(names)
    logger.info("Deleted secret reference %s", key)
    return known


def secret_state(name: str) -> str:
    """Return only 'configured' or 'missing', never reads the value."""
    try:
        key = _validate_name(name)
    except ValueError:
        return "missing"
    return "configured" if key in _read_names() else "missing"


def configured_secrets() -> list[dict[str, str]]:
    """Status-only list of known secret references, safe for diagnostics."""
    return [
        {"name": name, "state": "configured"}
        for name in sorted(_read_names())
    ]


def secret_status_payload() -> dict[str, Any]:
    """Manifest-safe summary: backend label plus configured/missing states."""
    return {
        "backend": backend_name(),
        "secrets": configured_secrets(),
        "note": "Only names and configured/missing state are reported. Values are never exported.",
    }


def resolve_secret_env(env: dict[str, str]) -> dict[str, str]:
    """Replace ${secret:NAME} / keyring:NAME env values from the vault.

    Used at MCP launch time so tokens never appear in config.json,
    mcp_servers.json, diagnostics, or audit logs.
    """
    resolved: dict[str, str] = {}
    for key, raw in (env or {}).items():
        text = str(raw)
        match = _REFERENCE_RE.fullmatch(text)
        if match:
            ref = match.group(1) or match.group(2)
            value = get_secret(ref)
            if value is None:
                logger.warning("Secret %s is missing; leaving %s empty", ref, key)
                resolved[str(key)] = ""
            else:
                resolved[str(key)] = value
        else:
            resolved[str(key)] = text
    return resolved


def reset() -> None:
    """Clear cached backend detection (used by tests and settings reloads)."""
    _state.clear()


# ---------------------------------------------------------------------------
# Voice / brain tools, confirmations never include secret values
# ---------------------------------------------------------------------------

SECRET_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_secret_reference",
            "description": (
                "Store an optional provider key or MCP token in the OS keychain "
                "(or the encrypted local vault when no keychain daemon exists). "
                "The value is hidden: never repeat it aloud or in a summary. "
                "Confirm only that the named secret was stored."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short reference name, e.g. 'mcp.github.token'.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The secret value. Do not echo it back.",
                    },
                },
                "required": ["name", "value"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_configured_secrets",
            "description": (
                "List which secret references are configured or missing. Reports "
                "names and status only; never reads or speaks secret values."
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
            "name": "delete_secret",
            "description": (
                "Delete a named secret from the keychain. Requires an explicit "
                "confirm=true argument after the user confirms; never speaks or "
                "returns the deleted value."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Secret reference to remove."},
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually delete after user confirmation.",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
]


def set_secret_reference(name: str, value: str) -> str:
    """Spoken-safe confirmation of a stored secret (value is never repeated)."""
    try:
        key = _validate_name(name)
        set_secret(key, value)
        return f"Stored {key} in your {backend_name()}. I won't repeat the value."
    except ValueError as exc:
        return f"I couldn't store that secret: {exc}"


def list_configured_secrets() -> str:
    """Spoken-safe list of configured secret names, with no values."""
    secrets_list = configured_secrets()
    if not secrets_list:
        return "No secret references are configured."
    names = ", ".join(item["name"] for item in secrets_list)
    return f"{len(secrets_list)} secret reference(s) configured: {names}. Values are hidden."


def delete_secret_reference(name: str, confirm: bool = False) -> str:
    """Brain-facing delete with an explicit confirmation step."""
    try:
        key = _validate_name(name)
    except ValueError as exc:
        return f"I couldn't delete that secret: {exc}"
    if not confirm:
        return f"Say 'confirm delete secret {key}' to erase it."
    if not delete_secret(key):
        return f"Secret {key} was not configured."
    return f"Secret {key} deleted from your {backend_name()}."
