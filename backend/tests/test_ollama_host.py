"""OLLAMA_HOST is an Ollama listen address, not necessarily a client URL.

Ollama commonly sets it to ``0.0.0.0``. httpx rejects that as a relative URL,
which surfaced in the HUD as "Request URL is missing an 'http://' or 'https://'
protocol" instead of starting a model pull.
"""

from __future__ import annotations

import pytest

import setup as app_setup
from local_endpoint import DEFAULT_OLLAMA_HOST, normalize_ollama_host, ollama_host


def test_bare_listen_address_becomes_a_loopback_url():
    assert normalize_ollama_host("0.0.0.0") == DEFAULT_OLLAMA_HOST
    assert normalize_ollama_host("0.0.0.0:11434") == DEFAULT_OLLAMA_HOST
    assert normalize_ollama_host(" 0.0.0.0 ") == DEFAULT_OLLAMA_HOST


def test_bare_host_and_host_port_get_a_scheme():
    assert normalize_ollama_host("127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert normalize_ollama_host("localhost:11434") == "http://localhost:11434"


def test_full_urls_are_preserved_without_a_trailing_slash():
    assert normalize_ollama_host("http://localhost:11434/") == "http://localhost:11434"
    assert normalize_ollama_host("https://127.0.0.1:11434") == "https://127.0.0.1:11434"
    assert normalize_ollama_host("http://[::1]:11434") == "http://[::1]:11434"


def test_empty_or_invalid_values_fall_back_to_loopback():
    assert normalize_ollama_host(None) == DEFAULT_OLLAMA_HOST
    assert normalize_ollama_host("") == DEFAULT_OLLAMA_HOST
    assert normalize_ollama_host("ftp://localhost:11434") == DEFAULT_OLLAMA_HOST
    assert normalize_ollama_host("http://bad:port") == DEFAULT_OLLAMA_HOST


def test_ollama_host_reads_the_environment_at_call_time(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0")
    assert ollama_host() == DEFAULT_OLLAMA_HOST


class _FakeStream:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def aiter_lines(self):
        yield '{"status":"success"}'

    async def aread(self):
        return b""


class _CapturingClient:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, method, url, **_kwargs):
        self.calls.append((method, url))
        return _FakeStream()


@pytest.mark.asyncio
async def test_pull_uses_an_absolute_url_even_with_a_listen_address(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(app_setup.httpx, "AsyncClient", lambda *_a, **_k: client)
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0")

    result = await app_setup.pull_model("qwen2.5:7b", lambda *_args: None)

    assert result["ok"] is True
    assert client.calls == [("POST", "http://127.0.0.1:11434/api/pull")]
