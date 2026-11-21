"""Safety gate: destructive shell/file detection and confirmation gating."""

from __future__ import annotations

import pytest

from tools.safety import SafetyGate, is_destructive


@pytest.mark.parametrize(
    "command",
    ["rm -rf /", "del C:\\file.txt /F", "format C:", "sudo rm x",
     "taskkill /F /IM app.exe", "shutdown /s"],
)
def test_destructive_shell_requires_confirmation(command):
    gate = SafetyGate()
    assert gate.shell_requires_confirmation(command)
    decision = gate.decide_shell(command)
    assert decision.requires_confirmation and not decision.allowed


@pytest.mark.parametrize("command", ["dir", "echo hello", "python script.py", "ls -la"])
def test_safe_shell_allowed(command):
    gate = SafetyGate()
    assert not gate.shell_requires_confirmation(command)
    assert gate.decide_shell(command).allowed


def test_destructive_file_ops_require_confirmation():
    gate = SafetyGate()
    for op in ("delete", "remove", "write", "overwrite"):
        assert gate.file_operation_requires_confirmation(op, "/tmp/x")
    assert not gate.file_operation_requires_confirmation("read", "/tmp/x")


def test_run_shell_denied_calls_callback_and_does_not_execute(deny_confirm, monkeypatch):
    import tools.safety as safety

    called = {"count": 0}

    def boom(cmd, **kwargs):
        called["count"] += 1
        raise AssertionError("must not execute")

    monkeypatch.setattr(safety.subprocess, "run", boom)
    gate = SafetyGate(confirm_callback=deny_confirm)
    result = gate.run_shell("rm -rf /")
    assert "cancelled" in result.lower()
    assert called["count"] == 0
    assert gate.audit[-1]["decision"] == "denied"


def test_run_shell_no_callback_blocks_destructive():
    gate = SafetyGate(confirm_callback=None)
    result = gate.run_shell("rm -rf /")
    assert "confirmation required" in result.lower()


def test_run_shell_safe_executes_when_mock(noop_confirm, monkeypatch):
    import tools.safety as safety

    monkeypatch.setattr(
        safety.subprocess, "run",
        lambda cmd, **k: SimpleNamespace(returncode=0, stdout="safe output", stderr=""),
    )
    gate = SafetyGate(confirm_callback=noop_confirm)
    assert "safe output" in gate.run_shell("echo safe")


def test_is_destructive_convenience():
    assert is_destructive(command="rm -rf /")
    assert is_destructive(operation="delete", path="/tmp/x")
    assert not is_destructive(command="echo hi")


# SimpleNamespace import kept local-safe
from types import SimpleNamespace  # noqa: E402
