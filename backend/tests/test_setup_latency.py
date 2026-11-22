"""Setup status must stay fast when Ollama is absent or slow."""

from __future__ import annotations

import time

import setup


def test_ollama_probe_has_short_timeout(monkeypatch):
    """A missing Ollama must not stall /setup/status for seconds."""
    calls = []

    def slow_get(url, timeout):
        calls.append((url, timeout))
        time.sleep(0.15)
        raise OSError("offline")

    monkeypatch.setattr(setup.httpx, "get", slow_get)

    start = time.perf_counter()
    status = setup.ollama_status()
    elapsed = time.perf_counter() - start

    assert status["running"] is False
    assert elapsed < 0.5, f"probe took {elapsed:.2f}s"
    assert calls and calls[0][1] <= 1.0, "timeout should be bounded to ~1s"


def test_tags_are_cached_between_status_helpers(monkeypatch):
    """get_setup_status should not hit /api/tags twice for the same snapshot."""
    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return {"models": []}

    def counted_get(url, timeout):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(setup.httpx, "get", counted_get)
    monkeypatch.setattr(setup, "COMPLETE_MARKER", setup.Path("/nonexistent-marker"))

    setup.get_setup_status()

    tag_calls = [c for c in calls if "/api/tags" in c]
    assert len(tag_calls) <= 1, f"expected one tags call, got {tag_calls}"
