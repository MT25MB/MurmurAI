"""Typed WebSocket protocol + in-memory session state.

These Pydantic models mirror `src/lib/websocket.ts` in the HUD. Everything is
ephemeral and local; nothing is persisted to disk or sent off-machine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ClientMessage(BaseModel):
    """Messages the HUD (or any local client) may send to the sidecar."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "ping", "state", "text_input", "audio_chunk", "confirm",
        "guidance_response", "abort_automation",
    ]
    text: str | None = None
    data: str | None = None  # base64 audio chunk
    request_id: str | None = None
    approved: bool | None = None


class ServerMessage(BaseModel):
    """Messages the sidecar sends back to the HUD."""

    type: Literal[
        "pong",
        "state",
        "text_output",
        "audio_ack",
        "confirmation_required",
        "guidance_required",
        "automation_stopped",
        "progress",
        "pull_progress",
        "pull_complete",
        "error",
        "info",
    ]
    ts: float | None = None
    status: str | None = None
    uptime_s: int | None = None
    text: str | None = None
    chunks: int | None = None
    amplitude: float | None = None
    percent: int | None = None
    request_id: str | None = None
    description: str | None = None
    command: str | None = None
    model: str | None = None
    detail: str | None = None

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


@dataclass
class ConfirmationRequest:
    request_id: str
    description: str
    command: str
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class SessionState:
    """Per-connection conversational + agent state."""

    started_at: float = field(default_factory=time.monotonic)
    turns: list[dict[str, str]] = field(default_factory=list)
    pending: dict[str, ConfirmationRequest] = field(default_factory=dict)
    audio_chunks: int = 0

    def uptime(self) -> int:
        return int(time.monotonic() - self.started_at)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content})
        # Bound memory: keep the most recent 40 turns.
        if len(self.turns) > 40:
            self.turns = self.turns[-40:]
