"""Regression tests for confirmed security audit findings.

No real shell commands, network calls or OS APIs are used.
"""

from __future__ import annotations

import urllib.parse
import urllib.request

import tools.os_tools as os_tools
from tools.safety import SafetyGate


class TestAppleScriptInjection:
    def test_window_names_are_escaped_before_embedding(self):
        from tools.window_tools import _as_applescript_string

        evil = 'foo" & do shell script "touch /tmp/pwned'
        escaped = _as_applescript_string(evil)
        assert '"' not in escaped.replace('\\"', "")
        assert escaped.startswith('foo\\"')
        assert "\\" in escaped


class TestRecipeRedirects:
    def test_redirect_handler_refuses_link_local_and_http(self):
        from tools.tool_recipes import _ValidatingRedirect

        handler = _ValidatingRedirect(("api.allowed.example",))

        req = urllib.request.Request("https://api.allowed.example/lookup?q=1", method="GET")
        for target in (
            "http://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://evil.example/x",
            "http://api.allowed.example/x",
        ):
            assert handler.redirect_request(req, None, 302, "Found", {}, target) is None

        same_host = handler.redirect_request(
            req, None, 302, "Found", {}, "https://api.allowed.example/next"
        )
        assert same_host is not None


class TestShellSafetyBlacklist:
    def test_overwrite_and_move_forms_require_confirmation(self):
        gate = SafetyGate()
        for command in (
            "copy /Y C:\\a.txt C:\\b.txt",
            'powershell -NoProfile -Command "Set-Content -Path x -Value y"',
            "Move-Item C:\\a C:\\b -Force",
            "robocopy C:\\a C:\\b /MIR",
            "git clean -fdx",
        ):
            assert gate.shell_requires_confirmation(command) is True, command
        assert gate.shell_requires_confirmation("dir C:\\") is False


class TestSecretDeletionAuthorization:
    def test_model_supplied_confirm_cannot_delete_a_secret(self, monkeypatch):
        import security.secret_vault as vault
        from tools.event_bus import tool_bus

        approvals = []
        deleted = []
        monkeypatch.setattr(
            tool_bus, "request_confirmation",
            lambda description, command, timeout=180.0: (
                approvals.append((description, command)) or False
            ),
        )
        monkeypatch.setattr(
            vault, "delete_secret_reference",
            lambda name, confirm=False: (deleted.append((name, confirm)) or "ok"),
        )

        result = os_tools.dispatch_tool(
            "delete_secret", {"name": "KEY", "confirm": True}, SafetyGate()
        )

        assert approvals, "the model's confirm flag must trigger a real user gate"
        # The vault is still consulted, but only with an explicit denial.
        assert deleted == [("KEY", False)]
        assert "deleted" not in result.lower()
