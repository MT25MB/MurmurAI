"""Murmur AI backend sidecar — FastAPI + WebSocket control plane.

Runs on 127.0.0.1:8765 and drives the voice agent loop:
  IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE
with a CONFIRMATION_REQUIRED branch for destructive OS actions.

Spawned and killed by the Tauri shell. The HUD connects to ws://127.0.0.1:8765/ws.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from agent.brain import Brain
from agent.state import SessionState, ServerMessage
from audio.listener import VoiceListener
from audio.speaker import LocalSpeaker
from audio.speaker_provider import set_speaker as register_speaker
from agent.abort import abort_controller, is_abort_phrase
from tools.safety import SafetyGate
from tools.event_bus import tool_bus
import setup as setup_module

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("murmur_ai.backend")

BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8765"))


class AppState:
    """Shared runtime state across WebSocket connections."""

    def __init__(self) -> None:
        self.brain = Brain()
        self.listener: Optional[VoiceListener] = None
        self.speaker: Optional[LocalSpeaker] = None
        self.sessions: dict[str, SessionState] = {}
        self.listening_task: Optional[asyncio.Task] = None
        self.speaking_task: Optional[asyncio.Task] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.hud_sockets: set[WebSocket] = set()
        self.send_locks: dict[int, asyncio.Lock] = {}
        self.setup_task: Optional[asyncio.Task] = None
        self._shutting_down = False

    def session_for(self, websocket: WebSocket) -> SessionState:
        sid = id(websocket)
        if sid not in self.sessions:
            self.sessions[sid] = SessionState()
        return self.sessions[sid]


app_state = AppState()


# ---- lifespan: start/stop background audio workers ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    app_state.loop = loop

    # Wire the tool event bus so tools can push progress to all HUDs and
    # speak confirmation prompts aloud for blind/low-vision users.
    def emit_from_tool(message: ServerMessage) -> None:
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_to_huds(message), loop)

    def speak_from_tool(text: str) -> None:
        speaker = app_state.speaker
        if speaker is not None:
            speaker.speak(text)

    tool_bus.configure(loop, emit_from_tool, speak_fn=speak_from_tool)

    logger.info("Murmur AI backend starting on %s:%s", BACKEND_HOST, BACKEND_PORT)
    try:
        app_state.speaker = LocalSpeaker(
            engine=os.getenv("TTS_ENGINE", "auto"),
            kokoro_voice=os.getenv("KOKORO_VOICE", "af_heart"),
            piper_model=os.getenv("PIPER_MODEL") or None,
        )
        register_speaker(app_state.speaker)
        logger.info("TTS speaker initialized")
    except Exception:
        logger.exception("TTS speaker init failed; continuing without TTS")
        app_state.speaker = None
        register_speaker(None)

    # On first launch, download local STT/TTS weights into ~/.murmur-ai/models/.
    # Runs in the background so the control plane starts immediately.
    app_state.setup_task = asyncio.create_task(setup_module.ensure_local_weights())

    yield

    app_state._shutting_down = True
    if app_state.setup_task:
        app_state.setup_task.cancel()
    if app_state.listening_task:
        app_state.listening_task.cancel()
    if app_state.speaking_task:
        app_state.speaking_task.cancel()
    if app_state.listener:
        try:
            app_state.listener.stop()
        except Exception:
            logger.exception("Failed to stop listener")
    if app_state.speaker:
        try:
            app_state.speaker.interrupt()
        except Exception:
            logger.exception("Failed to interrupt speaker")
    logger.info("Murmur AI backend shut down")


app = FastAPI(title="Murmur AI Local Voice Sidecar", lifespan=lifespan)


# ---- HTTP ----

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "Murmur AI-backend",
            "tts": app_state.speaker is not None,
            "listening": app_state.listening_task is not None
            and not app_state.listening_task.done(),
        }
    )


# ---- first-run setup HTTP endpoints ----

@app.get("/setup/status")
async def setup_status() -> JSONResponse:
    return JSONResponse(setup_module.get_setup_status())


@app.get("/setup/permissions")
async def setup_permissions() -> JSONResponse:
    return JSONResponse(setup_module.permission_status())


@app.post("/setup/permissions/prompt")
async def setup_permissions_prompt() -> JSONResponse:
    """Trigger the OS accessibility permission prompt (macOS) / re-check state."""
    return JSONResponse(setup_module.request_accessibility_prompt())


@app.post("/setup/install-ollama")
async def setup_install_ollama() -> JSONResponse:
    return JSONResponse(setup_module.install_ollama_instructions())


@app.post("/setup/complete")
async def setup_complete() -> JSONResponse:
    return JSONResponse(setup_module.mark_setup_complete())


@app.post("/setup/reset")
async def setup_reset() -> JSONResponse:
    return JSONResponse(setup_module.reset_setup())


# ---- model pull WebSocket (streams Ollama /api/pull progress) ----

@app.websocket("/setup/pull-model")
async def setup_pull_model(websocket: WebSocket):
    await websocket.accept()
    logger.info("Setup pull-model client connected")

    progress_tasks: set[asyncio.Task] = set()

    async def send_progress(label: str, percent: Optional[int], status: str, model: str) -> None:
        await websocket.send_text(
            ServerMessage(
                type="pull_progress",
                model=model,
                text=status,
                percent=percent,
                detail=label,
            ).to_json()
        )

    def on_progress(label: str, percent: Optional[int], status: str) -> None:
        # Keep a strong reference so the send task is never GC'd mid-flight.
        task = asyncio.create_task(send_progress(label, percent, status, model_name))
        progress_tasks.add(task)
        task.add_done_callback(progress_tasks.discard)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    ServerMessage(type="error", detail="Invalid JSON.").to_json()
                )
                continue

            model_name = str(data.get("model", ""))
            result = await setup_module.pull_model(model_name, on_progress)
            # Ensure all progress frames are flushed before the terminal message.
            if progress_tasks:
                await asyncio.gather(*list(progress_tasks), return_exceptions=True)
            if result.get("ok"):
                await websocket.send_text(
                    ServerMessage(
                        type="pull_complete",
                        model=result["model"],
                        text=f"{result['model']} is ready.",
                    ).to_json()
                )
            else:
                await websocket.send_text(
                    ServerMessage(
                        type="error",
                        detail=result.get("error", "Pull failed."),
                    ).to_json()
                )
    except WebSocketDisconnect:
        logger.info("Setup pull-model client disconnected")
    except Exception:
        logger.exception("Setup pull-model endpoint error")


# ---- WebSocket broadcast (used by tool threads) ----

async def broadcast_to_huds(message: ServerMessage) -> None:
    """Send a message to every connected HUD safely."""
    payload = message.to_json()
    for socket in list(app_state.hud_sockets):
        lock = app_state.send_locks.get(id(socket))
        try:
            if lock:
                async with lock:
                    await socket.send_text(payload)
            else:
                await socket.send_text(payload)
        except Exception:  # pragma: no cover - connection may be closing
            logger.debug("Failed to broadcast to a HUD", exc_info=True)


# ---- WebSocket control plane ----

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    session = app_state.session_for(websocket)
    app_state.hud_sockets.add(websocket)
    app_state.send_locks[id(websocket)] = asyncio.Lock()
    logger.info("HUD connected (session %s)", id(websocket))

    async def send(msg: ServerMessage) -> None:
        async with app_state.send_locks[id(websocket)]:
            await websocket.send_text(msg.to_json())

    # Greet with current state.
    await send(ServerMessage(type="state", status="IDLE", uptime_s=session.uptime()))

    try:
        while True:
            raw = await websocket.receive_text()
            import json

            try:
                from agent.state import ClientMessage
                msg = ClientMessage.model_validate_json(raw)
            except Exception as exc:
                logger.warning("Malformed client message: %s", exc)
                await send(ServerMessage(type="error", detail="Malformed message"))
                continue

            if msg.type == "ping":
                await send(
                    ServerMessage(type="pong", ts=time.time(), uptime_s=session.uptime())
                )

            elif msg.type == "state":
                await send(
                    ServerMessage(
                        type="state",
                        status="IDLE",
                        uptime_s=session.uptime(),
                    )
                )

            elif msg.type == "text_input":
                # Run in a background task so the receive loop stays free to
                # handle confirmations/progress during long tool calls (installs).
                asyncio.create_task(handle_text_input(session, send, msg.text or ""))

            elif msg.type == "confirm":
                # Tool-side confirmations (installer, etc.) block a worker thread.
                if tool_bus.resolve_confirmation(msg.request_id or "", bool(msg.approved)):
                    await send(
                        ServerMessage(
                            type="info",
                            text="Approved — starting installation." if msg.approved else "Cancelled.",
                        )
                    )
                else:
                    # Legacy safety-gate confirmation: re-run the brain with approval.
                    await handle_confirm(session, send, msg.request_id, bool(msg.approved))

            elif msg.type == "guidance_response":
                # Free-text answer to a spoken "I'm stuck, what should I do?" prompt.
                if tool_bus.resolve_guidance(msg.request_id or "", msg.text or ""):
                    await send(ServerMessage(type="info", text="Guidance received."))

            elif msg.type == "abort_automation":
                # UI abort button: halt the running vision loop immediately.
                abort_controller.abort(msg.text or "user pressed stop in the HUD")
                await send(
                    ServerMessage(
                        type="automation_stopped",
                        text=f"Automation stopped. {abort_controller.reason}",
                    )
                )

            elif msg.type == "audio_chunk":
                # Streaming audio from the HUD (optional path).
                logger.debug("Received audio chunk (%s bytes)", len(msg.data or ""))

    except WebSocketDisconnect:
        logger.info("HUD disconnected (session %s)", id(websocket))
    finally:
        session.pending.clear()
        app_state.hud_sockets.discard(websocket)
        app_state.send_locks.pop(id(websocket), None)
        if id(websocket) in app_state.sessions:
            del app_state.sessions[id(websocket)]


# ---- handlers ----

async def handle_text_input(
    session: SessionState, send, text: str
) -> None:
    """Full voice turn: transcribe already done; think, act, speak."""
    session.add_turn("user", text)
    # If the user is answering a spoken confirmation, handle it here instead of
    # sending "yes"/"no" to the model.
    if _try_verbal_confirmation(text) is not None:
        await send(ServerMessage(type="text_output", text=text))
        return
    await _set_state(send, session, "THINKING")

    try:
        # Offload the synchronous Ollama/tool loop so the event loop keeps
        # streaming progress and accepting confirmations during installs.
        reply = await asyncio.to_thread(
            app_state.brain.think_and_act,
            user_text=text,
            conversation_history=session.turns,
        )
    except Exception:
        logger.exception("Brain turn failed")
        await _set_state(send, session, "IDLE")
        await send(ServerMessage(type="error", detail="I had trouble thinking that through."))
        return

    session.add_turn("assistant", reply)
    await _speak_and_return(session, send, reply)


async def handle_confirm(
    session: SessionState, send, request_id: Optional[str], approved: bool
) -> None:
    """User answered a confirmation request from a destructive tool."""
    pending = session.pending.get(request_id) if request_id else None
    if not pending:
        await send(ServerMessage(type="error", detail="No pending confirmation."))
        await _set_state(send, session, "IDLE")
        return

    if approved:
        # Re-run the brain with approval so the tool proceeds.
        # The brain's confirm_callback returns True for this request_id.
        app_state.brain.safety.confirm_callback = lambda desc, cmd: True
        reply = await asyncio.to_thread(
            app_state.brain.think_and_act,
            user_text=f"User confirmed: {pending.description}",
            conversation_history=session.turns,
        )
        session.add_turn("assistant", reply)
        await _speak_and_return(session, send, reply)
    else:
        session.add_turn("assistant", "Cancelled.")
        await send(ServerMessage(type="text_output", text="Cancelled."))
        await _set_state(send, session, "IDLE")

    session.pending.pop(request_id, None)


# ---- verbal confirmation ----

import re as _re

_YES_RE = _re.compile(
    r"\b(yes|yeah|yep|yup|confirm|confirmed|approve|approved|okay|ok|"
    r"sure|go ahead|do it|allow|please do|yes please|yes confirm)\b",
    _re.IGNORECASE,
)
_NO_RE = _re.compile(
    r"\b(no|nope|nah|never|cancel|cancelled|deny|denied|stop|abort|"
    r"don't|do not|no cancel|no thanks)\b",
    _re.IGNORECASE,
)


def _try_verbal_confirmation(text: str) -> Optional[bool]:
    """If a confirmation is pending and the text says yes/no, resolve it.

    Returns True if a pending confirmation was consumed (approved or denied),
    False otherwise. 'no' takes precedence to be fail-safe.
    """
    pending = tool_bus.pending_ids()

    # A dedicated stop phrase halts automation regardless of pending state,
    # and denies any pending confirmation (fail-safe = no).
    if is_abort_phrase(text):
        abort_controller.abort("user said stop")
        if pending:
            tool_bus.resolve_confirmation(pending[-1], False)
        return None

    # If we're waiting for stuck-guidance, any spoken text is the answer.
    guidance_pending = tool_bus.guidance_ids()
    if guidance_pending and not pending:
        tool_bus.resolve_guidance(guidance_pending[-1], text)
        return False  # consumed as guidance, not a yes/no confirmation

    if not pending:
        return None
    denied = bool(_NO_RE.search(text))
    approved = bool(_YES_RE.search(text))
    if not (denied or approved):
        return None
    decision = False if denied else approved
    # Resolve the most recent pending request.
    request_id = pending[-1]
    tool_bus.resolve_confirmation(request_id, decision)
    logger.info("Verbal confirmation %s for %s (heard: %r)", decision, request_id, text)
    _chime("confirmation" if decision else "error")
    if app_state.speaker is not None:
        app_state.speaker.speak("Approved." if decision else "Cancelled.")
    return decision


# ---- state helpers ----

def _chime(kind: str) -> None:
    """Play a state-transition earcon if the user enabled them."""
    if app_state.speaker is not None:
        try:
            app_state.speaker.chime(kind)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Earcon failed", exc_info=True)


async def _set_state(send, session: SessionState, status: str) -> None:
    await send(ServerMessage(type="state", status=status, uptime_s=session.uptime()))
    cue = {
        "LISTENING": "listening",
        "THINKING": "thinking",
        "SPEAKING": "speaking",
        "CONFIRMATION_REQUIRED": "confirmation",
    }.get(status)
    if cue:
        _chime(cue)


async def _speak_and_return(session: SessionState, send, reply: str) -> None:
    """Speak the reply, then return to IDLE (listening)."""
    await _set_state(send, session, "SPEAKING")
    if app_state.speaker:
        try:
            app_state.speaker.speak(reply)
        except Exception:
            logger.exception("TTS speak failed")
    # Give the UI a moment to show SPEAKING, then go idle.
    await asyncio.sleep(0.25)
    await _set_state(send, session, "IDLE")


# ---- voice loop (started by the HUD or auto on connect) ----

async def start_listening(session: SessionState, send) -> None:
    """Begin the continuous listen -> transcribe -> think -> speak loop."""
    if app_state.listening_task and not app_state.listening_task.done():
        return  # already listening

    app_state.listener = VoiceListener(
        model_name=os.getenv("WHISPER_MODEL", "base.en"),
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        silence_ms=int(os.getenv("VAD_SILENCE_MS", "800")),
    )

    def on_utterance(text: str) -> None:
        session.add_turn("user", text)
        loop = app_state.loop or asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            _on_utterance_async(session, send, text), loop
        )

    app_state.listener.on_utterance = on_utterance
    app_state.listener.start()
    app_state.listening_task = asyncio.create_task(_listen_amplitude(session, send))
    await _set_state(send, session, "LISTENING")


async def _on_utterance_async(session, send, text: str) -> None:
    # Verbal "yes, confirm" / "no, cancel" can answer a pending spoken prompt.
    if _try_verbal_confirmation(text) is not None:
        await send(ServerMessage(type="text_output", text=text))
        return
    await _set_state(send, session, "THINKING")
    try:
        reply = await asyncio.to_thread(
            app_state.brain.think_and_act,
            user_text=text,
            conversation_history=session.turns,
        )
    except Exception:
        logger.exception("Brain turn failed")
        await _set_state(send, session, "IDLE")
        await send(ServerMessage(type="error", detail="I had trouble thinking that through."))
        return

    session.add_turn("assistant", reply)
    await _speak_and_return(session, send, reply)
    await _set_state(send, session, "LISTENING")


async def _listen_amplitude(session: SessionState, send) -> None:
    """Broadcast live RMS amplitude while listening (for the waveform)."""
    import sounddevice as sd

    try:
        stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            blocksize=int(16000 * 0.05),  # 50 ms blocks
        )
        with stream:
            while not app_state._shutting_down:
                indata, _ = stream.read(1600)
                rms = float((indata ** 2).mean() ** 0.5) if indata.size else 0.0
                # 0..1-ish amplitude for the UI.
                amp = min(rms * 8.0, 1.0)
                await send(
                    ServerMessage(
                        type="state",
                        status="LISTENING",
                        uptime_s=session.uptime(),
                        amplitude=amp,
                    )
                )
                await asyncio.sleep(0.05)
    except Exception:
        logger.exception("Amplitude stream stopped")


# ---- entrypoint ----

def main() -> None:
    import uvicorn

    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, log_level="info")


if __name__ == "__main__":
    main()
