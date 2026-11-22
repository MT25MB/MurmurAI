"""Streamed local model replies are chunked at sentence boundaries."""

from __future__ import annotations

import json

from agent.brain import Brain


def test_stream_sentences_from_ollama_chunks():
    brain = Brain(host="http://127.0.0.1:1")

    class FakeResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        def raise_for_status(self):
            return None

        def iter_lines(self):
            for chunk in self._chunks:
                yield json.dumps(chunk)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeClient:
        def stream(self, method, url, json):
            assert json["stream"] is True
            return FakeResponse([
                {"message": {"content": "First sentence."}},
                {"message": {"content": " Second"}},
                {"message": {"content": " sentence. Third one."}},
            ])

    brain._client = FakeClient()
    sentences = list(
        brain.stream_sentences([{"role": "user", "content": "talk"}])
    )

    assert [s.text for s in sentences] == ["First sentence.", "Second sentence.", "Third one."]


def test_stream_sentences_handles_local_endpoint_fallback(monkeypatch):
    brain = Brain(host="http://127.0.0.1:1")

    class Endpoint:
        def chat(self, messages, tools=None):
            return {"message": {"content": "One. Two."}}

    brain.local_endpoint = Endpoint()
    sentences = list(
        brain.stream_sentences([{"role": "user", "content": "talk"}])
    )
    assert [s.text for s in sentences] == ["One.", "Two."]
