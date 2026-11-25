"""OS keychain / encrypted fallback vault tests (no real keychain, no network)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import agent.brain as brain
import security.secret_vault as sv
import system.diagnostics_bundle as db
import system.settings_tools as st
import tools.os_tools as os_tools
from security.secret_vault import (
    SECRET_TOOLS,
    backend_name,
    configured_secrets,
    delete_secret,
    delete_secret_reference,
    get_secret,
    list_configured_secrets,
    resolve_secret_env,
    secret_state,
    secret_status_payload,
    set_secret,
    set_secret_reference,
)


@pytest.fixture(autouse=True)
def _isolated_vault(monkeypatch, tmp_path):
    """Redirect all vault files to tmp and force the encrypted fallback."""
    monkeypatch.setattr(sv, "NAMES_PATH", tmp_path / "secret_names.json")
    monkeypatch.setattr(sv, "FALLBACK_PATH", tmp_path / "secrets.enc.json")
    monkeypatch.setattr(sv, "FALLBACK_KEY_PATH", tmp_path / "secrets.key")
    monkeypatch.setitem(sv._state, "backend", None)
    monkeypatch.delitem(sys.modules, "keyring", raising=False)
    yield
    sv.reset()


class FakeKeyring:
    """In-memory stand-in for a working OS keyring backend."""

    def __init__(self, fail_get: bool = False):
        self.rows: dict[tuple[str, str], str] = {}
        self.fail_get = fail_get

    def set_password(self, service, name, value):
        self.rows[(service, name)] = value

    def get_password(self, service, name):
        if self.fail_get:
            raise AssertionError("status helpers must never call get_password")
        return self.rows.get((service, name))

    def delete_password(self, service, name):
        self.rows.pop((service, name), None)


# ---- validation / fallback storage ----

@pytest.mark.parametrize("bad", ["", "   ", "bad name", "../etc/passwd", "-lead", "x" * 129])
def test_invalid_names_rejected(bad):
    with pytest.raises(ValueError):
        set_secret(bad, "value")
    assert get_secret(bad) is None
    assert secret_state(bad) == "missing"


def test_encrypted_fallback_round_trip(tmp_path):
    assert backend_name() == "encrypted local vault"
    assert set_secret("mcp.github.token", "ghp_SENTINEL_12345") is True
    assert get_secret("mcp.github.token") == "ghp_SENTINEL_12345"
    assert secret_state("mcp.github.token") == "configured"

    blob = json.loads(sv.FALLBACK_PATH.read_text(encoding="utf-8"))["entries"]["mcp.github.token"]
    assert "ghp_SENTINEL_12345" not in blob
    assert "ghp_SENTINEL_12345" not in sv.FALLBACK_PATH.read_text(encoding="utf-8")
    assert len(sv.FALLBACK_KEY_PATH.read_bytes()) == 32


def test_fallback_detects_tampered_entry(tmp_path):
    set_secret("key", "original")
    data = json.loads(sv.FALLBACK_PATH.read_text(encoding="utf-8"))
    first = data["entries"]["key"]
    data["entries"]["key"] = first[:20] + ("A" if first[20] != "A" else "B") + first[21:]
    sv.FALLBACK_PATH.write_text(json.dumps(data), encoding="utf-8")
    assert get_secret("key") is None


def test_delete_removes_value_and_name():
    set_secret("old.token", "value")
    assert delete_secret("old.token") is True
    assert get_secret("old.token") is None
    assert secret_state("old.token") == "missing"
    assert delete_secret("old.token") is False


# ---- keyring backend ----

def test_uses_os_keyring_when_available(monkeypatch):
    backend = FakeKeyring()
    monkeypatch.setitem(sv._state, "backend", backend)
    set_secret("provider.key", "abc123")
    assert backend.rows[("MurmurAI", "provider.key")] == "abc123"
    assert get_secret("provider.key") == "abc123"
    # The local encrypted fallback was not touched.
    assert not sv.FALLBACK_PATH.exists()
    assert "Windows Credential Manager" in backend_name() or "FakeKeyring" in backend_name()


def test_keyring_discovered_via_module(monkeypatch):
    backend = FakeKeyring()
    sv._state.pop("backend", None)
    fake = types.ModuleType("keyring")
    fake.get_keyring = lambda: backend
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert set_secret("discovered", "xyz") is True
    assert backend.rows[("MurmurAI", "discovered")] == "xyz"
    assert ("MurmurAI", sv._PROBE_NAME) not in backend.rows  # probe cleaned up


# ---- status never reads values ----

def test_status_helpers_never_retrieve_secret_values(monkeypatch):
    backend = FakeKeyring(fail_get=True)
    monkeypatch.setitem(sv._state, "backend", backend)
    set_secret("a", "one")
    set_secret("b", "two")
    assert secret_state("a") == "configured"
    assert configured_secrets() == [
        {"name": "a", "state": "configured"},
        {"name": "b", "state": "configured"},
    ]
    payload = secret_status_payload()
    assert payload["backend"]
    assert "one" not in json.dumps(payload) and "two" not in json.dumps(payload)


# ---- env resolution for MCP tokens ----

def test_resolve_secret_env_replaces_references():
    set_secret("mcp.token", "real-token")
    resolved = resolve_secret_env({
        "PLAIN": "value",
        "BRACED": "${secret:mcp.token}",
        "PREFIX": "keyring:mcp.token",
    })
    assert resolved == {
        "PLAIN": "value",
        "BRACED": "real-token",
        "PREFIX": "real-token",
    }


def test_resolve_secret_env_missing_becomes_empty():
    assert resolve_secret_env({"TOKEN": "${secret:nope}"}) == {"TOKEN": ""}


def test_mcp_launch_resolves_env_without_writing_config(monkeypatch):
    import tools.mcp_manager as mm

    set_secret("notes.token", "injected")
    config = mm.ServerConfig(name="notes", command="python", env={"TOKEN": "${secret:notes.token}"})
    captured = {}

    class FakeProc:
        stdin = None
        stdout = None

    client = mm.StdioMcpClient(config)
    monkeypatch.setattr(mm, "os", types.SimpleNamespace(environ={}))
    monkeypatch.setattr(mm.subprocess, "Popen", lambda *a, **kw: captured.update(kw) or FakeProc())
    monkeypatch.setattr(client, "request", lambda *a, **kw: {})
    monkeypatch.setattr(client, "notify", lambda *a, **kw: None)
    monkeypatch.setattr(client, "_read_loop", lambda: None)
    client.start()
    assert captured["env"]["TOKEN"] == "injected"


# ---- tools and voice commands never speak values ----

def test_set_secret_reference_reply_hides_value():
    reply = set_secret_reference("api.key", "SUPER_SECRET_VALUE")
    assert "SUPER_SECRET_VALUE" not in reply
    assert "Stored api.key" in reply
    assert "won't repeat" in reply


def test_list_configured_secrets_reply_hides_values():
    set_secret("first", "one")
    set_secret("second", "two")
    reply = list_configured_secrets()
    assert "2 secret" in reply and "first" in reply and "second" in reply
    assert "one" not in reply and "two" not in reply


def test_delete_secret_reference_requires_confirmation():
    set_secret("gone", "value")
    assert "confirm delete secret gone" in delete_secret_reference("gone").lower()
    assert secret_state("gone") == "configured"
    assert "deleted" in delete_secret_reference("gone", True).lower()
    assert secret_state("gone") == "missing"


@pytest.mark.parametrize("phrase", [
    "set secret provider.token to SUPERSECRET",
    "store my secret provider.token as SUPERSECRET",
    "remember secret provider.token is SUPERSECRET",
])
def test_voice_set_confirms_without_value(phrase, monkeypatch):
    monkeypatch.setattr(st, "_voice_reply", lambda text: text)
    reply = st.handle_voice_command(phrase)
    assert reply is not None
    assert "SUPERSECRET" not in reply
    assert "Stored provider.token" in reply
    assert get_secret("provider.token") == "SUPERSECRET"


def test_voice_list_and_delete_require_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(st, "_voice_reply", lambda text: text)
    set_secret("voice.key", "hidden-value")
    listing = st.handle_voice_command("list configured secrets")
    assert "voice.key" in listing and "hidden-value" not in listing

    first = st.handle_voice_command("delete secret voice.key")
    assert "confirm" in first.lower() and "hidden-value" not in first
    assert secret_state("voice.key") == "configured"
    second = st.handle_voice_command("yes, confirm delete secret voice.key")
    assert "deleted" in second.lower() and "hidden-value" not in second
    assert secret_state("voice.key") == "missing"


# ---- registration / dispatch ----

def test_secret_tools_registered_in_brain():
    names = [t["function"]["name"] for t in SECRET_TOOLS]
    assert set(names) == {
        "set_secret_reference", "list_configured_secrets", "delete_secret"
    }
    brain_names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    for name in names:
        assert name in brain_names
    lowered = brain.SYSTEM_PROMPT.lower()
    assert "never speak or repeat the value" in lowered


def test_secret_tool_schemas_valid():
    for tool in SECRET_TOOLS:
        params = tool["function"]["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        assert isinstance(params["required"], list)


def test_dispatch_routes_secret_tools(monkeypatch):
    seen = []
    monkeypatch.setattr(sv, "set_secret_reference", lambda n, v: seen.append(("set", n, v)) or "set")
    monkeypatch.setattr(sv, "list_configured_secrets", lambda: seen.append(("list",)) or "list")
    monkeypatch.setattr(sv, "delete_secret_reference", lambda n, c: seen.append(("del", n, c)) or "del")

    assert os_tools.dispatch_tool("set_secret_reference", {"name": "n", "value": "v"}, None) == "set"
    assert os_tools.dispatch_tool("list_configured_secrets", {}, None) == "list"
    assert os_tools.dispatch_tool("delete_secret", {"name": "n", "confirm": True}, None) == "del"
    assert seen == [("set", "n", "v"), ("list",), ("del", "n", True)]


def test_audit_log_never_contains_secret_values(tmp_path):
    from tools.mcp_manager import audit_tool_call

    set_secret("audit.token", "AUDIT_SENTINEL")
    path = tmp_path / "tool_audit.jsonl"
    audit_tool_call(path, "srv", "tool", "approved", {"token": "AUDIT_SENTINEL"})
    dumped = path.read_text(encoding="utf-8")
    assert "AUDIT_SENTINEL" not in dumped
    assert json.loads(dumped.strip())["decision"] == "approved"


# ---- packaging ----

def test_sidecar_bundles_security_and_keyring():
    spec = (Path(__file__).resolve().parents[1] / "murmur-backend.spec").read_text(encoding="utf-8")
    assert '"security.secret_vault"' in spec
    assert '"keyring"' in spec
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"keyring>=' in pyproject
    assert '"security*"' in pyproject


# ---- diagnostics ----

def test_diagnostics_manifest_reports_secret_status_only(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(db, "MCP_CONFIG_PATH", tmp_path / "mcp_servers.json")
    monkeypatch.setattr(db, "_hardware_profile", lambda: {})
    monkeypatch.setattr(db, "_ollama_status", lambda: {})
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "_CACHE", None)

    set_secret("diag.token", "SENTINEL_DIAG_VALUE")
    manifest = db.build_manifest()
    dumped = json.dumps(manifest)
    assert "SENTINEL_DIAG_VALUE" not in dumped
    assert manifest["secrets"]["secrets"] == [
        {"name": "diag.token", "state": "configured"}
    ]
    assert manifest["secrets"]["backend"] == "encrypted local vault"
