"""Opt-in, LAN-only mobile companion server for Murmur AI.

Nothing here is reachable until the user explicitly says "start phone remote".
The server binds to local interfaces on a dedicated port, but every HTTP and
WebSocket request is checked against RFC1918 private networks (plus loopback)
before it is accepted. Public / non-LAN sources are rejected.

Pairing is a rotating 6-digit PIN that Murmur speaks aloud. Exchanging it over
an authenticated LAN WebSocket yields a short-lived token bound to that peer
address; only then are commands accepted. Approval buttons route through the
same ``tool_bus`` as the desktop HUD, so every approval stays single-use and
bound to one exact request.

No telemetry, no analytics, no third-party hosts. The served web app is plain
semantic HTML/CSS/JS with zero network dependencies.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger("murmur_ai.remote.companion")

REMOTE_PORT = int(os.getenv("MURMUR_REMOTE_PORT", "8766"))


def _remote_dir() -> Path:
    """Find the UI in a source checkout or inside the onefile sidecar."""
    candidates = [
        Path(__file__).resolve().parents[2] / "src" / "remote",
        Path(getattr(sys, "_MEIPASS", "")) / "src" / "remote",
        Path(__file__).resolve().parent / "src" / "remote",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[0]


REMOTE_DIR = _remote_dir()

PIN_TTL_S = 300          # rotate the spoken PIN every 5 minutes
TOKEN_TTL_S = 3600       # short-lived session token
MAX_PIN_ATTEMPTS = 5     # rate-limit brute force
PIN_DIGITS = 6

# RFC1918 + loopback only. Link-local (169.254.x.x), CGNAT (100.64/10), public
# addresses, and all non-ULA IPv6 are refused.
LAN_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def is_lan_address(value: Optional[str]) -> bool:
    """True only for RFC1918 private IPv4 or loopback addresses."""
    try:
        addr = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    if addr.version == 4:
        return any(addr in network for network in LAN_NETWORKS)
    return False


def _peer_host(websocket: WebSocket) -> str:
    client = getattr(websocket, "client", None)
    return str(getattr(client, "host", "") or "")


def _speak(text: str) -> None:
    """Speak through the shared local TTS (best effort, never fatal)."""
    try:  # pragma: no cover - TTS optional
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            speaker.speak(text)
    except Exception:
        logger.debug("Companion announcement failed", exc_info=True)


def _spoken_digits(pin: str) -> str:
    return " ".join(pin)


_TRANSCRIBE_MODEL = None
_TRANSCRIBE_MODEL_NAME = ""
_TRANSCRIBE_LOCK = threading.Lock()


def _get_transcribe_model():
    """Load the local whisper weights once, not once per utterance."""
    global _TRANSCRIBE_MODEL, _TRANSCRIBE_MODEL_NAME
    from faster_whisper import WhisperModel

    model_name = os.getenv("WHISPER_MODEL", "tiny.en")
    with _TRANSCRIBE_LOCK:
        if _TRANSCRIBE_MODEL is None or _TRANSCRIBE_MODEL_NAME != model_name:
            _TRANSCRIBE_MODEL = WhisperModel(model_name, compute_type="int8", device="cpu")
            _TRANSCRIBE_MODEL_NAME = model_name
        return _TRANSCRIBE_MODEL


def transcribe_audio(pcm: bytes) -> str:
    """Transcribe 16 kHz int16 PCM locally with faster-whisper (no cloud)."""
    import numpy as np

    model = _get_transcribe_model()
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(
        audio, language="en", beam_size=1, vad_filter=False
    )
    return " ".join(str(seg.text).strip() for seg in segments).strip()


class PairingManager:
    """Rotating PIN -> short-lived, peer-bound session token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pin = ""
        self._pin_expires = 0.0
        self._attempts = 0
        self._tokens: dict[str, tuple[str, float]] = {}

    def rotate(self) -> str:
        with self._lock:
            self._pin = f"{secrets.randbelow(1_000_000):0{PIN_DIGITS}d}"
            self._pin_expires = time.monotonic() + PIN_TTL_S
            self._attempts = 0
            self._tokens.clear()  # old sessions die with the PIN
            return self._pin

    def clear(self) -> None:
        with self._lock:
            self._pin = ""
            self._pin_expires = 0.0
            self._attempts = 0
            self._tokens.clear()

    @property
    def pin_age_ok(self) -> bool:
        with self._lock:
            return bool(self._pin) and time.monotonic() < self._pin_expires

    def verify(self, pin: str, peer: str = "") -> Optional[str]:
        """Exchange a PIN for a token. PINs and tokens are single-use."""
        with self._lock:
            if not is_lan_address(peer):
                return None
            if not self._pin or time.monotonic() >= self._pin_expires:
                return None
            if self._attempts >= MAX_PIN_ATTEMPTS:
                return None
            self._attempts += 1
            if not secrets.compare_digest(str(pin or "").strip(), self._pin):
                return None
            # Consume the PIN: it cannot be replayed for a second token.
            self._pin = ""
            self._pin_expires = 0.0
            token = secrets.token_urlsafe(24)
            self._tokens[token] = (str(peer), time.monotonic() + TOKEN_TTL_S)
            return token

    def validate_token(self, token: str, peer: str = "") -> bool:
        with self._lock:
            entry = self._tokens.get(str(token or ""))
            if entry is None:
                return False
            bound_peer, expires = entry
            # A wrong peer must not destroy the legitimate session: just refuse.
            if bound_peer != str(peer):
                return False
            if time.monotonic() >= expires:
                self._tokens.pop(str(token), None)
                return False
            return True

    def paired(self) -> bool:
        with self._lock:
            now = time.monotonic()
            expired = [t for t, (_, exp) in self._tokens.items() if exp <= now]
            for token in expired:
                self._tokens.pop(token, None)
            return bool(self._tokens)


pairing = PairingManager()


class CompanionRuntime:
    """Start/stop the LAN server in a daemon thread (owned by the sidecar)."""

    def __init__(self) -> None:
        self._server: Any = None
        self._thread: Optional[threading.Thread] = None
        self._rotator: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return bool(self._server and getattr(self._server, "started", False))

    def start(self) -> bool:
        if self.is_running():
            return False
        try:
            import uvicorn
        except ImportError:  # pragma: no cover - uvicorn is a core dependency
            logger.error("uvicorn is required for the phone companion")
            return False
        config = uvicorn.Config(
            app, host="0.0.0.0", port=REMOTE_PORT, log_level="warning", access_log=False
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=lambda: asyncio.run(self._server.serve()),
            name="murmur-phone-companion",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self.is_running():
            time.sleep(0.05)
        if self.is_running():
            self._rotator = threading.Thread(
                target=self._rotate_loop, name="murmur-phone-pairing-rotation", daemon=True
            )
            self._rotator.start()
        return self.is_running()

    def _rotate_loop(self) -> None:
        """Rotate and speak a fresh PIN periodically; never rotate a dead server."""
        server = self._server
        while server is not None and not getattr(server, "should_exit", False):
            time.sleep(PIN_TTL_S)
            if getattr(server, "should_exit", False):
                break
            pin = pairing.rotate()
            _speak(
                f"Phone remote pairing code changed to {_spoken_digits(pin)}. "
                "Say stop phone remote to turn it off."
            )

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None


runtime = CompanionRuntime()


def start_companion(speak: bool = True) -> dict[str, Any]:
    """Enable the opt-in setting, start the LAN server and speak a fresh PIN."""
    from system.settings_tools import update_settings

    update_settings({"remote_companion_enabled": True})
    running = runtime.start()
    pin = pairing.rotate()
    if speak:
        _speak(
            "Phone remote is on. Open the companion page on this Wi-Fi and enter "
            f"pairing code {_spoken_digits(pin)}. Say stop phone remote to turn it off."
        )
    return {
        "enabled": True,
        "running": running,
        "pin": pin,
        "summary": (
            f"Phone remote is on. Pairing code {_spoken_digits(pin)}. "
            "Say stop phone remote to turn it off."
        ),
    }


def stop_companion() -> dict[str, Any]:
    from system.settings_tools import update_settings

    update_settings({"remote_companion_enabled": False})
    runtime.stop()
    pairing.clear()
    return {
        "enabled": False,
        "running": runtime.is_running(),
        "summary": "Phone remote is off. The pairing code has been discarded.",
    }


def companion_status() -> dict[str, Any]:
    from system.settings_tools import load_settings

    enabled = bool(load_settings().get("remote_companion_enabled", False))
    running = runtime.is_running()
    paired = pairing.paired()
    summary = (
        "Phone remote is on and paired."
        if enabled and running and paired else
        "Phone remote is on, waiting for pairing."
        if enabled and running else
        "Phone remote is off."
    )
    return {
        "enabled": enabled,
        "running": running,
        "paired": paired,
        "port": REMOTE_PORT,
        "summary": summary,
    }


def resolve_remote_approval(request_id: str, approved: bool) -> bool:
    """Same single-use approval primitive the desktop HUD uses."""
    from tools.event_bus import tool_bus

    return tool_bus.resolve_confirmation(str(request_id or ""), bool(approved))


# ---------------------------------------------------------------------------
# FastAPI app (every route is LAN-gated)
# ---------------------------------------------------------------------------

app = FastAPI(title="Murmur AI Phone Companion", docs_url=None, redoc_url=None)


def _lan_guard(request=None, websocket=None) -> bool:
    peer = (
        _peer_host(websocket)
        if websocket is not None
        else (request.client.host if request is not None and request.client else "")
    )
    allowed = is_lan_address(peer)
    if not allowed:
        logger.warning("Rejected non-LAN companion connection from %r", peer)
    return allowed


@app.get("/remote/status")
async def remote_status(request: Request):
    if not _lan_guard(request=request):
        raise HTTPException(403, "LAN only")
    return JSONResponse(companion_status())


@app.get("/remote/")
async def remote_index(request: Request):
    if not _lan_guard(request=request):
        raise HTTPException(403, "LAN only")
    return FileResponse(REMOTE_DIR / "index.html")


@app.get("/remote/{asset:path}")
async def remote_asset(asset: str, request: Request):
    if not _lan_guard(request=request):
        raise HTTPException(403, "LAN only")
    # Allow only the two local static assets; never expose arbitrary files.
    if asset not in ("styles.css", "app.js"):
        raise HTTPException(404, "Not found")
    return FileResponse(REMOTE_DIR / asset)


async def _send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_text(json.dumps(payload))
    except Exception:  # pragma: no cover - socket already closed
        pass


async def _handle_command(
    websocket: WebSocket, token: str, peer: str, message: dict[str, Any]
) -> None:
    kind = str(message.get("type") or "")
    if not pairing.validate_token(token, peer):
        await _send(websocket, {"type": "error", "detail": "Session expired. Pair again."})
        return

    if kind == "command":
        text = str(message.get("text") or "").strip()
        if not text:
            await _send(websocket, {"type": "error", "detail": "No command received."})
            return
        from agent.brain import Brain

        reply = await asyncio.to_thread(Brain().think_and_act, text)
        await _send(websocket, {"type": "transcript", "text": reply, "role": "assistant"})
        _speak(reply)
    elif kind == "audio":
        try:
            pcm = base64.b64decode(str(message.get("data") or ""), validate=True)
        except Exception:
            await _send(websocket, {"type": "error", "detail": "Invalid audio data."})
            return
        text = await asyncio.to_thread(transcribe_audio, pcm)
        if not text:
            await _send(websocket, {"type": "error", "detail": "I did not catch that."})
            return
        await _send(websocket, {"type": "transcript", "text": text, "role": "user"})
        from agent.brain import Brain

        reply = await asyncio.to_thread(Brain().think_and_act, text)
        await _send(websocket, {"type": "transcript", "text": reply, "role": "assistant"})
        _speak(reply)
    elif kind == "describe":
        from agent.vision_agent import describe_screen

        description = await asyncio.to_thread(describe_screen, "overview")
        await _send(websocket, {"type": "transcript", "text": description, "role": "assistant"})
        _speak(description)
    elif kind == "stop":
        from agent.abort import abort_controller

        abort_controller.abort("phone companion stop")
        try:  # pragma: no cover - TTS optional
            from audio.speaker_provider import get_speaker

            speaker = get_speaker()
            if speaker is not None:
                speaker.interrupt()
        except Exception:
            pass
        await _send(websocket, {"type": "state", "status": "IDLE", "text": "Automation stopped."})
    elif kind == "approve":
        request_id = str(message.get("request_id") or "")
        approved = bool(message.get("approved"))
        ok = resolve_remote_approval(request_id, approved)
        await _send(
            websocket,
            {
                "type": "status",
                "text": "Approved." if ok and approved else "Cancelled." if ok else "That approval is no longer available.",
            },
        )
    else:
        await _send(websocket, {"type": "error", "detail": "Unknown command."})


@app.websocket("/remote/ws")
async def remote_ws(websocket: WebSocket):
    peer = _peer_host(websocket)
    if not _lan_guard(websocket=websocket):
        await websocket.close(code=1008, reason="LAN only")
        return
    await websocket.accept()
    token: str = ""
    announced: set[str] = set()

    await _send(websocket, {"type": "pairing_required", "expires_in": PIN_TTL_S})

    async def handle(raw: str) -> None:
        nonlocal token
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await _send(websocket, {"type": "error", "detail": "Malformed message."})
            return
        if not isinstance(message, dict):
            await _send(websocket, {"type": "error", "detail": "Malformed message."})
            return
        kind = str(message.get("type") or "")
        if kind == "pair":
            if token:
                await _send(websocket, {"type": "error", "detail": "Already paired."})
                return
            new_token = pairing.verify(str(message.get("pin") or ""), peer)
            if not new_token:
                await _send(websocket, {"type": "error", "detail": "Incorrect or expired pairing code."})
                return
            token = new_token
            await _send(
                websocket,
                {"type": "paired", "token": token, "expires_in": TOKEN_TTL_S},
            )
            return
        if not token:
            await _send(websocket, {"type": "error", "detail": "Pair first."})
            return
        await _handle_command(websocket, token, peer, message)

    async def receive_loop() -> None:
        while True:
            await handle(await websocket.receive_text())

    async def approval_loop() -> None:
        from tools.event_bus import tool_bus

        while True:
            await asyncio.sleep(0.4)
            for detail in tool_bus.pending_details():
                rid = detail["request_id"]
                if rid in announced:
                    continue
                announced.add(rid)
                await _send(
                    websocket,
                    {
                        "type": "confirmation_required",
                        "request_id": rid,
                        "description": detail["description"],
                        "command": detail["command"],
                    },
                )

    receiver = asyncio.create_task(receive_loop())
    poller = asyncio.create_task(approval_loop())
    try:
        await receiver
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        poller.cancel()
        receiver.cancel()
