"""Privacy-safe diagnostics bundle tests (local files only, no network)."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

import agent.brain as brain
import system.diagnostics_bundle as db
import system.settings_tools as st
import tools.os_tools as os_tools


@pytest.fixture(autouse=True)
def _isolated_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "HOME_LOG_DIR", tmp_path / "home-logs")
    monkeypatch.setattr(db, "BACKEND_LOG_DIR", tmp_path / "backend-logs")
    monkeypatch.setattr(db, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(db, "MCP_CONFIG_PATH", tmp_path / "mcp_servers.json")
    monkeypatch.setattr(db, "_speak", lambda text: None)
    yield


# ---- sanitization ----

@pytest.mark.parametrize("key", [
    "api_key", "TOKEN", "client_secret", "password", "AUTH_HEADER", "private_key",
])
def test_sensitive_keys_redacted(key):
    assert db.sanitize_value(key, "super-secret-value") == db.REDACTED


@pytest.mark.parametrize("value", [
    "/home/me/notes", "C:\\Users\\me\\Documents", "~/projects/murmur",
    "/tmp/report.pdf",
])
def test_custom_paths_redacted(value):
    assert db.sanitize_value("some_label", value) == db.REDACTED_PATH


def test_nested_structures_sanitized():
    value = db.sanitize_value("outer", {
        "token": "abc",
        "note": "hello",
        "files": ["/home/me/a.txt", {"password": "x", "ok": 1}],
    })
    assert value["token"] == db.REDACTED
    assert value["note"] == "hello"
    assert value["files"][0] == db.REDACTED_PATH
    assert value["files"][1]["password"] == db.REDACTED
    assert value["files"][1]["ok"] == 1


def test_url_query_tokens_redacted():
    result = db.sanitize_value("link", "https://example.com/api?token=abc123&page=2")
    assert "abc123" not in result
    assert "page=2" in result


def test_plain_values_preserved():
    assert db.sanitize_value("speech_rate", 1.25) == 1.25
    assert db.sanitize_value("voice", "af_heart") == "af_heart"


# ---- log collection ----

def test_collect_recent_logs_only(tmp_path):
    home = db.HOME_LOG_DIR
    backend = db.BACKEND_LOG_DIR
    home.mkdir(parents=True)
    backend.mkdir(parents=True)

    recent = home / "session.log"
    recent.write_text("recent log", encoding="utf-8")
    old = backend / "old.log"
    old.write_text("old", encoding="utf-8")
    import os

    old_time = time.time() - 20 * 86400
    os.utime(old, (old_time, old_time))

    collected = db.collect_log_files()
    assert [p.name for p in collected] == ["session.log"]


def test_collect_logs_excludes_verbatim_screen_content(tmp_path):
    backend = tmp_path / "backend-logs"
    backend.mkdir()
    (backend / "session.log").write_text("ok", encoding="utf-8")
    (backend / "step_001.json").write_text('{"text":"password field"}', encoding="utf-8")
    describe = backend / "describe"
    describe.mkdir()
    (describe / "description.txt").write_text("on-screen text", encoding="utf-8")

    db.BACKEND_LOG_DIR = backend
    db.HOME_LOG_DIR = tmp_path / "empty-home"
    assert [p.name for p in db.collect_log_files()] == ["session.log"]


def test_collect_logs_skips_large_files(tmp_path):
    db.BACKEND_LOG_DIR.mkdir(parents=True)
    big = db.BACKEND_LOG_DIR / "huge.log"
    big.write_bytes(b"x" * (db.LOG_MAX_BYTES + 1))
    assert db.collect_log_files() == []


# ---- bundle creation ----

def test_export_creates_zip_with_sanitized_manifest(monkeypatch, tmp_path):
    log_dir = db.HOME_LOG_DIR
    log_dir.mkdir(parents=True)
    (log_dir / "session.log").write_text("something happened", encoding="utf-8")
    monkeypatch.setattr(db, "build_manifest", lambda: {
        "config": db.sanitize_config({"api_key": "secret", "voice": "af_heart", "notes_location": "/home/me/notes"}),
        "ollama": db.sanitize_config({"running": True, "install_path": "/usr/bin/ollama"}),
        "created_at": "now",
    })
    spoken = []
    monkeypatch.setattr(db, "_speak", lambda text: spoken.append(text))

    out = tmp_path / "out"
    path = db.export_diagnostics(out, speak=True)

    assert Path(path).is_file() and path.endswith(".zip")
    assert spoken and path in spoken[0]
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        assert any(name.endswith("session.log") for name in names)
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["config"]["api_key"] == db.REDACTED
        assert manifest["config"]["notes_location"] == db.REDACTED_PATH
        assert manifest["config"]["voice"] == "af_heart"
        assert manifest["ollama"]["install_path"] == db.REDACTED


def test_export_without_logs_still_creates_bundle(tmp_path):
    path = db.export_diagnostics(tmp_path / "empty", speak=False)
    with zipfile.ZipFile(path) as bundle:
        assert "manifest.json" in bundle.namelist()
        assert "README.txt" in bundle.namelist()


# ---- registration / routing ----

def test_diagnostics_tool_registered():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert "export_diagnostics" in names


def test_dispatch_export_tool(monkeypatch, tmp_path):
    expected = str(tmp_path / "bundle.zip")
    monkeypatch.setattr(db, "export_diagnostics", lambda: expected)
    assert os_tools.dispatch_tool("export_diagnostics", {}, None) == expected


def test_export_voice_phrase(monkeypatch, tmp_path):
    expected = str(tmp_path / "bundle.zip")
    monkeypatch.setattr(db, "export_diagnostics", lambda speak=True: expected)
    st._CACHE = None
    assert st.handle_voice_command("Export diagnostics") == expected
    st._CACHE = None
