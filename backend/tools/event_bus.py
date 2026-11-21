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
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._lock = threading.Lock()

    # ---- configuration (called by main.py at startup) ----

    def configure(
        self,
        loop: asyncio.AbstractEventLoop,
        emit_fn: Callable[["ServerMessage"], None],
    ) -> None:
        self._loop = loop
        self._emit_fn = emit_fn

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
        """
        request_id = uuid.uuid4().hex
        done = threading.Event()
        result: dict[str, bool] = {"approved": False}

        with self._lock:
            self._pending[request_id] = (done, result)

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
        logger.info("Awaiting confirmation %s: %s", request_id, description)

        signalled = done.wait(timeout)
        with self._lock:
            self._pending.pop(request_id, None)

        if not signalled:
            logger.info("Confirmation %s timed out", request_id)
            return False
        return bool(result["approved"])

    def resolve_confirmation(self, request_id: str, approved: bool) -> bool:
        """Resolve a pending confirmation from the async WS handler.

        Returns True if the request_id was found and resolved.
        """
        with self._lock:
            entry = self._pending.get(request_id)
        if entry is None:
            return False
        done, result = entry
        result["approved"] = bool(approved)
        done.set()
        logger.info("Confirmation %s resolved: %s", request_id, approved)
        return True

    def has_pending(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._pending


# Module-level singleton used by all tools.
tool_bus = ToolEventBus()
