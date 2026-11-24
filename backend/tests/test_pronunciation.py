"""Pronunciation normalizer, voice tool and profile switcher tests."""

from __future__ import annotations

import json
import time

import pytest

import agent.brain as brain
import audio.pronunciation as pron
import audio.speaker as speaker
import audio.voice_profiles as profiles
import system.settings_tools as st
import tools.os_tools as os_tools


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pron, "PRONUNCIATIONS_PATH", tmp_path / "pronunciations.json")
    monkeypatch.setattr(pron, "_CACHE", None)
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "_CACHE", None)
    monkeypatch.setattr("audio.speaker_provider.get_speaker", lambda: None)
    yield
    pron._CACHE = None
    st._CACHE = None


# ---- defaults + normalization ----

@pytest.mark.parametrize("term,spoken", [
    ("GUI", "gooey"), ("sudo", "soo-doo"), ("Ctrl", "Control"),
    ("bpy", "B-P-Y"), ("VRAM", "V-ram"),
])
def test_default_pronunciations(term, spoken):
    assert pron.load_dictionary()[term] == spoken


def test_normalize_case_insensitive_and_preserves_other_words():
    value = pron.normalize("Open the GUI, then Ctrl+C and bpy. Weather is nice.")
    assert "gooey" in value and "Control" in value and "B-P-Y" in value
    assert "Weather is nice" in value


def test_normalize_longest_term_first():
    value = pron.normalize("Use HTTPS not HTTP")
    assert value == "Use H-T-T-P-S not H-T-T-P"


def test_normalize_empty_and_custom_dictionary():
    assert pron.normalize("") == ""
    assert pron.normalize("nod", {"nod": "node"}) == "node"


# ---- persistence / voice tool ----

def test_add_pronunciation_persists_and_overrides():
    reply = pron.add_pronunciation("nvda", "N-V-D-A")
    assert "N-V-D-A" in reply
    assert json.loads(pron.PRONUNCIATIONS_PATH.read_text(encoding="utf-8"))["NVDA"] == "N-V-D-A"
    assert pron.normalize("Use NVDA now") == "Use N-V-D-A now"


def test_add_pronunciation_validates():
    assert "need both" in pron.add_pronunciation("", "").lower()


def test_reset_pronunciations():
    pron.add_pronunciation("GUI", "different")
    result = pron.reset_pronunciations()
    assert result["GUI"] == "gooey"


def test_speaker_normalizes_before_tts(monkeypatch, fake_sounddevice):
    captured = []
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    monkeypatch.setattr(s, "_resolve_engine", lambda: "kokoro")
    monkeypatch.setattr(s, "_speak_kokoro", lambda text: captured.append(text))
    s.speak("Open the GUI with Ctrl")
    for _ in range(100):
        if captured:
            break
        time.sleep(0.01)
    assert captured == ["Open the gooey with Control"]


# ---- brain / voice routing ----

def test_pronunciation_tool_registered():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert "add_pronunciation" in names


def test_dispatch_pronunciation_tool():
    result = os_tools.dispatch_tool(
        "add_pronunciation", {"word": "yaml", "spoken_as": "Y-A-M-L"}, None
    )
    assert "Y-A-M-L" in result
    assert pron.load_dictionary()["YAML"] == "Y-A-M-L"


def test_voice_pronounce_phrase():
    reply = st.handle_voice_command("Pronounce 'nvda' as 'N-V-D-A'")
    assert reply and "N-V-D-A" in reply
    assert pron.load_dictionary()["NVDA"] == "N-V-D-A"


# ---- voice profiles ----

def test_profile_settings():
    assert profiles.profile_settings("clear")["speech_rate"] == 0.9
    assert profiles.profile_settings("my fast profile")["voice"] == "af_bella"
    assert profiles.profile_settings("unknown") is None


def test_apply_profile_updates_settings(monkeypatch):
    monkeypatch.setattr(st, "apply_settings", lambda settings=None: None)
    reply = profiles.apply_voice_profile("clear")
    assert "clear" in reply.lower()
    settings = st.load_settings()
    assert settings["voice_profile"] == "clear"
    assert settings["screen_reader_friendly"] is True
    assert settings["earcons"] is False


def test_voice_profile_registered_and_routed(monkeypatch):
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert "set_voice_profile" in names
    monkeypatch.setattr(st, "apply_settings", lambda settings=None: None)
    result = os_tools.dispatch_tool("set_voice_profile", {"profile": "fast"}, None)
    assert "fast" in result.lower()


def test_voice_profile_phrase(monkeypatch):
    monkeypatch.setattr(st, "apply_settings", lambda settings=None: None)
    reply = st.handle_voice_command("Switch to my clear voice profile")
    assert reply and "clear" in reply.lower()


def test_natural_profile_uses_the_best_local_voice():
    values = profiles.profile_settings("natural")
    assert values["voice"] == "af_heart"
    assert values["speech_rate"] == 0.95
    assert values["earcons"] is False


def test_high_quality_voice_phrase_selects_natural(monkeypatch):
    monkeypatch.setattr(st, "apply_settings", lambda settings=None: None)
    reply = st.handle_voice_command("Use your high quality voice")
    assert reply and "natural" in reply.lower()
    assert st.load_settings()["voice_profile"] == "natural"
