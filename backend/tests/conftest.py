"""Shared pytest fixtures for Murmur AI backend tests.

All external hardware/network calls are mocked here so the suite runs fast and
deterministically in CI without microphones, speakers, Ollama, or display servers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Ensure the backend package root is importable regardless of the CI working dir.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def _no_model_download(monkeypatch):
    """Never trigger first-run weight/model downloads during tests."""
    monkeypatch.setenv("MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS", "0")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    yield


@pytest.fixture
def noop_confirm():
    """A confirm_callback that approves everything (for execution-path tests)."""
    return lambda description, command: True


@pytest.fixture
def deny_confirm():
    """A confirm_callback that denies everything."""
    return lambda description, command: False


@pytest.fixture
def fake_whisper(monkeypatch):
    """Inject a fake faster-whisper model returning deterministic segments."""
    import audio.listener as listener

    class FakeSegment:
        def __init__(self, text):
            self.text = text

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            return ([FakeSegment("hello world")], SimpleNamespace())

    monkeypatch.setattr(listener, "WhisperModel", FakeModel)
    return FakeModel


@pytest.fixture
def fake_sounddevice(monkeypatch):
    """A minimal sounddevice stub (no real audio device access)."""
    import numpy as np

    class FakeInputStream:
        def __init__(self, *a, **k):
            self._entered = False

        def __enter__(self):
            self._entered = True
            return self

        def __exit__(self, *a):
            self._entered = False

        def read(self, n):
            return np.zeros((n, 1), dtype="float32"), None

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    fake = SimpleNamespace(
        InputStream=FakeInputStream,
        play=lambda *a, **k: None,
        stop=lambda: None,
        PortAudioError=RuntimeError,
    )
    return fake
