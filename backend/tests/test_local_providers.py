"""Optional local OpenAI-compatible endpoints stay strictly on loopback."""

from __future__ import annotations

import json

from agent.local_providers import LocalEndpoint, is_local_url, load_endpoints


def test_only_loopback_urls_are_local():
    assert is_local_url("http://127.0.0.1:8080/v1")
    assert is_local_url("http://localhost:11434")
    assert is_local_url("https://[::1]:8443/v1")
    assert not is_local_url("https://api.openai.com/v1")
    assert not is_local_url("http://user:pass@127.0.0.1:8080")
    assert not is_local_url("ftp://127.0.0.1/v1")
    assert not is_local_url("not a url")


def test_unsafe_endpoint_config_is_skipped(tmp_path):
    path = tmp_path / "local_endpoints.json"
    path.write_text(json.dumps({"endpoints": [
        {"name": "llama", "base_url": "http://127.0.0.1:8080/v1", "model": "local"},
        {"name": "cloud", "base_url": "https://api.example.com/v1", "model": "x"},
        {"name": "../escape", "base_url": "http://127.0.0.1:9/v1", "model": "x"},
    ]}), encoding="utf-8")

    endpoints = load_endpoints(path)

    assert set(endpoints) == {"llama"}
    assert endpoints["llama"].model == "local"


def test_openai_response_is_converted_to_internal_shape():
    endpoint = LocalEndpoint(name="llama", base_url="http://127.0.0.1:8080/v1", model="local")
    response = {
        "choices": [{
            "message": {
                "content": "hello",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "open_application", "arguments": '{"app_name":"Notepad"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }]
    }

    converted = endpoint.parse_response(response)

    assert converted["message"]["content"] == "hello"
    assert converted["message"]["tool_calls"][0]["function"]["name"] == "open_application"


def test_brain_routes_to_configured_local_endpoint(monkeypatch):
    import agent.brain as brain_module

    class Endpoint:
        def __init__(self):
            self.seen = None

        def chat(self, messages, tools=None):
            self.seen = messages
            return {"message": {"content": "from local"}}

    endpoint = Endpoint()
    monkeypatch.setenv("MURMUR_LOCAL_ENDPOINT", "llama")
    monkeypatch.setattr(brain_module, "load_endpoints", lambda: {"llama": endpoint})

    brain = brain_module.Brain()
    result = brain._chat([{"role": "user", "content": "hi"}])

    assert result["message"]["content"] == "from local"
    assert endpoint.seen[0]["content"] == "hi"


def test_openai_payload_stays_on_loopback():
    endpoint = LocalEndpoint(name="llama", base_url="http://127.0.0.1:8080/v1", model="local")
    seen: dict = {}

    class FakeClient:
        def post(self, url, json):
            seen["url"] = url
            seen["payload"] = json

            class FakeResponse:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"choices": [{"message": {"content": "ok"}}]}

            return FakeResponse()

    converted = endpoint.chat(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "open_application"}}],
        client=FakeClient(),
    )

    assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert seen["payload"]["model"] == "local"
    assert seen["payload"]["tools"][0]["function"]["name"] == "open_application"
    assert converted["message"]["content"] == "ok"
