"""Shared fixtures for headless voice-to-action end-to-end tests."""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Fixture phrases mapped to a synthetic WAV index (encoded in the first sample).
PHRASES = {
    1: "What is on my screen?",
    2: "Go to sleep",
    3: "Run diagnostics",
}


def write_fixture_wav(path: Path, index: int) -> Path:
    """Create a short 16 kHz mono WAV whose first sample encodes the phrase id."""
    sample_rate = 16000
    frames = int(sample_rate * 0.6)
    t = np.linspace(0.0, 0.6, frames, endpoint=False)
    samples = (np.sin(2 * np.pi * (180 + index * 40) * t) * 3000).astype(np.int16)
    samples[0] = index * 1000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return path


@pytest.fixture(autouse=True)
def e2e_environment(monkeypatch):
    monkeypatch.setenv("MURMUR_AI_AUTO_DOWNLOAD_WEIGHTS", "0")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("MURMUR_AI_EARCONS", "0")
    # The production readiness gate is covered in backend/tests. E2E fixtures
    # run without Ollama or weights, so assume a ready local environment here.
    import setup
    monkeypatch.setattr(setup, "readiness", lambda: {
        "ready": True, "missing": [], "detail": "All local components are ready.",
    })


@pytest.fixture
def fixture_wavs(tmp_path):
    return {index: write_fixture_wav(tmp_path / f"phrase-{index}.wav", index)
            for index in PHRASES}
