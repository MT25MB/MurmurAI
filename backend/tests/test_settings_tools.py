"""Voice settings, persistence and spoken diagnostics tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import agent.brain as brain
import main
import setup as app_setup
import system.settings_tools as st
import tools.os_tools as os_tools
from agent.state import SessionState


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "_CACHE", None)
    monkeypatch.setattr("audio.speaker_provider.get_speaker", lambda: None)
    yield
    monkeypatch.setattr(st, "_CACHE", None)


@pytest.fixture
def no_runtime(monkeypatch):
    """Prevent settings from touching a real main/app_state in unit tests."""
    monkeypatch.setattr(st, "apply_settings", lambda settings=None: None)


# ---- persistence ----

def test_defaults_and_persistence():
    settings = st.load_settings()
    assert settings["speech_rate"] == 1.0
    assert settings["description_verbosity"] == "concise"
    assert settings["listening_mode"] == "active"

    st.update_settings({"speech_rate": 1.4, "earcons": False})
    assert json.loads(st.CONFIG_PATH.read_text(encoding="utf-8"))["speech_rate"] == 1.4

    st._CACHE = None
    reloaded = st.load_settings()
    assert reloaded["speech_rate"] == 1.4 and reloaded["earcons"] is False


def test_invalid_values_are_clamped():
    st.save_settings({"speech_rate": 9.0, "mic_threshold": -3})
    st._CACHE = None
    settings = st.load_settings()
    assert settings["speech_rate"] == 2.0
    assert settings["mic_threshold"] == 0.0


def test_reset_defaults():
    st.update_settings({"speech_rate": 1.8})
    result = st.reset_settings()
    assert result == st.DEFAULT_SETTINGS


# ---- voice commands ----

@pytest.mark.parametrize("phrase", ["Speak faster", "Speed up your speech"])
def test_speak_faster(no_runtime, phrase):
    reply = st.handle_voice_command(phrase)
    assert reply and "faster" in reply.lower()
    assert st.load_settings()["speech_rate"] > 1.0


@pytest.mark.parametrize("phrase", ["Slow down your voice", "Speak slower"])
def test_slow_down(no_runtime, phrase):
    st.update_settings({"speech_rate": 1.5})
    reply = st.handle_voice_command(phrase)
    assert reply and "slow" in reply.lower()
    assert st.load_settings()["speech_rate"] < 1.5


def test_change_voice(no_runtime):
    assert "af_bella" in st.handle_voice_command("use voice af_bella")
    assert st.load_settings()["voice"] == "af_bella"


@pytest.mark.parametrize("phrase,expected", [
    ("Turn chimes on", True),
    ("Turn chimes off", False),
    ("Disable sounds", False),
])
def test_chimes_toggle(no_runtime, phrase, expected):
    st.handle_voice_command(phrase)
    assert st.load_settings()["earcons"] is expected


def test_detailed_and_concise_descriptions(no_runtime):
    st.handle_voice_command("Switch to detailed screen descriptions")
    assert st.load_settings()["description_verbosity"] == "detailed"
    st.handle_voice_command("Use concise descriptions")
    assert st.load_settings()["description_verbosity"] == "concise"


def test_listening_modes(no_runtime, monkeypatch):
    monkeypatch.setattr(main, "app_state", type("S", (), {"listening_mode": "active"})())
    st.handle_voice_command("Switch to wake-word mode")
    assert st.load_settings()["listening_mode"] == "wake"
    assert main.app_state.listening_mode == "sleep"
    st.handle_voice_command("Switch to continuous listening")
    assert st.load_settings()["listening_mode"] == "active"


def test_mic_threshold(no_runtime):
    st.handle_voice_command("Increase mic threshold")
    assert st.load_settings()["mic_threshold"] > 0.5
    st.handle_voice_command("Decrease mic threshold")
    assert st.load_settings()["mic_threshold"] == pytest.approx(0.5)


def test_switch_vision_model(no_runtime):
    reply = st.handle_voice_command("Switch vision model to qwen3-vl")
    assert "qwen3-vl" in reply
    assert st.load_settings()["vision_model"] == "qwen3-vl"


def test_show_models(no_runtime, monkeypatch):
    monkeypatch.setattr(st, "_available_models", lambda: ["qwen2.5:7b", "qwen3-vl:7b"])
    reply = st.handle_voice_command("Show current models")
    assert "qwen2.5:7b" in reply and "qwen3-vl:7b" in reply


def test_unrelated_phrase_ignored(no_runtime):
    assert st.handle_voice_command("What time is it?") is None


# ---- diagnostics ----

def test_run_diagnostics_report(monkeypatch):
    monkeypatch.setattr(st, "_mic_signal", lambda: {"available": True, "signal": 90, "ok": True})
    monkeypatch.setattr(st, "_available_models", lambda: ["qwen2.5:7b"])
    monkeypatch.setattr(app_setup, "ollama_status", lambda: {"running": True, "installed": True})
    monkeypatch.setattr(app_setup, "permission_status", lambda: {
        "platform": "Linux", "session_type": "x11", "items": []
    })
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    result = st.run_diagnostics()
    assert result["issues"] == []
    assert "Everything looks healthy" in result["summary"]
    assert "Microphone: ok" in result["summary"]
    assert "Ollama: running" in result["summary"]


def test_diagnostics_offers_fixes(monkeypatch):
    monkeypatch.setattr(st, "_mic_signal", lambda: {"available": False, "signal": 0, "ok": False})
    monkeypatch.setattr(st, "_available_models", lambda: [])
    monkeypatch.setattr(app_setup, "ollama_status", lambda: {"running": False, "installed": False})
    monkeypatch.setattr(app_setup, "permission_status", lambda: {
        "platform": "Darwin",
        "items": [{"key": "accessibility", "label": "Accessibility", "granted": False,
                   "hint": "Enable it in System Settings."}],
    })
    for key in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(key, raising=False)

    result = st.run_diagnostics()
    assert result["issues"]
    assert "fix permissions" in result["summary"].lower()
    assert "restart ollama" in result["summary"].lower()
    assert "not running" in result["summary"]


def test_diagnostics_voice_phrase(monkeypatch):
    monkeypatch.setattr(st, "_mic_signal", lambda: {"available": True, "signal": 90, "ok": True})
    monkeypatch.setattr(st, "_available_models", lambda: ["m"])
    monkeypatch.setattr(app_setup, "ollama_status", lambda: {"running": True})
    monkeypatch.setattr(app_setup, "permission_status", lambda: {"items": []})
    reply = st.handle_voice_command("Why aren't you working?")
    assert reply and reply.startswith("Diagnostics.")


def test_fix_and_restart_helpers(monkeypatch):
    monkeypatch.setattr(app_setup, "request_accessibility_prompt", lambda: {"items": []})
    assert "opened" in st.fix_permissions().lower()

    monkeypatch.setattr(app_setup, "_ollama_binary_path", lambda: None)
    assert "not installed" in st.restart_ollama().lower()


# ---- brain registration + dispatch ----

def test_settings_tools_registered():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert {"run_diagnostics", "get_settings", "set_setting"} <= set(names)


def test_dispatch_settings_tools(monkeypatch):
    monkeypatch.setattr(st, "run_diagnostics", lambda: {"summary": "All good."})
    assert os_tools.dispatch_tool("run_diagnostics", {}, None) == "All good."
    assert "speech rate" in os_tools.dispatch_tool("get_settings", {}, None).lower()
    changed = os_tools.dispatch_tool("set_setting", {"changes": {"earcons": False}}, None)
    assert "chimes off" in changed.lower()


@pytest.mark.asyncio
async def test_settings_phrase_fast_path(monkeypatch):
    sent = []

    async def send(message):
        sent.append(message)

    assert await main._try_settings_phrase(SessionState(), send, "Speak faster") is True
    assert any(m.type == "info" for m in sent)
    assert await main._try_settings_phrase(SessionState(), send, "what time is it") is False


# ---- HTTP endpoints ----

def test_settings_http_endpoints(monkeypatch):
    monkeypatch.setattr(st, "run_diagnostics", lambda: {"summary": "Healthy."})
    client = TestClient(main.app)

    initial = client.get("/settings").json()
    assert initial["speech_rate"] == 1.0

    updated = client.post("/settings", json={"speech_rate": 1.3}).json()
    assert updated["speech_rate"] == 1.3
    assert client.get("/settings").json()["speech_rate"] == 1.3

    assert client.get("/diagnostics").json()["summary"] == "Healthy."
    assert client.post("/settings/reset").json()["speech_rate"] == 1.0
