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


def test_invalid_numeric_settings_fall_back_to_defaults():
    saved = st.update_settings({"speech_rate": "abc", "mic_threshold": None})
    assert saved["speech_rate"] == 1.0
    assert saved["mic_threshold"] == 0.5


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


def test_model_settings_are_hardware_gated(no_runtime, monkeypatch, tmp_path):
    import system.profiler as profiler

    monkeypatch.setattr(profiler, "PROFILE_PATH", tmp_path / "hardware_profile.json")
    profiler.save_profile(profiler.HardwareProfile(
        total_ram_gb=8, vram_gb=0, tier="light", compute_backend="CPU"
    ))

    with pytest.raises(ValueError, match="cannot run"):
        st.update_settings({"chat_model": "qwen3.5:9b"})
    with pytest.raises(ValueError, match="Unknown model"):
        st.update_settings({"vision_model": "not-a-model"})

    saved = st.update_settings({"chat_model": "qwen2.5:3b"})
    assert saved["chat_model"] == "qwen2.5:3b"


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
    # Settings only persists the choice; the live transition belongs to main.
    st.handle_voice_command("Switch to wake-word mode")
    assert st.load_settings()["listening_mode"] == "wake"
    st.handle_voice_command("Switch to continuous listening")
    assert st.load_settings()["listening_mode"] == "active"


@pytest.mark.asyncio
async def test_spoken_mode_change_updates_runtime(monkeypatch):
    from types import SimpleNamespace

    slept = []
    monkeypatch.setattr(
        main, "app_state", SimpleNamespace(listening_mode="active", speaker=None)
    )

    async def fake_sleep(session, send):
        slept.append(True)
        main.app_state.listening_mode = "sleep"

    monkeypatch.setattr(main, "enter_sleep", fake_sleep)
    sent = []

    async def send(message):
        sent.append(message)

    handled = await main._try_settings_phrase(SessionState(), send, "Switch to wake-word mode")
    assert handled is True
    assert slept == [True]


def test_mic_threshold(no_runtime):
    st.handle_voice_command("Increase mic threshold")
    assert st.load_settings()["mic_threshold"] > 0.5
    st.handle_voice_command("Decrease mic threshold")
    assert st.load_settings()["mic_threshold"] == pytest.approx(0.5)


def test_switch_vision_model(no_runtime, monkeypatch, tmp_path):
    import system.profiler as profiler

    monkeypatch.setattr(profiler, "PROFILE_PATH", tmp_path / "hardware_profile.json")
    profiler.save_profile(profiler.HardwareProfile(
        total_ram_gb=32, vram_gb=0, tier="high", compute_backend="CPU"
    ))
    reply = st.handle_voice_command("Switch vision model to qwen2.5vl:7b")
    assert "qwen2.5vl:7b" in reply
    assert st.load_settings()["vision_model"] == "qwen2.5vl:7b"


def test_model_upgrade_requires_supported_hardware(no_runtime, monkeypatch, tmp_path):
    import system.profiler as profiler

    monkeypatch.setattr(
        profiler, "PROFILE_PATH", tmp_path / "hardware_profile.json"
    )
    profiler.save_profile(profiler.HardwareProfile(
        total_ram_gb=8, vram_gb=0, tier="light", compute_backend="CPU"
    ))
    st._CACHE = None

    reply = st.handle_voice_command("Use qwen3.5:9b for screen")
    assert "can't use" in reply.lower()
    assert "need" in reply.lower()
    assert st.load_settings()["vision_model"] != "qwen3.5:9b"

    reply = st.handle_voice_command("Use qwen3.5:4b for screen")
    assert "qwen3.5:4b is now the vision model" in reply.lower()
    assert st.load_settings()["vision_model"] == "qwen3.5:4b"


def test_select_unified_model_sets_both_roles(no_runtime, monkeypatch, tmp_path):
    import system.profiler as profiler

    monkeypatch.setattr(profiler, "PROFILE_PATH", tmp_path / "hardware_profile.json")
    profiler.save_profile(profiler.HardwareProfile(
        total_ram_gb=32, vram_gb=0, tier="high", compute_backend="CPU"
    ))
    reply = st.select_model("qwen3.5:9b", "both")
    assert "both chat and screen" in reply.lower()
    settings = st.load_settings()
    assert settings["chat_model"] == "qwen3.5:9b"
    assert settings["vision_model"] == "qwen3.5:9b"


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


def test_diagnostics_does_not_warn_about_display_on_windows(monkeypatch):
    monkeypatch.setattr(st.platform, "system", lambda: "Windows")
    monkeypatch.setattr(st, "_mic_signal", lambda: {"available": True, "signal": 90, "ok": True})
    monkeypatch.setattr(st, "_available_models", lambda: ["qwen2.5:7b"])
    monkeypatch.setattr(app_setup, "ollama_status", lambda: {"running": True, "installed": True})
    monkeypatch.setattr(app_setup, "permission_status", lambda: {"platform": "Windows", "items": []})
    for key in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(key, raising=False)

    result = st.run_diagnostics()
    assert result["issues"] == []
    assert "Display: native" in result["summary"]
    assert "Computer control:" in result["summary"]


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


def test_autostart_voice_toggle_is_opt_in_and_emits(monkeypatch):
    from tools.event_bus import tool_bus

    emitted = []
    monkeypatch.setattr(tool_bus, "emit", lambda message: emitted.append(message))

    reply = st.handle_voice_command("Start Murmur when I log in")
    assert reply and "log in" in reply.lower()
    assert st.load_settings()["autostart_enabled"] is True
    assert any(getattr(m, "type", None) == "autostart" and m.enabled for m in emitted)

    emitted.clear()
    reply = st.handle_voice_command("Disable startup launch")
    assert reply and "will not start" in reply.lower()
    assert st.load_settings()["autostart_enabled"] is False
    assert any(getattr(m, "type", None) == "autostart" and not m.enabled for m in emitted)


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
