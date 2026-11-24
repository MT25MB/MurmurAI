"""Resolve Ollama's host setting into a usable client base URL.

Ollama treats ``OLLAMA_HOST`` as a *listen* address, so ``0.0.0.0`` (or
``0.0.0.0:11434``) is a perfectly normal value. Murmur AI treats the same
variable as a client base URL for httpx, which rejects a bare host with
"Request URL is missing an 'http://' or 'https://' protocol". Normalize at the
input boundary so a listen-style value still produces an absolute loopback URL.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_PORT = 11434
_LOOPBACK_WILDCARDS = {"0.0.0.0", "::", ""}


def normalize_ollama_host(value: str | None) -> str:
    """Return an absolute http(s) base URL for the local Ollama server."""
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_OLLAMA_HOST
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        hostname = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return DEFAULT_OLLAMA_HOST
    if scheme not in {"http", "https"}:
        return DEFAULT_OLLAMA_HOST
    if hostname in _LOOPBACK_WILDCARDS or not hostname:
        hostname = "127.0.0.1"
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{netloc}:{port if port is not None else DEFAULT_OLLAMA_PORT}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", "")).rstrip("/")


def ollama_host() -> str:
    """Read and normalize ``OLLAMA_HOST`` at call time."""
    return normalize_ollama_host(os.getenv("OLLAMA_HOST"))
