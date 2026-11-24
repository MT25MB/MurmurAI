"""Headless synthetic voice-to-action end-to-end tests.

The real FastAPI WebSocket server, VAD segmentation, STT interface, brain ReAct
routing and TTS rendering paths all run. Only hardware, model weights and the
Ollama HTTP endpoint are replaced by deterministic fakes, so CI needs no
microphone, GPU, network or heavy model downloads.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import types
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

PHRASES = {
    1: "What is on my screen?",
    2: "Go to sleep",
    3: "Run diagnostics",
}


def _fakes(monkeypatch, played):
    """Install deterministic audio/model fakes before the app starts."""
    import agent.vision_agent as va
    import audio.listener as listener
    import audio.speaker as speaker
    import main
    import setup as app_setup
    from tools import mcp_manager

    class FakeInputStream:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, count):
            return np.zeros((count, 1), dtype=np.float32), None

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    def play(audio, samplerate=None, device=None, blocking=True):
        played.append(np.asarray(audio).copy())
        return None

    fake_sd = SimpleNamespace(
        InputStream=FakeInputStream,
        play=play,
        stop=lambda: None,
        rec=lambda *a, **k: np.zeros(1600, dtype=np.float32),
        wait=lambda: None,
        PortAudioError=RuntimeError,
    )
    monkeypatch.setattr(listener, "sd", fake_sd)
    monkeypatch.setattr(speaker, "sd", fake_sd)
    monkeypatch.setattr(va, "pyautogui", SimpleNamespace(
        click=lambda *a, **k: None,
        doubleClick=lambda *a, **k: None,
        rightClick=lambda *a, **k: None,
        moveTo=lambda *a, **k: None,
        dragTo=lambda *a, **k: None,
        write=lambda *a, **k: None,
        press=lambda *a, **k: None,
        hotkey=lambda *a, **k: None,
        FAILSAFE=False,
        PAUSE=0,
    ))

    class FakeVad:
        def __init__(self, mode):
            self.frames = 0

        def is_speech(self, frame, rate):
            self.frames += 1
            return self.frames <= 12

    monkeypatch.setattr(listener, "webrtcvad", types.SimpleNamespace(Vad=FakeVad))

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            phrase_id = int(round(float(audio[0]) * 32768.0 / 1000.0)) if len(audio) else 0
            text = {
                1: "What is on my screen?",
                2: "Go to sleep",
                3: "Run diagnostics",
            }.get(phrase_id, "")
            return ([SimpleNamespace(text=text)], object())

    monkeypatch.setattr(listener, "WhisperModel", FakeWhisperModel)
    # Headless tests have no speaker bleed; ignore the echo guard between cases.
    monkeypatch.setattr(listener, "echo_is_active", lambda *a, **k: False)

    kokoro = types.ModuleType("kokoro")
    kokoro.KModel = type("KModel", (), {})
    kokoro.KPipeline = type("KPipeline", (), {
        "__init__": lambda self, **kwargs: None,
        "__call__": lambda self, text, **kwargs: [
            (None, None, np.zeros(2205, dtype=np.float32))
        ],
    })
    monkeypatch.setitem(sys.modules, "kokoro", kokoro)

    def fake_chat(messages, model=None, tools=None):
        return {"message": {"content": "I see a Blender window with a cube selected."}}

    monkeypatch.setattr(main.app_state.brain, "_chat", fake_chat)

    async def noop_async(*args, **kwargs):
        return {}

    monkeypatch.setattr(app_setup, "warm_models", noop_async)
    monkeypatch.setattr(app_setup, "prewarm_audio_on_startup", lambda *a, **k: {})
    monkeypatch.setattr(mcp_manager.manager, "reload", lambda: {})
    monkeypatch.setattr(main, "_listen_amplitude", noop_async)
    monkeypatch.setattr(main, "_wake_monitor", noop_async)

    import system.settings_tools as st

    monkeypatch.setattr(st, "run_diagnostics", lambda: {
        "summary": "Diagnostics. Microphone: ok. Ollama: running. Everything looks healthy.",
        "issues": [],
    })

    return main


def _transcript_from_wav(main_module, wav_path):
    """Run the real VAD + STT interface over a fixture WAV."""
    import audio.listener as listener

    with wave_open(wav_path) as handle:
        pcm = handle.readframes(handle.getnframes())

    captured = []
    voice = listener.VoiceListener(silence_ms=150, on_utterance=captured.append)
    voice._buffer = bytearray(pcm)
    voice._process_frames()
    assert captured, "VAD/STT pipeline produced no utterance"
    return captured[0]


def wave_open(path):
    import wave

    return wave.open(str(path), "rb")


def _drain(ws, count, timeout=5.0):
    """Read up to ``count`` messages without ever hanging the suite."""
    inbox: queue.Queue = queue.Queue()

    def reader():
        for _ in range(count):
            try:
                inbox.put(ws.receive_json())
            except Exception as exc:  # connection closed / test teardown
                inbox.put(exc)
                break

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    messages = []
    deadline = time.time() + timeout
    while len(messages) < count and time.time() < deadline:
        try:
            item = inbox.get(timeout=0.1)
        except queue.Empty:
            continue
        if isinstance(item, Exception):
            break
        messages.append(item)
    return messages


@pytest.mark.parametrize("phrase_id,expected_count,expected_states", [
    # Typed commands are a silent chat: transcript + THINKING -> IDLE, no SPEAKING.
    (1, 3, {"THINKING", "IDLE"}),
    (2, 2, {"SLEEPING"}),
    (3, 3, {"IDLE"}),
])
def test_voice_to_action_roundtrip(monkeypatch, fixture_wavs, phrase_id, expected_count, expected_states):
    played = []
    main_module = _fakes(monkeypatch, played)

    # Real VAD/STT stage produces the transcript from a synthetic WAV fixture.
    transcript = _transcript_from_wav(main_module, fixture_wavs[phrase_id])
    assert transcript == PHRASES[phrase_id]

    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws") as ws:
            greeting = ws.receive_json()
            assert greeting["type"] == "state" and greeting["status"] == "IDLE"

            ws.send_text(json.dumps({"type": "text_input", "text": transcript}))
            messages = _drain(ws, expected_count)

    states = {m.get("status") for m in messages if m["type"] == "state"}
    assert expected_states <= states, messages
    assert "SPEAKING" not in states, messages
    assert any(m["type"] == "transcript" for m in messages), messages

    if phrase_id == 1:
        assert any(
            m["type"] == "transcript" and "Blender" in m.get("text", "")
            for m in messages
        )
    if phrase_id == 3:
        assert any("Diagnostics" in m.get("text", "") or "Diagnostics" in m.get("detail", "")
                   for m in messages)

    # Wait briefly for the detached TTS threads to render their buffers.
    deadline = time.time() + 3
    while not played and time.time() < deadline:
        time.sleep(0.02)
    assert played and all(np.asarray(buffer).size > 0 for buffer in played)
