"""Voice pipeline tests: VAD segmentation, STT, TTS, interrupt, earcons.

All audio hardware and model calls are mocked so this runs anywhere, headless.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

import audio.listener as listener
import audio.speaker as speaker


def _make_listener(monkeypatch, fake_sounddevice, vad_fn=None, transcribe_text="hello"):
    """Build a VoiceListener with a scripted VAD and stub transcription."""
    class FakeVad:
        def __init__(self, mode):
            self.mode = mode

        def is_speech(self, frame, rate):
            return vad_fn(frame) if vad_fn else False

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            class Seg:
                text = transcribe_text
            return ([Seg()], object())

    monkeypatch.setattr(listener, "sd", fake_sounddevice)
    monkeypatch.setattr(listener, "webrtcvad", type("V", (), {"Vad": FakeVad})())
    monkeypatch.setattr(listener, "WhisperModel", FakeModel)
    return listener.VoiceListener


def test_voice_listener_requires_deps_when_missing(monkeypatch):
    monkeypatch.setattr(listener, "sd", None)
    with pytest.raises(RuntimeError, match="sounddevice"):
        listener.VoiceListener()


def test_voice_listener_interface_and_lazy_model(monkeypatch, fake_sounddevice):
    L = _make_listener(monkeypatch, fake_sounddevice)
    captured = []
    v = L(model_name="base.en", silence_ms=800, on_utterance=lambda t: captured.append(t))
    assert v.model_name == "base.en" and v.silence_ms == 800
    assert v._model is None  # lazy
    assert v._transcribe((np.zeros(16000) * 32767).astype(np.int16).tobytes()) == "hello"
    assert v._model is not None  # loaded on demand
    v.unload_model()
    assert v._model is None


def test_vad_speech_start_then_silence_finalizes(monkeypatch, fake_sounddevice):
    """Speech followed by >silence_ms of silence triggers on_utterance once."""
    state = {"frames": 0}

    def vad_fn(frame):
        state["frames"] += 1
        # First 10 frames are speech, the rest silence.
        return state["frames"] <= 10

    captured = []
    L = _make_listener(monkeypatch, fake_sounddevice, vad_fn=vad_fn, transcribe_text=" hi there ")
    v = L(silence_ms=90, on_utterance=lambda t: captured.append(t))  # 90ms = 3 silence frames

    # Feed 30 frames of 30ms (900ms): 10 speech + 20 silence.
    frame_bytes = b"\x00" * (listener.FRAME_SAMPLES * 2)
    v._buffer = bytearray(frame_bytes * 30)
    v._process_frames()

    assert captured == ["hi there"], captured
    assert v._speaking is False
    assert v._silence_frames == 0
    assert len(v._buffer) == 0


def test_vad_ignores_subthreshold_noise(monkeypatch, fake_sounddevice):
    """A blip shorter than 0.3s is dropped, not transcribed."""
    captured = []
    L = _make_listener(monkeypatch, fake_sounddevice, vad_fn=lambda f: True,
                       transcribe_text="should not fire")
    v = L(silence_ms=30, on_utterance=lambda t: captured.append(t))
    v._buffer = bytearray(b"\x00" * (listener.FRAME_SAMPLES * 2) * 5)  # 150ms < 300ms
    v._process_frames()
    assert captured == []


def test_transcribe_joins_segments_and_strips(monkeypatch, fake_sounddevice):
    class FakeVad:
        def __init__(self, mode): pass
        def is_speech(self, f, r): return False

    class FakeModel:
        def __init__(self, *a, **k): pass
        def transcribe(self, audio, **kwargs):
            segs = [type("S", (), {"text": " open "})(), type("S", (), {"text": "blender "})()]
            return (segs, object())

    monkeypatch.setattr(listener, "sd", fake_sounddevice)
    monkeypatch.setattr(listener, "webrtcvad", type("V", (), {"Vad": FakeVad})())
    monkeypatch.setattr(listener, "WhisperModel", FakeModel)
    v = listener.VoiceListener()
    assert v._transcribe((np.zeros(16000) * 32767).astype(np.int16).tobytes()) == "open blender"


def test_asr_confidence_from_logprob_and_no_speech():
    from audio.asr_confidence import confidence_from_segments

    high = confidence_from_segments([
        {"text": "hello", "avg_logprob": -0.1, "no_speech_prob": 0.01},
    ])
    low = confidence_from_segments([
        {"text": "hello", "avg_logprob": -1.2, "no_speech_prob": 0.8},
    ])
    assert high[0] == "high" and low[0] == "low"


def test_hotwords_include_window_title_and_pronunciations(monkeypatch):
    from audio import hotwords

    monkeypatch.setattr(hotwords, "_active_window_title", lambda: "Blender - scene.blend")
    monkeypatch.setattr(hotwords, "_skill_keywords", lambda: ["viewport", "timeline"])
    monkeypatch.setattr(
        hotwords, "_custom_names", lambda: ["GUI", "DaVinci"]
    )
    hint = hotwords.build_hint()
    assert "Blender" in hint
    assert "viewport" in hint
    assert "GUI" in hint


def test_transcribe_passes_prompt_hint(monkeypatch, fake_sounddevice):
    seen = {}

    class Seg:
        text = " open blender "
        avg_logprob = -0.1
        no_speech_prob = 0.01

    class Model:
        def transcribe(self, audio, **kwargs):
            seen.update(kwargs)
            return [Seg()], {}

    v = _make_listener(monkeypatch, fake_sounddevice)()
    v._model = Model()
    result = v._transcribe((np.zeros(16000) * 32767).astype(np.int16).tobytes())
    assert result == "open blender"
    assert "initial_prompt" in seen
    assert v.last_confidence == "high"


def test_transcribe_failure_returns_empty(monkeypatch, fake_sounddevice):
    class FakeVad:
        def __init__(self, mode): pass
        def is_speech(self, f, r): return False
    class FakeModel:
        def __init__(self, *a, **k): pass
        def transcribe(self, audio, **kwargs):
            raise RuntimeError("model blew up")

    monkeypatch.setattr(listener, "sd", fake_sounddevice)
    monkeypatch.setattr(listener, "webrtcvad", type("V", (), {"Vad": FakeVad})())
    monkeypatch.setattr(listener, "WhisperModel", FakeModel)
    v = listener.VoiceListener()
    assert v._transcribe((np.zeros(16000) * 32767).astype(np.int16).tobytes()) == ""


def test_speaker_earcons_toggle_and_cues(monkeypatch, fake_sounddevice):
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    assert set(s.EARCON_NOTES) >= {"listening", "thinking", "speaking", "confirmation", "error"}
    s.set_earcons(False)
    assert not s.earcons_enabled
    s.chime("confirmation")  # no-op when disabled
    s.set_earcons(True)
    assert s.earcons_enabled
    s.chime("nonexistent")  # unknown cue is safe


def test_speaker_chime_plays_when_enabled(monkeypatch, fake_sounddevice):
    played = []
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker(earcons=True)
    monkeypatch.setattr(s, "_stream_audio", lambda audio, rate: played.append((len(audio), rate)))
    s.chime("listening")
    # chime runs in a thread, so wait briefly
    import time
    for _ in range(50):
        if played:
            break
        time.sleep(0.01)
    assert played and played[0][1] == speaker.SAMPLE_RATE


def test_speaker_interrupt_is_idempotent(monkeypatch, fake_sounddevice):
    stopped = {"n": 0}
    fake_sounddevice.stop = lambda: stopped.__setitem__("n", stopped["n"] + 1)
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    s.interrupt()
    s.interrupt()
    assert stopped["n"] == 2 and s._interrupted


def test_speaker_provider_singleton():
    from audio.speaker_provider import set_speaker, get_speaker
    marker = object()
    set_speaker(marker)
    assert get_speaker() is marker
    set_speaker(None)
    assert get_speaker() is None


# ---- offline wake-word detection ----

def test_wake_and_sleep_earcon_cues_exist():
    assert "wake" in speaker.LocalSpeaker.EARCON_NOTES
    assert "sleep" in speaker.LocalSpeaker.EARCON_NOTES


@pytest.mark.parametrize("text", [
    "hey murmur", "Hey Murmur!", "wake up murmur", "wake murmur",
    "ok murmur", "MURMUR", "hey, murmur.",
])
def test_text_is_wake_phrase(text):
    from audio.wake_word import text_is_wake_phrase
    assert text_is_wake_phrase(text), text


@pytest.mark.parametrize("text", [
    "hello there", "what time is it", "open blender",
    "murmer", "", "   ",
])
def test_text_is_not_wake_phrase(text):
    from audio.wake_word import text_is_wake_phrase
    assert not text_is_wake_phrase(text), text


@pytest.mark.parametrize("text", [
    "go to sleep", "stop listening", "pause murmur", "pause listening",
    "go to standby", "sleep mode", "standby mode",
])
def test_text_is_sleep_phrase(text):
    from audio.wake_word import text_is_sleep_phrase
    assert text_is_sleep_phrase(text), text


@pytest.mark.parametrize("text", ["wake up", "hello", "delete that file", ""])
def test_text_is_not_sleep_phrase(text):
    from audio.wake_word import text_is_sleep_phrase
    assert not text_is_sleep_phrase(text), text


def _pcm():
    return (np.zeros(16000, dtype=np.int16)).tobytes()


def test_wake_detector_openwakeword_backend(monkeypatch):
    import audio.wake_word as ww
    d = object.__new__(ww.WakeWordDetector)
    d.backend = "openwakeword"
    d.model_name = "tiny.en"

    class FakeModel:
        def __init__(self): self.scores = [0.1]
        def predict(self, audio):
            self.scores = [0.9] if self.scores == [0.1] else [0.1]
            return {"hey_murmur": self.scores}

    d._oww_model = FakeModel()
    assert d.available is True
    assert d.detect(_pcm()) is True   # first call: 0.9
    assert d.detect(_pcm()) is False  # second call: 0.1
    assert d.detect(b"") is False


def test_wake_detector_whisper_keyword_backend(monkeypatch):
    import audio.wake_word as ww
    d = object.__new__(ww.WakeWordDetector)
    d.backend = "whisper-keyword"
    d.model_name = "tiny.en"

    class Seg:
        def __init__(self, t): self.text = t

    class FakeModel:
        def __init__(self): self.calls = 0
        def transcribe(self, audio, **kwargs):
            self.calls += 1
            text = "hey murmur" if self.calls == 1 else "weather forecast"
            return ([Seg(text)], None)

    d._whisper_model = FakeModel()
    assert d.available is True
    assert d.detect(_pcm()) is True
    assert d.detect(_pcm()) is False


def test_wake_detector_no_backend_degrades_gracefully():
    import audio.wake_word as ww
    d = object.__new__(ww.WakeWordDetector)
    d.backend = None
    d.model_name = "tiny.en"
    assert d.available is False
    assert d.detect(_pcm()) is False


def test_wake_detector_backend_error_returns_false():
    import audio.wake_word as ww
    d = object.__new__(ww.WakeWordDetector)
    d.backend = "openwakeword"
    d.model_name = "tiny.en"

    class BrokenModel:
        def predict(self, audio): raise RuntimeError("model error")

    d._oww_model = BrokenModel()
    assert d.detect(_pcm()) is False


# ---- sleep / wake state transitions ----

def _reset_sleep_state():
    import main
    main.app_state.listening_mode = "active"
    main.app_state.wake_detector = None
    main.app_state.wake_task = None
    main.app_state.speaker = None


@pytest.mark.asyncio
async def test_enter_sleep_broadcasts_sleeping_and_sets_mode(monkeypatch):
    import main
    from agent.state import SessionState

    _reset_sleep_state()
    sent, chimes, spoken = [], [], []

    async def send(msg): sent.append(msg)
    async def noop_monitor(*a, **k): pass

    monkeypatch.setattr(main, "_chime", lambda k: chimes.append(k))
    monkeypatch.setattr(main, "_announce", lambda t: spoken.append(t))
    monkeypatch.setattr(main, "_wake_monitor", noop_monitor)

    await main.enter_sleep(SessionState(), send)
    assert main.app_state.listening_mode == "sleep"
    assert any(m.type == "state" and m.status == "SLEEPING" for m in sent)
    assert chimes == ["sleep"]
    assert "hey murmur" in spoken[0].lower()

    # Reset so other tests see active mode.
    if main.app_state.wake_task:
        main.app_state.wake_task.cancel()
    _reset_sleep_state()


@pytest.mark.asyncio
async def test_enter_sleep_releases_microphone(monkeypatch):
    import main
    from agent.state import SessionState

    _reset_sleep_state()
    stopped = {"n": 0}
    listener_stub = type("L", (), {"stop": lambda self: stopped.__setitem__("n", 1)})()
    main.app_state.listener = listener_stub

    async def send(msg): pass
    async def noop_monitor(*a, **k): pass

    monkeypatch.setattr(main, "_chime", lambda k: None)
    monkeypatch.setattr(main, "_announce", lambda t: None)
    monkeypatch.setattr(main, "_wake_monitor", noop_monitor)

    await main.enter_sleep(SessionState(), send)
    assert stopped["n"] == 1
    assert main.app_state.listener is None
    assert main.app_state.listening_task is None

    if main.app_state.wake_task:
        main.app_state.wake_task.cancel()
    _reset_sleep_state()


@pytest.mark.asyncio
async def test_wake_up_broadcasts_idle_and_speaks_im_listening(monkeypatch):
    import main
    from agent.state import SessionState

    _reset_sleep_state()
    main.app_state.listening_mode = "sleep"
    sent, chimes, spoken = [], [], []

    async def send(msg): sent.append(msg)

    monkeypatch.setattr(main, "_chime", lambda k: chimes.append(k))
    monkeypatch.setattr(main, "_announce", lambda t: spoken.append(t))

    await main.wake_up(SessionState(), send)
    assert main.app_state.listening_mode == "active"
    assert sent[-1].status == "IDLE"
    assert chimes == ["wake"]
    assert spoken == ["I'm listening"]
    assert main.app_state.wake_task is None


@pytest.mark.asyncio
async def test_apply_listening_mode_validates(monkeypatch):
    import main
    _reset_sleep_state()
    main._apply_listening_mode("sleep")
    assert main.app_state.listening_mode == "sleep"
    with pytest.raises(AssertionError):
        main._apply_listening_mode("invalid")
    _reset_sleep_state()


@pytest.mark.asyncio
async def test_verbal_sleep_phrase_bypasses_brain(monkeypatch):
    import main
    from agent.state import SessionState

    _reset_sleep_state()
    sent = []

    async def send(msg): sent.append(msg)
    async def noop_monitor(*a, **k): pass

    monkeypatch.setattr(main, "_chime", lambda k: None)
    monkeypatch.setattr(main, "_announce", lambda t: None)
    monkeypatch.setattr(main, "_wake_monitor", noop_monitor)
    monkeypatch.setattr(main.app_state.brain, "think_and_act",
                        lambda *a, **k: pytest.fail("brain must not be called"))

    await main._on_utterance_async(SessionState(), send, "go to sleep")
    assert main.app_state.listening_mode == "sleep"
    assert any(getattr(m, "status", None) == "SLEEPING" for m in sent)

    if main.app_state.wake_task:
        main.app_state.wake_task.cancel()
    _reset_sleep_state()


@pytest.mark.asyncio
async def test_verbal_wake_phrase_from_standby_resumes(monkeypatch):
    import main
    from agent.state import SessionState

    _reset_sleep_state()
    main.app_state.listening_mode = "sleep"
    sent = []

    async def send(msg): sent.append(msg)
    async def noop_listen(*a, **k): pass

    monkeypatch.setattr(main, "_chime", lambda k: None)
    monkeypatch.setattr(main, "_announce", lambda t: None)
    monkeypatch.setattr(main, "start_listening", noop_listen)

    await main._on_utterance_async(SessionState(), send, "wake up murmur")
    assert main.app_state.listening_mode == "active"
    assert any(m.status == "IDLE" for m in sent if getattr(m, "status", None))
    _reset_sleep_state()


def test_ws_set_listening_mode_sleep_and_active(monkeypatch):
    from fastapi.testclient import TestClient
    import main

    _reset_sleep_state()

    async def noop(*a, **k): pass
    monkeypatch.setattr(main, "_wake_monitor", noop)
    monkeypatch.setattr(main, "start_listening", noop)
    monkeypatch.setattr(main, "_chime", lambda k: None)
    monkeypatch.setattr(main, "_announce", lambda t: None)

    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # greeting
        ws.send_text('{"type":"set_listening_mode","mode":"sleep"}')
        messages = [ws.receive_json(), ws.receive_json()]
        states = [m for m in messages if m["type"] == "state"]
        assert states and states[0]["status"] == "SLEEPING"
        assert main.app_state.listening_mode == "sleep"

        ws.send_text('{"type":"set_listening_mode","mode":"active"}')
        msg = ws.receive_json()
        assert msg["status"] == "IDLE"
        assert main.app_state.listening_mode == "active"

    _reset_sleep_state()


# ---- echo / speaker-bleed guard ----

def test_echo_guard_drops_frames_while_speaking(monkeypatch, fake_sounddevice):
    monkeypatch.setattr(listener, "echo_is_active", lambda *a, **k: True)
    captured = []
    L = _make_listener(monkeypatch, fake_sounddevice, vad_fn=lambda f: True,
                       transcribe_text="should not happen")
    v = L(on_utterance=lambda t: captured.append(t))
    v._buffer = bytearray(b"\x00" * (listener.FRAME_SAMPLES * 2) * 10)
    v._speaking = True
    v._process_frames()
    assert captured == []
    assert len(v._buffer) == 0
    assert v._speaking is False


def test_echo_guard_tail_buffer_timing(monkeypatch):
    import time

    import audio.echo_guard as guard

    speaker_stub = type("S", (), {
        "is_speaking": lambda self: False,
        "last_speak_end": time.monotonic() - 0.10,
    })()
    monkeypatch.setattr(guard, "get_speaker", lambda: speaker_stub)
    monkeypatch.setattr(guard, "loopback_is_loud", lambda *a, **k: False)

    assert guard.echo_is_active(tail_s=0.25, loopback=False) is True
    speaker_stub.last_speak_end = time.monotonic() - 0.50
    assert guard.echo_is_active(tail_s=0.25, loopback=False) is False


def test_echo_guard_while_speaker_is_active(monkeypatch):
    import audio.echo_guard as guard

    stub = type("S", (), {"is_speaking": lambda self: True, "last_speak_end": None})()
    monkeypatch.setattr(guard, "get_speaker", lambda: stub)
    assert guard.echo_is_active(0.25, False) is True


def test_wake_detector_respects_echo_guard(monkeypatch):
    import audio.wake_word as wake

    monkeypatch.setattr(wake, "echo_is_active", lambda *a, **k: True)
    d = object.__new__(wake.WakeWordDetector)
    d.echo_guard = True
    d.echo_tail_s = 0.25
    d.loopback_guard = True
    d.backend = "openwakeword"
    d._oww_model = type("M", (), {"predict": lambda self, a: {"hey": [0.99]}})()
    assert d.detect((np.zeros(16000, dtype=np.int16)).tobytes()) is False

    monkeypatch.setattr(wake, "echo_is_active", lambda *a, **k: False)
    assert d.detect((np.zeros(16000, dtype=np.int16)).tobytes()) is True


# ---- barge-in, ducking and screen-reader friendliness ----

def test_speaker_marks_end_and_restores_volume(monkeypatch, fake_sounddevice):
    events = []
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    s.set_media_ducking(True)
    s._ducker = type("D", (), {
        "duck": lambda self: events.append("duck"),
        "restore": lambda self: events.append("restore"),
    })()
    monkeypatch.setattr(s, "_resolve_engine", lambda: "kokoro")
    monkeypatch.setattr(s, "_speak_kokoro", lambda text: None)

    s.speak("hello")
    for _ in range(100):
        if not s.is_speaking():
            break
        time.sleep(0.01)

    assert events == ["duck", "restore"]
    assert s.last_speak_end is not None


def test_be_quiet_interrupts_immediately(monkeypatch, fake_sounddevice):
    stopped = {"n": 0}
    fake_sounddevice.stop = lambda: stopped.__setitem__("n", stopped["n"] + 1)
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker()
    s.be_quiet()
    assert stopped["n"] == 1 and s._interrupted is True


def test_screen_reader_friendly_suppresses_chimes(monkeypatch, fake_sounddevice):
    played = []
    monkeypatch.setattr(speaker, "sd", fake_sounddevice)
    s = speaker.LocalSpeaker(earcons=True)
    monkeypatch.setattr(s, "_stream_audio", lambda audio, rate: played.append(rate))
    s.set_screen_reader_friendly(True)
    s.chime("listening")
    assert played == []
    s.set_screen_reader_friendly(False)
    s.chime("listening")
    for _ in range(50):
        if played:
            break
        time.sleep(0.01)
    assert played


def test_config_toggles_apply_to_speaker(monkeypatch, tmp_path):
    import system.settings_tools as st

    calls = []
    stub = type("S", (), {
        "set_speech_rate": lambda self, v: calls.append(("rate", v)),
        "set_voice": lambda self, v: calls.append(("voice", v)),
        "set_earcons": lambda self, v: calls.append(("earcons", v)),
        "set_screen_reader_friendly": lambda self, v: calls.append(("sr", v)),
        "set_media_ducking": lambda self, v: calls.append(("duck", v)),
    })()
    monkeypatch.setattr(st, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(st, "_CACHE", None)
    monkeypatch.setattr("audio.speaker_provider.get_speaker", lambda: stub)
    monkeypatch.setattr("main.app_state", type("A", (), {
        "listener": None, "brain": type("B", (), {})(), "wake_detector": None,
    })(), raising=False)

    st.update_settings({"screen_reader_friendly": True, "media_ducking": True})
    assert ("sr", True) in calls
    assert ("duck", True) in calls
    assert st.load_settings()["echo_guard"] is True


def test_be_quiet_voice_command(monkeypatch):
    import system.settings_tools as st

    calls = []
    stub = type("S", (), {"be_quiet": lambda self: calls.append(1),
                          "interrupt": lambda self: calls.append(2)})()
    monkeypatch.setattr("audio.speaker_provider.get_speaker", lambda: stub)
    reply = st.handle_voice_command("Be quiet")
    assert reply and "quiet" in reply.lower()
    assert calls == [1]

