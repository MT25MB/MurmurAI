"""Typed WebSocket protocol + in-memory session state.

These Pydantic models mirror `src/lib/websocket.ts` in the HUD. Everything is
ephemeral and local; nothing is persisted to disk or sent off-machine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent.plan_preview import PlanPreview


class ClientMessage(BaseModel):
    """Messages the HUD (or any local client) may send to the sidecar."""

    model_config = ConfigDict(extra="ignore")

    type: Literal[
        "ping", "state", "text_input", "audio_chunk", "confirm",
        "guidance_response", "abort_automation", "set_listening_mode",
        "update_available", "update_confirm", "update_status", "permission_status", "be_quiet",
        "set_muted",
    ]
    text: str | None = None
    muted: bool | None = None
    data: str | None = None  # base64 audio chunk
    request_id: str | None = None
    approved: bool | None = None
    mode: str | None = None  # "active" | "sleep"
    version: str | None = None  # update notification
    notes: str | None = None    # release summary
    detail: str | None = None   # update error/offline detail
    permissions: dict | None = None  # OS permission diagnostics from the shell


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
        "update_available",
        "update_install",
        "update_check_request",
        "transcript",
        "activity",
        "cursor",
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
    role: str | None = None      # transcript speaker (assistant | system)
    version: str | None = None   # update notification
    notes: str | None = None     # spoken release summary
    x: int | None = None         # cursor overlay: physical screen pixel
    y: int | None = None
    kind: str | None = None      # click | drag | type

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
    # Held, single-use plan preview. Cleared on approval, adjustment cancel, or
    # any unrelated utterance so a stale "yes" never executes an old plan.
    pending_plan: PlanPreview | None = None
    audio_chunks: int = 0
    # Lightweight per-session context for pronoun/"this"/"it" resolution.
    context: dict[str, object] = field(default_factory=dict)

    def remember(self, key: str, value: object) -> None:
        self.context[key] = value

    def recall(self, key: str) -> object | None:
        return self.context.get(key)

    def uptime(self) -> int:
        return int(time.monotonic() - self.started_at)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content})
        # Bound memory: keep the most recent 40 turns.
        if len(self.turns) > 40:
            self.turns = self.turns[-40:]
