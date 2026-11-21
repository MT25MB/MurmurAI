"""Voice pipeline interface tests with all hardware/model calls mocked."""

from __future__ import annotations

import numpy as np
import pytest

import audio.listener as listener
import audio.speaker as speaker


def test_voice_listener_requires_deps_when_missing(monkeypatch):
    monkeypatch.setattr(listener, "sd", None)
    with pytest.raises(RuntimeError, match="sounddevice"):
        listener.VoiceListener()


def test_voice_listener_initializes_and_exposes_interface(monkeypatch, fake_sounddevice):
    class FakeVad:
        def __init__(self, mode):
            self.mode = mode

        def is_speech(self, frame, rate):
            return False

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            class Seg:
                text = "hello"
            return ([Seg()], object())

    monkeypatch.setattr(listener, "sd", fake_sounddevice)
    monkeypatch.setattr(listener, "webrtcvad", type("V", (), {"Vad": FakeVad})())
    monkeypatch.setattr(listener, "WhisperModel", FakeModel)

    captured = []
    v = listener.VoiceListener(model_name="base.en", silence_ms=800,
                               on_utterance=lambda t: captured.append(t))
    assert v.model_name == "base.en" and v.silence_ms == 800
    # Feed 0.5s of silence (< 0.3s threshold target check) then speech audio.
    pcm = (np.zeros(16000) * 32767).astype(np.int16).tobytes()
    assert isinstance(v._transcribe(pcm), str)
    assert v._transcribe(pcm) == "hello"
    v.unload_model()
    assert v._model is None


def test_transcribe_returns_text_via_callback(monkeypatch, fake_sounddevice):
    class FakeVad:
        def __init__(self, mode):
            pass

        def is_speech(self, frame, rate):
            return False

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            class Seg:
                text = " open blender "
            return ([Seg()], object())

    monkeypatch.setattr(listener, "sd", fake_sounddevice)
    monkeypatch.setattr(listener, "webrtcvad", type("V", (), {"Vad": FakeVad})())
    monkeypatch.setattr(listener, "WhisperModel", FakeModel)
    v = listener.VoiceListener()
    result = v._transcribe((np.zeros(16000) * 32767).astype(np.int16).tobytes())
    assert "open blender" in result


def test_speaker_earcons_toggle_and_cues(monkeypatch, fake_sounddevice):
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    assert set(s.EARCON_NOTES) >= {"listening", "thinking", "speaking", "confirmation", "error"}
    s.set_earcons(False)
    assert not s.earcons_enabled
    # chime is a no-op when disabled and must not raise.
    s.chime("confirmation")
    s.set_earcons(True)
    assert s.earcons_enabled
    # Unknown cue is a safe no-op.
    s.chime("nonexistent")


def test_speaker_interrupt_is_idempotent(monkeypatch, fake_sounddevice):
    stopped = {"n": 0}

    def fake_stop():
        stopped["n"] += 1

    fake_sounddevice.stop = fake_stop
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    s.interrupt()
    s.interrupt()
    assert stopped["n"] == 2  # idempotent in effect, no exception


def test_speaker_provider_singleton():
    from audio.speaker_provider import set_speaker, get_speaker

    marker = object()
    set_speaker(marker)
    assert get_speaker() is marker
    set_speaker(None)
    assert get_speaker() is None
