"""Thread-safe bridge between synchronous tools and the async WebSocket HUD.

Tool functions (e.g. the installer) run inside a worker thread via the brain.
They need to (a) push live events to the HUD and (b) block until the user clicks
Approve in the HUD. This module provides that bridge without coupling tools to
FastAPI.

Flow:
  worker thread  --emit(ServerMessage)-->  event loop  --broadcast-->  HUD
  HUD "confirm"  --resolve_confirmation()-->  unblocks the waiting worker thread
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover - type-only, avoids circular import at runtime
    from agent.state import ServerMessage

logger = logging.getLogger("murmur_ai.tools.event_bus")


def _server_message_cls():
    """Lazily import ServerMessage to avoid the tools<->agent import cycle."""
    from agent.state import ServerMessage

    return ServerMessage


class ToolEventBus:
    """Global, thread-safe event + confirmation bridge (singleton: `tool_bus`)."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._emit_fn: Optional[Callable[[ServerMessage], None]] = None
        self._speak_fn: Optional[Callable[[str], None]] = None
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        # Spoken-safe metadata for remote/UIs: description + command only, no
        # tool arguments or secrets. Never mutated outside the lock.
        self._pending_meta: dict[str, dict[str, str]] = {}
        self._guidance: dict[str, tuple[threading.Event, dict]] = {}
        self._resolved: set[str] = set()
        self._lock = threading.Lock()

    # ---- configuration (called by main.py at startup) ----

    def configure(
        self,
        loop: asyncio.AbstractEventLoop,
        emit_fn: Callable[["ServerMessage"], None],
        speak_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._loop = loop
        self._emit_fn = emit_fn
        if speak_fn is not None:
            self._speak_fn = speak_fn

    def speak(self, text: str) -> None:
        """Speak text through the app's shared TTS, if configured."""
        if self._speak_fn is None:
            return
        try:
            self._speak_fn(text)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Spoken prompt failed")

    # ---- emitting ----

    def emit(self, message: "ServerMessage") -> None:
        """Emit a WS message to the HUD from any thread (non-blocking)."""
        if self._emit_fn is None:
            logger.debug("Event bus not configured; dropping %s event", message.type)
            return
        try:
            self._emit_fn(message)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to emit tool event")

    def progress(self, text: str, percent: Optional[int] = None) -> None:
        self.emit(_server_message_cls()(type="progress", text=text, percent=percent))

    # ---- confirmation ----

    def request_confirmation(
        self,
        description: str,
        command: str,
        timeout: float = 180.0,
    ) -> bool:
        """Emit CONFIRMATION_REQUIRED and block until the user answers.

        Returns True only on an explicit approval. Denials and timeouts return
        False (treated as 'no', per AGENTS.md).

        Only one approval may be held at a time: a second request is refused
        immediately rather than leaving two live "yes" targets. This mirrors
        Capri's single held action and keeps spoken approval unambiguous.
        """
        with self._lock:
            if self._pending:
                logger.info("Confirmation refused: another approval is already held")
                return False
            self._resolved.clear()
        request_id = uuid.uuid4().hex
        done = threading.Event()
        result: dict[str, bool] = {"approved": False}

        with self._lock:
            self._pending[request_id] = (done, result)
            self._pending_meta[request_id] = {
                "description": str(description),
                "command": str(command),
            }

        ServerMessage = _server_message_cls()
        self.emit(
            ServerMessage(
                type="confirmation_required",
                request_id=request_id,
                description=description,
                command=command,
            )
        )
        self.emit(ServerMessage(type="state", status="CONFIRMATION_REQUIRED"))

        # Speak the exact action and the verbal confirmation choices aloud so
        # a blind/low-vision user can act without looking at the HUD.
        spoken = (
            f"Approval needed. {description}. "
            f"The exact command is {command}. "
            "Say yes, confirm to approve, or no, cancel to stop."
        )
        self.speak(spoken)

        logger.info("Awaiting confirmation %s: %s", request_id, description)

        signalled = done.wait(timeout)
        with self._lock:
            self._pending.pop(request_id, None)
            self._pending_meta.pop(request_id, None)

        if not signalled:
            logger.info("Confirmation %s timed out", request_id)
            return False
        return bool(result["approved"])

    def resolve_confirmation(self, request_id: str, approved: bool) -> bool:
        """Resolve a pending confirmation from the async WS handler.

        Returns True if the request_id was found and resolved. Each approval is
        single-use: replaying a yes for an already-resolved request is refused.
        """
        with self._lock:
            if request_id in self._resolved:
                return False
            entry = self._pending.get(request_id)
            if entry is None:
                return False
            self._resolved.add(request_id)
            self._pending_meta.pop(request_id, None)
        done, result = entry
        result["approved"] = bool(approved)
        done.set()
        logger.info("Confirmation %s resolved: %s", request_id, approved)
        return True

    def drop_pending(self, reason: str) -> int:
        """Deny and discard every held approval (Capri's Security.Drop).

        Called when the user says anything that is not a yes or a no: the held
        action is cancelled rather than left waiting for a later "yes".
        Returns the number of approvals dropped.
        """
        with self._lock:
            held = list(self._pending.items())
            self._pending.clear()
            self._pending_meta.clear()
            for request_id in held:
                self._resolved.add(request_id[0])
        for request_id, (done, result) in held:
            result["approved"] = False
            done.set()
            logger.info("Confirmation %s dropped: %s", request_id, reason)
        return len(held)

    def has_pending(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._pending

    def pending_ids(self) -> list[str]:
        """Return IDs of all currently pending confirmations (insertion order)."""
        with self._lock:
            return list(self._pending.keys())

    def pending_details(self) -> list[dict[str, str]]:
        """Return spoken-safe pending approvals (id + description + command)."""
        with self._lock:
            return [
                {"request_id": rid, **dict(meta)}
                for rid, meta in self._pending_meta.items()
                if rid in self._pending
            ]

    # ---- guidance (ask the user verbally when stuck) ----

    def request_guidance(self, question: str, timeout: float = 120.0) -> Optional[str]:
        """Emit a spoken question and block until the user answers via HUD or voice.

        Returns the user's answer text, or None on timeout/denial.
        """
        request_id = uuid.uuid4().hex
        done = threading.Event()
        result: dict[str, Optional[str]] = {"text": None}

        with self._lock:
            self._guidance[request_id] = (done, result)

        ServerMessage = _server_message_cls()
        self.emit(
            ServerMessage(
                type="guidance_required",
                request_id=request_id,
                text=question,
            )
        )
        self.speak(question)
        logger.info("Awaiting guidance %s: %s", request_id, question)

        signalled = done.wait(timeout)
        with self._lock:
            self._guidance.pop(request_id, None)

        if not signalled:
            logger.info("Guidance %s timed out", request_id)
            self.emit(ServerMessage(type="error", detail="No guidance received; stopping automation."))
            return None
        return result["text"]

    def resolve_guidance(self, request_id: str, text: str) -> bool:
        with self._lock:
            entry = self._guidance.get(request_id)
        if entry is None:
            return False
        done, result = entry
        result["text"] = text
        done.set()
        logger.info("Guidance %s resolved: %s", request_id, text)
        return True

    def guidance_ids(self) -> list[str]:
        with self._lock:
            return list(self._guidance.keys())


# Module-level singleton used by all tools.
tool_bus = ToolEventBus()
