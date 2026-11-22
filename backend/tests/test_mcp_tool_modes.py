"""MCP tool modes: off blocks, ask forces a prompt, always skips the gate."""

from __future__ import annotations

import sys

import pytest

import agent.brain as brain
from test_mcp_manager import MOCK_SERVER, FakeBus, write_config
from tools.mcp_manager import McpManager


@pytest.fixture(autouse=True)
def _restore_brain_tools():
    original = list(brain.ALL_TOOLS)
    yield
    brain.ALL_TOOLS[:] = original


def make_manager(tmp_path, modes, approved=True):
    config = write_config(tmp_path / "mcp.json", {
        "mock": {
            "command": sys.executable,
            "args": ["-c", MOCK_SERVER],
            "env": {},
            "allowlist": ["read_note", "write_note"],
            "tool_modes": modes,
        }
    })
    return McpManager(config_path=config, bus=FakeBus(approved=approved))


def test_off_tool_is_blocked_without_confirmation(tmp_path):
    manager = make_manager(tmp_path, {"read_note": "off"})
    try:
        manager.reload()
        result = manager.call_tool("mcp__mock__read_note", {"name": "x"})
        assert "off" in result.lower()
        assert manager.bus.calls == []
    finally:
        manager.shutdown()


def test_ask_mode_forces_confirmation_even_for_allowlisted_tool(tmp_path):
    manager = make_manager(tmp_path, {"read_note": "ask"}, approved=False)
    try:
        manager.reload()
        result = manager.call_tool("mcp__mock__read_note", {"name": "x"})
        assert "cancelled" in result.lower()
        assert len(manager.bus.calls) == 1
    finally:
        manager.shutdown()


def test_always_mode_skips_confirmation_for_risky_tool(tmp_path):
    manager = make_manager(tmp_path, {"write_note": "always"}, approved=False)
    try:
        # Keep the tool risky by removing it from the risk allowlist.
        import json
        path = tmp_path / "mcp.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["servers"]["mock"]["allowlist"] = ["read_note"]
        path.write_text(json.dumps(data), encoding="utf-8")
        manager.reload()
        result = manager.call_tool("mcp__mock__write_note", {"name": "x", "text": "y"})
        assert result == "called write_note"
        assert manager.bus.calls == []
    finally:
        manager.shutdown()


def test_unknown_mode_is_ignored(tmp_path):
    manager = make_manager(tmp_path, {"write_note": "banana"})
    try:
        manager.reload()
        result = manager.call_tool("mcp__mock__write_note", {"name": "x", "text": "y"})
        assert result == "called write_note"
    finally:
        manager.shutdown()
