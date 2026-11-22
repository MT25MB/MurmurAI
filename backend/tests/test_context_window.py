"""Context window starts from hardware and grows once on an Ollama overflow.

Capri sizes her memory from RAM/VRAM and retries an overflowed ask with a
bigger window. Murmur does the same locally, with a user override that always
wins and a hard cap so a runaway request cannot eat all system memory.
"""

from __future__ import annotations

from copy import deepcopy

from system.profiler import initial_context_window, needed_context, next_context_window


def test_initial_context_high_hardware():
    assert initial_context_window(16, 0) == 16_384
    assert initial_context_window(8, 6) == 16_384


def test_initial_context_light_hardware():
    assert initial_context_window(8, 0) == 4_096


def test_initial_context_mid_hardware():
    assert initial_context_window(12, 0) == 8_192


def test_initial_context_override_wins():
    assert initial_context_window(64, 24, override=2_048) == 2_048


def test_needed_context_parses_ollama_overflow():
    error = "request (6073 tokens) exceeds the available context size (4096 tokens)"
    assert needed_context(error) == 6_073 + 512


def test_needed_context_ignores_unrelated_errors():
    assert needed_context("model not found") is None
    assert needed_context("") is None


def test_next_context_grows_one_tier():
    assert next_context_window(4_096, 6_500) == 8_192
    assert next_context_window(8_192, 9_000) == 16_384


def test_next_context_returns_none_at_cap():
    assert next_context_window(16_384, 60_000, cap=16_384) is None
    assert next_context_window(32_768, 60_000) is None


def _fake_brain(monkeypatch=None):
    from agent.brain import Brain

    brain = Brain(host="http://127.0.0.1:1")
    posts: list[dict] = []

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self.data

    def make_client(responses):
        posts.clear()

        class FakeClient:
            def post(self, path, json):
                posts.append(deepcopy(json))
                return FakeResponse(responses[len(posts) - 1])

        return FakeClient()

    brain._make_fake_client = make_client
    brain._posts = posts
    return brain


def test_chat_retries_overflow_once_with_bigger_window():
    brain = _fake_brain()
    brain.context_window = 4_096
    brain._auto_context = True
    overflow = {"error": "request (6073 tokens) exceeds the available context size (4096 tokens)"}
    brain._client = brain._make_fake_client([overflow, {"message": {"content": "hello"}}])

    result = brain._chat([{"role": "user", "content": "hi"}])

    assert result["message"]["content"] == "hello"
    assert len(brain._posts) == 2
    assert brain._posts[0]["options"]["num_ctx"] == 4_096
    assert brain._posts[1]["options"]["num_ctx"] == 8_192
    assert brain.context_window == 8_192


def test_chat_does_not_retry_with_explicit_override(monkeypatch):
    monkeypatch.setenv("MURMUR_CONTEXT_WINDOW", "2048")
    brain = _fake_brain()
    overflow = {"error": "request (6073 tokens) exceeds the available context size (2048 tokens)"}
    brain._client = brain._make_fake_client([overflow, {"message": {"content": "unexpected"}}])

    result = brain._chat([{"role": "user", "content": "hi"}])

    assert "error" in result
    assert len(brain._posts) == 1
    assert brain._posts[0]["options"]["num_ctx"] == 2_048
