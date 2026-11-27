"""Optional OpenAI-compatible providers, local by default and cloud opt-in.

Ollama remains the default. A user may register extra endpoints (llama.cpp,
LM Studio, vLLM on loopback, or an explicitly opted-in cloud API) in
~/.murmur-ai/local_endpoints.json. Loopback is the default; a remote base URL
is accepted only with ``cloud: true`` in that file, and an API key is read from
the local secret vault at call time rather than stored in the config.
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
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
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


def is_allowed_url(url: str, cloud: bool = False) -> bool:
    """Loopback for local providers; https remote URLs only when cloud is on."""
    if not cloud:
        return is_local_url(url)
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    return bool(parsed.hostname) and (parsed.hostname or "").lower() not in _LOOPBACK


@dataclass(frozen=True)
class LocalEndpoint:
    name: str
    base_url: str
    model: str
    cloud: bool = False
    api_key_ref: str = ""

    def __post_init__(self) -> None:
        if not _SAFE_NAME.match(self.name):
            raise ValueError(f"Unsafe provider name: {self.name!r}")
        if not _SAFE_MODEL.match(self.model):
            raise ValueError(f"Unsafe model name: {self.model!r}")
        if not is_allowed_url(self.base_url, self.cloud):
            raise ValueError(
                "Local providers must use credential-free loopback http(s); "
                "cloud providers must use an https URL without embedded credentials"
            )
        if self.api_key_ref and not _SAFE_REF.match(self.api_key_ref):
            raise ValueError("Unsafe API key reference")

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

        headers: dict[str, str] = {}
        if self.cloud and self.api_key_ref:
            from security.secret_vault import get_secret

            key = get_secret(self.api_key_ref)
            if key:
                headers["Authorization"] = f"Bearer {key}"

        client = client or httpx.Client(
            timeout=float(os.getenv("MURMUR_REQUEST_TIMEOUT", "120")),
            headers=headers,
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


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read provider config %s: %s", path, exc)
        return []
    raw = data.get("endpoints", []) if isinstance(data, dict) else []
    return raw if isinstance(raw, list) else []


def _write_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"endpoints": entries}, indent=2), encoding="utf-8")


def load_endpoints(path: Path | None = None) -> dict[str, LocalEndpoint]:
    """Read and validate registered providers; unsafe entries are skipped."""
    endpoints: dict[str, LocalEndpoint] = {}
    for entry in _read_entries(Path(path) if path else DEFAULT_ENDPOINTS_PATH):
        if not isinstance(entry, dict):
            continue
        try:
            endpoint = LocalEndpoint(
                name=str(entry.get("name", "")),
                base_url=str(entry.get("base_url", "")),
                model=str(entry.get("model", "")),
                cloud=bool(entry.get("cloud", False)),
                api_key_ref=str(entry.get("api_key_ref", "") or ""),
            )
        except ValueError as exc:
            logger.warning("Skipping unsafe provider: %s", exc)
            continue
        endpoints[endpoint.name] = endpoint
    return endpoints


def list_providers(path: Path | None = None) -> list[dict[str, Any]]:
    """Sanitized provider list for Settings; never includes an API key."""
    from security.secret_vault import secret_state

    result = []
    for entry in _read_entries(Path(path) if path else DEFAULT_ENDPOINTS_PATH):
        if not isinstance(entry, dict):
            continue
        ref = str(entry.get("api_key_ref", "") or "")
        result.append({
            "name": str(entry.get("name", "")),
            "base_url": str(entry.get("base_url", "")),
            "model": str(entry.get("model", "")),
            "cloud": bool(entry.get("cloud", False)),
            "api_key_ref": ref,
            "key_configured": bool(ref) and secret_state(ref) == "configured",
        })
    return result


def register_provider(
    name: str,
    base_url: str,
    model: str,
    cloud: bool = False,
    api_key: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Validate and save a provider. Cloud use is explicit; keys go to the vault."""
    endpoint = LocalEndpoint(
        name=name, base_url=base_url, model=model, cloud=cloud,
        api_key_ref=f"provider:{name}" if cloud and api_key else "",
    )
    target = Path(path) if path else DEFAULT_ENDPOINTS_PATH
    entries = [e for e in _read_entries(target) if isinstance(e, dict) and e.get("name") != name]
    entries.append({
        "name": endpoint.name,
        "base_url": endpoint.base_url,
        "model": endpoint.model,
        "cloud": endpoint.cloud,
        "api_key_ref": endpoint.api_key_ref,
    })
    _write_entries(target, entries)
    if cloud and api_key:
        from security.secret_vault import set_secret

        set_secret(f"provider:{name}", api_key)
    return {
        "name": endpoint.name,
        "base_url": endpoint.base_url,
        "model": endpoint.model,
        "cloud": endpoint.cloud,
        "api_key_ref": endpoint.api_key_ref,
        "key_configured": bool(endpoint.api_key_ref),
    }


def remove_provider(name: str, path: Path | None = None) -> bool:
    target = Path(path) if path else DEFAULT_ENDPOINTS_PATH
    entries = [
        e for e in _read_entries(target)
        if not (isinstance(e, dict) and e.get("name") == name)
    ]
    _write_entries(target, entries)
    return True
