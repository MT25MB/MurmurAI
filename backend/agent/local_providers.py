"""Optional localhost OpenAI-compatible providers (never cloud, never paid).

Ollama remains the default. A user may register extra local endpoints (llama.cpp,
LM Studio, vLLM) in ~/.murmur-ai/local_endpoints.json. Every base URL is checked
against a strict loopback allowlist before it can be used.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("murmur_ai.agent.local_providers")

DEFAULT_ENDPOINTS_PATH = Path.home() / ".murmur-ai" / "local_endpoints.json"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def is_local_url(url: str) -> bool:
    """True only for credential-free http(s) URLs on loopback."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    return (parsed.hostname or "").lower() in _LOOPBACK


@dataclass(frozen=True)
class LocalEndpoint:
    name: str
    base_url: str
    model: str

    def __post_init__(self) -> None:
        if not _SAFE_NAME.match(self.name):
            raise ValueError(f"Unsafe local endpoint name: {self.name!r}")
        if not is_local_url(self.base_url):
            raise ValueError("Local endpoints must be credential-free http(s) URLs on loopback")

    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        client: Any = None,
    ) -> dict[str, Any]:
        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        client = client or httpx.Client(
            timeout=float(os.getenv("MURMUR_REQUEST_TIMEOUT", "120"))
        )
        response = client.post(self.base_url.rstrip("/") + "/chat/completions", json=payload)
        response.raise_for_status()
        return self.parse_response(response.json())

    @staticmethod
    def parse_response(data: dict[str, Any]) -> dict[str, Any]:
        """Map an OpenAI-style reply into the shape Brain._chat expects."""
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls: list[dict] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)
            calls.append({"function": {"name": function.get("name", ""), "arguments": arguments}})
        return {
            "message": {"content": message.get("content") or "", "tool_calls": calls},
            "error": data.get("error"),
        }


def load_endpoints(path: Path | None = None) -> dict[str, LocalEndpoint]:
    """Read and validate registered local endpoints; unsafe entries are skipped."""
    path = Path(path) if path else DEFAULT_ENDPOINTS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read local endpoint config %s: %s", path, exc)
        return {}
    raw = data.get("endpoints", []) if isinstance(data, dict) else []
    if not isinstance(raw, list):
        logger.warning("local_endpoints.json 'endpoints' must be a list")
        return {}
    endpoints: dict[str, LocalEndpoint] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            endpoint = LocalEndpoint(
                name=str(entry.get("name", "")),
                base_url=str(entry.get("base_url", "")),
                model=str(entry.get("model", "")),
            )
        except ValueError as exc:
            logger.warning("Skipping unsafe local endpoint: %s", exc)
            continue
        endpoints[endpoint.name] = endpoint
    return endpoints
