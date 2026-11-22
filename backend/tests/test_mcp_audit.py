"""MCP tool decisions are audited without payloads and idle servers stop."""

from __future__ import annotations

import json
import sys
import time

import pytest

import agent.brain as brain
from test_mcp_manager import MOCK_SERVER, FakeBus, write_config
from tools.mcp_manager import McpManager, audit_tool_call


@pytest.fixture(autouse=True)
def _restore_brain_tools():
    original = list(brain.ALL_TOOLS)
    yield
    brain.ALL_TOOLS[:] = original


@pytest.fixture
def manager(tmp_path):
    config = write_config(tmp_path / "mcp.json", {
        "mock": {
            "command": sys.executable,
            "args": ["-c", MOCK_SERVER],
            "env": {},
            "allowlist": ["read_note"],
        }
    })
    mgr = McpManager(config_path=config, bus=FakeBus())
    yield mgr
    mgr.shutdown()


def test_audit_line_has_no_tool_arguments(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit_tool_call(
        path,
        "notes",
        "write_note",
        "denied",
        {"text": "SUPER_SECRET_PAYLOAD", "name": "private.txt"},
    )

    raw = path.read_text(encoding="utf-8")
    assert "SUPER_SECRET_PAYLOAD" not in raw
    assert "private.txt" not in raw
    row = json.loads(raw.strip())
    assert row["server"] == "notes"
    assert row["tool"] == "write_note"
    assert row["decision"] == "denied"
    assert "ts" in row


def test_manager_audits_approved_and_denied_calls(tmp_path):
    config = write_config(tmp_path / "mcp.json", {
        "mock": {
            "command": sys.executable,
            "args": ["-c", MOCK_SERVER],
            "env": {},
            "allowlist": ["read_note"],
        }
    })
    audit = tmp_path / "audit.jsonl"
    manager = McpManager(config_path=config, bus=FakeBus(approved=True), audit_path=audit)
    try:
        manager.reload()
        manager.call_tool("mcp__mock__read_note", {"name": "todo"})
        manager.bus.approved = False
        manager.call_tool("mcp__mock__write_note", {"name": "x", "text": "SECRET"})
    finally:
        manager.shutdown()

    rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    decisions = [(r["tool"], r["decision"]) for r in rows]
    assert ("mcp__mock__read_note", "approved") in decisions
    assert ("mcp__mock__write_note", "denied") in decisions
    assert "SECRET" not in audit.read_text(encoding="utf-8")


def test_idle_mcp_server_is_closed(manager):
    manager.reload()
    client = manager._clients["mock"]
    closed: list[bool] = []
    client.close = lambda: closed.append(True)

    manager._last_used["mock"] = time.monotonic() - 1200
    manager._close_idle()

    assert "mock" not in manager._clients
    assert closed == [True]


def test_recently_used_mcp_server_stays_connected(manager):
    manager.reload()
    manager._last_used["mock"] = time.monotonic()
    manager._close_idle()
    assert "mock" in manager._clients
