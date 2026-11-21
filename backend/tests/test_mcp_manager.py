"""MCP stdio client tests: discovery, execution, confirmation gating and reload.

A tiny real JSON-RPC server is started as a local subprocess so the stdio
transport, handshake and tools/call path are all exercised without network.
"""

from __future__ import annotations

import json
import sys

import pytest

import agent.brain as brain
import tools.os_tools as os_tools
from tools.mcp_manager import (
    MANAGEMENT_TOOL_NAMES,
    McpManager,
    ServerConfig,
    StdioMcpClient,
    tool_risk,
)

MOCK_SERVER = r'''
import json, sys
TOOLS = [
  {"name": "read_note", "description": "Read a local note by name",
   "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
  {"name": "write_note", "description": "Write or overwrite a local note",
   "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "text": {"type": "string"}}, "required": ["name", "text"]}},
]
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: msg = json.loads(line)
    except Exception: continue
    if "id" not in msg: continue
    method = msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "mock", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "called " + msg["params"]["name"]}], "isError": False}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n")
    sys.stdout.flush()
'''


class FakeBus:
    def __init__(self, approved: bool = True):
        self.approved = approved
        self.calls: list[tuple] = []

    def request_confirmation(self, description, command, timeout=180):
        self.calls.append((description, command, timeout))
        return self.approved


def write_config(path, servers):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _restore_brain_tools():
    original = list(brain.ALL_TOOLS)
    yield
    brain.ALL_TOOLS[:] = original


@pytest.fixture
def config_path(tmp_path):
    return write_config(tmp_path / "mcp_servers.json", {
        "mock": {
            "command": sys.executable,
            "args": ["-c", MOCK_SERVER],
            "env": {},
            "allowlist": ["read_note"],
        }
    })


@pytest.fixture
def manager(config_path):
    mgr = McpManager(config_path=config_path, bus=FakeBus())
    yield mgr
    mgr.shutdown()


# ---- risk classification ----

@pytest.mark.parametrize("name,expected", [
    ("read_note", "low"),
    ("write_note", "high"),
    ("fetch_url", "high"),
    ("run_shell", "high"),
    ("delete_file", "high"),
    ("search_notes", "low"),
])
def test_tool_risk(name, expected):
    assert tool_risk(name, "") == expected


# ---- config ----

def test_load_config_validates(tmp_path):
    path = write_config(tmp_path / "cfg.json", {
        "local": {"command": "python", "args": "-m mod", "env": {"A": "1"}}
    })
    with pytest.raises(Exception, match="invalid args/env"):
        McpManager(config_path=path).load_config()


def test_missing_config_is_empty(tmp_path):
    mgr = McpManager(config_path=tmp_path / "missing.json", bus=FakeBus())
    assert mgr.load_config() == {}
    assert mgr.reload()["tools"] == []


def test_example_config_created(tmp_path):
    mgr = McpManager(config_path=tmp_path / "mcp.json", bus=FakeBus())
    example = mgr.ensure_example_config()
    assert example.exists() and "servers" in example.read_text(encoding="utf-8")


# ---- discovery ----

def test_discovery_registers_tools_in_brain(manager):
    status = manager.reload()
    assert [s["name"] for s in status["servers"]] == ["mock"]
    tool_names = [t["name"] for t in status["tools"]]
    assert set(tool_names) == {"mcp__mock__read_note", "mcp__mock__write_note"}

    brain_names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    for name in tool_names + list(MANAGEMENT_TOOL_NAMES):
        assert name in brain_names

    schema = next(t for t in brain.ALL_TOOLS if t["function"]["name"] == "mcp__mock__read_note")
    params = schema["function"]["parameters"]
    assert params["type"] == "object" and "name" in params["properties"]
    assert params["required"] == ["name"]


def test_reload_is_idempotent(manager):
    manager.reload()
    first = [t["function"]["name"] for t in brain.ALL_TOOLS]
    manager.reload()
    second = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert len(first) == len(second) and len(second) == len(set(second))


def test_broken_server_is_nonfatal(config_path, tmp_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["servers"]["broken"] = {
        "command": "definitely-not-a-real-binary-mcp",
        "args": [],
        "env": {},
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    mgr = McpManager(config_path=config_path, bus=FakeBus())
    try:
        status = mgr.reload()
        assert status["errors"] and "broken" in status["errors"][0]
        assert len(status["tools"]) == 2  # healthy server still loaded
        assert "could not be reached" in mgr.spoken_status().lower()
    finally:
        mgr.shutdown()


# ---- execution + gating ----

def test_low_risk_tool_runs_without_confirmation(manager):
    manager.reload()
    result = manager.call_tool("mcp__mock__read_note", {"name": "todo"})
    assert result == "called read_note"
    assert manager.bus.calls == []


def test_high_risk_tool_is_gated(manager):
    manager.reload()
    manager.bus.approved = False
    result = manager.call_tool("mcp__mock__write_note", {"name": "x", "text": "y"})
    assert "cancelled" in result.lower()
    assert len(manager.bus.calls) == 1
    assert "write" in manager.bus.calls[0][0].lower()


def test_approved_high_risk_tool_runs(manager):
    manager.reload()
    manager.bus.approved = True
    result = manager.call_tool("mcp__mock__write_note", {"name": "x", "text": "y"})
    assert result == "called write_note"
    assert len(manager.bus.calls) == 1


def test_allowlisted_tool_skips_confirmation(tmp_path):
    path = write_config(tmp_path / "mcp.json", {
        "mock": {
            "command": sys.executable,
            "args": ["-c", MOCK_SERVER],
            "env": {},
            "allowlist": ["read_note", "write_note"],
        }
    })
    bus = FakeBus()
    mgr = McpManager(config_path=path, bus=bus)
    try:
        mgr.reload()
        result = mgr.call_tool("mcp__mock__write_note", {"name": "x", "text": "y"})
        assert result == "called write_note" and bus.calls == []
    finally:
        mgr.shutdown()


def test_unknown_tool_is_actionable(manager):
    manager.reload()
    assert "unknown" in manager.call_tool("mcp__mock__missing", {}).lower()


# ---- routing / voice ----

def test_dispatch_routes_plugin_tools(manager, monkeypatch):
    import tools.mcp_manager as mgr_module

    manager.reload()
    monkeypatch.setattr(mgr_module, "manager", manager)
    result = os_tools.dispatch_tool(
        "mcp__mock__read_note", {"name": "todo"}, None
    )
    assert result == "called read_note"
    assert "mcp" in mgr_module.list_plugins().lower()
    assert "servers connected" in mgr_module.reload_plugins()["summary"].lower()


@pytest.mark.asyncio
async def test_plugin_voice_phrases(manager, monkeypatch):
    import main
    import tools.mcp_manager as mgr_module

    manager.reload()
    monkeypatch.setattr(mgr_module, "manager", manager)

    async def speak(session, send, text):
        pass

    sent = []

    async def send(message):
        sent.append(message)

    from agent.state import SessionState

    assert await main._try_plugin_phrase(SessionState(), send, "What plugins or MCP tools are active?") is True
    info = [m for m in sent if m.type == "info"]
    assert info and "mcp" in info[-1].text.lower()

    before = len(sent)
    assert await main._try_plugin_phrase(SessionState(), send, "Reload my plugins") is True
    assert len(sent) > before

    assert await main._try_plugin_phrase(SessionState(), send, "What time is it?") is False
