"""Spatial earcon math, chimes, mute state and vision integration."""

from __future__ import annotations

import numpy as np
import pytest

import agent.vision_agent as va
import audio.earcons as earcons
import system.settings_tools as st


@pytest.fixture(autouse=True)
def _reset_cues():
    earcons.set_enabled(True)
    yield
    earcons.set_enabled(True)


# ---- coordinate math ----

@pytest.mark.parametrize("value,expected", [
    (0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (500.0, 0.5), (-2, 0.0), (2000, 1.0),
])
def test_normalize_coordinate(value, expected):
    assert earcons.normalize_coordinate(value) == pytest.approx(expected)


def test_normalize_invalid_value_defaults_center():
    assert earcons.normalize_coordinate("nope") == 0.5


def test_panning_left_center_right():
    left_l, right_l, _ = earcons.pan_and_pitch(0.0, 0.5)
    assert left_l > right_l and right_l == pytest.approx(0.0)

    left_c, right_c, _ = earcons.pan_and_pitch(0.5, 0.5)
    assert left_c == pytest.approx(right_c)

    left_r, right_r, _ = earcons.pan_and_pitch(1.0, 0.5)
    assert right_r > left_r and left_r == pytest.approx(0.0)


def test_pitch_higher_at_top_lower_at_bottom():
    _, _, top = earcons.pan_and_pitch(0.5, 0.0)
    _, _, middle = earcons.pan_and_pitch(0.5, 0.5)
    _, _, bottom = earcons.pan_and_pitch(0.5, 1.0)
    assert top > middle > bottom
    assert top > 1.0 and bottom < 1.0 and middle == pytest.approx(1.0)


# ---- synthesis ----

def test_render_spatial_cue_is_stereo_and_panned():
    left = earcons.render_spatial_cue(0.0, 0.5)
    right = earcons.render_spatial_cue(1.0, 0.5)
    assert left.ndim == 2 and left.shape[1] == 2
    assert np.abs(left[:, 0]).sum() > np.abs(left[:, 1]).sum()
    assert np.abs(right[:, 1]).sum() > np.abs(right[:, 0]).sum()


def test_render_spatial_cue_fades_edges():
    cue = earcons.render_spatial_cue(0.5, 0.5)
    assert abs(float(cue[0, 0])) < 0.01
    assert abs(float(cue[-1, 0])) < 0.01


def test_render_chimes_distinct_and_known():
    for name in ("wake_up", "sleep", "action_success", "confirmation_needed", "error_recovery"):
        audio = earcons.render_chime(name)
        assert audio is not None and audio.ndim == 1 and len(audio) > 0
    assert earcons.render_chime("does_not_exist") is None
    assert not np.array_equal(
        earcons.render_chime("wake_up"), earcons.render_chime("error_recovery")
    )


# ---- mute / toggle ----

def test_mute_toggle_state():
    assert earcons.set_enabled(False) is False
    assert earcons.is_enabled() is False
    assert earcons.set_enabled(True) is True
    assert earcons.is_enabled() is True


def test_mute_prevents_playback(monkeypatch):
    played = []
    fake = type("S", (), {
        "play": staticmethod(lambda audio, samplerate, blocking: played.append(audio))
    })()
    monkeypatch.setattr(earcons, "sd", fake)
    audio = earcons.render_spatial_cue(0.5, 0.5)

    earcons.set_enabled(False)
    earcons._play(audio, earcons.SAMPLE_RATE)
    assert played == []

    earcons.set_enabled(True)
    earcons._play(audio, earcons.SAMPLE_RATE)
    assert len(played) == 1


def test_settings_voice_toggle(monkeypatch):
    monkeypatch.setattr(st, "apply_settings", lambda settings=None: None)
    st._CACHE = None
    reply = st.handle_voice_command("Turn spatial audio cues off")
    assert reply and "off" in reply.lower()
    assert st.load_settings()["spatial_audio_cues"] is False
    st.handle_voice_command("Turn spatial audio cues on")
    assert st.load_settings()["spatial_audio_cues"] is True
    st._CACHE = None


# ---- vision integration ----

def test_click_triggers_spatial_cue(monkeypatch):
    called = []
    monkeypatch.setattr(va, "pyautogui", type("P", (), {"click": staticmethod(lambda x, y: None)})())
    monkeypatch.setattr(va.ScreenController, "_action_cue", lambda self, x, y: called.append((x, y)))

    controller = object.__new__(va.ScreenController)
    controller._width, controller._height = 1920, 1080
    controller._left, controller._top = 0, 0
    controller.click(250, 750)
    assert called == [(250, 750)]


def test_action_cue_respects_setting(monkeypatch):
    monkeypatch.setattr("system.settings_tools.load_settings", lambda: {"spatial_audio_cues": False})
    called = []
    monkeypatch.setattr("audio.earcons.play_spatial_cue", lambda x, y: called.append((x, y)))
    va.ScreenController._action_cue(500, 500)
    assert called == []

    monkeypatch.setattr("system.settings_tools.load_settings", lambda: {"spatial_audio_cues": True})
    va.ScreenController._action_cue(500, 500)
    assert called == [(500, 500)]
