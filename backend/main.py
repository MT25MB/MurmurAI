"""Murmur AI backend sidecar: FastAPI + WebSocket control plane.

Runs on 127.0.0.1:8765 and drives the voice agent loop:
  IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE
with a CONFIRMATION_REQUIRED branch for destructive OS actions.

Spawned and killed by the Tauri shell. The HUD connects to ws://127.0.0.1:8765/ws.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import time
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import agent.brain as brain_module
from agent.brain import Brain
from agent.plan_preview import (
    MULTI_STEP_RE,
    classify as classify_plan,
    pick_engine,
    should_auto_preview,
)
from agent.state import SessionState, ServerMessage
from audio.dictation import DictationSession, START_RE as DICTATION_START_RE
from audio.listener import VoiceListener
from audio.speaker import LocalSpeaker
from audio.speaker_provider import set_speaker as register_speaker
from agent.abort import abort_controller, is_abort_phrase
from tools.safety import SafetyGate
from tools.event_bus import tool_bus
from tools import text_edit_tools
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
        # One agent turn at a time: two quick utterances must not run competing
        # tool loops and interleave state frames.
        self.turn_lock = asyncio.Lock()
        self.listening_task: Optional[asyncio.Task] = None
        self.speaking_task: Optional[asyncio.Task] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.hud_sockets: set[WebSocket] = set()
        self.send_locks: dict[int, asyncio.Lock] = {}
        self.setup_task: Optional[asyncio.Task] = None
        # Voice dictation is a local mode: speech is typed, never treated as a
        # tool command until "stop dictating" or a command trigger.
        self.dictation = DictationSession()
        # Sleep/wake state machine: "active" (continuous VAD) or "sleep" (wake-word only).
        self.listening_mode = "active"
        self.wake_detector = None
        self.wake_task: Optional[asyncio.Task] = None
        # Hardware profile + latency warm-up tasks (see system/profiler.py).
        self.hardware_config: Optional[dict] = None
        # Pending spoken update prompt: {request_id, version, notes}.
        self.pending_update: Optional[dict] = None
        self.warm_task: Optional[asyncio.Task] = None
        self.prewarm_task: Optional[asyncio.Task] = None
        self.plugin_task: Optional[asyncio.Task] = None
        self.demo: Optional[object] = None  # active guided practice session
        self.os_permissions: Optional[dict] = None  # from the Tauri shell
        # HUD mute is an explicit runtime switch: utterances are ignored but the
        # listener keeps running so unmuting is instant and the waveform stays live.
        self.muted = False
        # Typed commands get text replies only; spoken turns use local TTS.
        self.last_input_mode = "voice"
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
        # Confirmation prompts are urgent: preempt queued narration.
        speaker = app_state.speaker
        if speaker is not None:
            if hasattr(speaker, "speak_priority"):
                from audio.speech_queue import SpeechPriority

                speaker.speak_priority(text, SpeechPriority.INTERRUPT)
            else:
                speaker.speak(text)

    tool_bus.configure(loop, emit_from_tool, speak_fn=speak_from_tool)

    # The brain runs Ollama on a worker thread; surface each step to every HUD
    # and speak it in voice mode so the user always knows what is happening.
    async def broadcast_activity(text: str) -> None:
        await broadcast_to_huds(ServerMessage(type="activity", text=text))
        await broadcast_to_huds(ServerMessage(type="transcript", text=text, role="system"))
        if app_state.speaker and getattr(app_state, "last_input_mode", "voice") != "typed":
            try:
                await asyncio.to_thread(app_state.speaker.speak, text)
            except Exception:  # pragma: no cover - TTS dependent
                logger.debug("Activity narration failed", exc_info=True)

    def activity_from_brain(text: str) -> None:
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(broadcast_activity(text), loop)

    brain_module.set_activity_callback(activity_from_brain)

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

    # Profile the machine and apply the best model tier before any model is
    # used. Environment variables / saved settings overrides always win.
    try:
        app_state.hardware_config = setup_module.configure_from_hardware()
        app_state.brain.model = app_state.hardware_config["chat_model"]
        app_state.brain.vision_model = app_state.hardware_config["vision_model"]
    except Exception:
        logger.exception("Hardware profiling failed; using default model tier")

    # Apply persisted voice/listening/model preferences to the live runtime.
    try:
        from system import settings_tools

        settings_tools.apply_settings()
    except Exception:
        logger.exception("Could not apply saved settings")

    # On first launch, download local STT/TTS weights into ~/.murmur-ai/models/.
    # Runs in the background so the control plane starts immediately.
    app_state.setup_task = asyncio.create_task(setup_module.ensure_local_weights())
    # Keep Ollama models warm and pre-import TTS/VAD so the first command and
    # first greeting have no cold-start stutter. All non-fatal, background.
    app_state.warm_task = asyncio.create_task(setup_module.warm_models())
    app_state.prewarm_task = asyncio.create_task(
        asyncio.to_thread(setup_module.prewarm_audio_on_startup, app_state.speaker)
    )

    # Load local MCP plugin tools in the background. Missing/broken servers are
    # collected as non-fatal errors and reported by "what plugins are active".
    from tools import mcp_manager

    app_state.plugin_task = asyncio.create_task(
        asyncio.to_thread(mcp_manager.manager.reload)
    )

    yield

    app_state._shutting_down = True
    if app_state.setup_task:
        app_state.setup_task.cancel()
    if app_state.warm_task:
        app_state.warm_task.cancel()
    if app_state.prewarm_task:
        app_state.prewarm_task.cancel()
    if app_state.plugin_task:
        app_state.plugin_task.cancel()
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


# Browsers can open ws://127.0.0.1 from any website; CORS does not apply to
# WebSocket handshakes. Only the local Tauri webview and localhost dev origins
# may drive the agent. Clients without an Origin header (native CLI/tests) pass.
_WS_ORIGIN_ALLOW = re.compile(
    r"^(tauri://localhost|https?://tauri\.localhost|"
    r"https?://(localhost|127\.0\.0\.1)(:\d+)?)$",
    re.IGNORECASE,
)


def _ws_origin_allowed(websocket: WebSocket) -> bool:
    headers = getattr(websocket, "headers", {})
    origin = headers.get("origin") if headers else None
    return not origin or bool(_WS_ORIGIN_ALLOW.match(origin.strip()))


app = FastAPI(title="Murmur AI Local Voice Sidecar", lifespan=lifespan)

# Set by main() so the Tauri shell can ask us to exit cleanly. A clean exit lets
# PyInstaller remove its onefile extraction directory; a hard kill leaves a
# ~744 MB _MEI* dir behind on every quit until the disk fills up.
_uvicorn_server: Optional[object] = None

# The Tauri webview runs on a different origin (tauri://localhost on macOS/Linux,
# http://tauri.localhost on Windows) than this localhost API. Without CORS the
# browser blocks every /setup/* fetch with "Failed to fetch". The server only
# binds 127.0.0.1, so allowing the local webview origins is safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
    ],
    allow_origin_regex=(
        r"^(tauri://localhost|https?://tauri\.localhost|"
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?)$"
    ),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- HTTP ----

@app.post("/shutdown", include_in_schema=False)
async def shutdown() -> JSONResponse:
    """Ask the local server to stop so the shell can exit without a hard kill."""
    server = globals().get("_uvicorn_server")
    if server is not None:
        server.should_exit = True
    return JSONResponse({"status": "shutting_down"})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "Murmur AI-backend",
            "tts": app_state.speaker is not None,
            "listening": app_state.listening_task is not None
            and not app_state.listening_task.done(),
            "os_permissions": app_state.os_permissions,
        }
    )


# ---- first-run setup HTTP endpoints ----

@app.get("/setup/status")
async def setup_status() -> JSONResponse:
    return JSONResponse(setup_module.get_setup_status())


@app.get("/readiness")
async def readiness_endpoint() -> JSONResponse:
    """Block GUI/agent work until every required local component is present."""
    return JSONResponse(setup_module.readiness())


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


# ---- settings + diagnostics HTTP endpoints (used by the settings drawer) ----

@app.get("/settings")
async def get_settings_endpoint() -> JSONResponse:
    from system import settings_tools

    return JSONResponse(settings_tools.load_settings())


@app.post("/settings")
async def post_settings_endpoint(request: Request) -> JSONResponse:
    from system import settings_tools

    try:
        changes = await request.json()
    except Exception:
        changes = {}
    try:
        return JSONResponse(settings_tools.update_settings(changes if isinstance(changes, dict) else {}))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/settings/reset")
async def reset_settings_endpoint() -> JSONResponse:
    from system import settings_tools

    return JSONResponse(settings_tools.reset_settings())


@app.get("/providers")
async def list_providers_endpoint() -> JSONResponse:
    """Registered model providers, with no API keys ever included."""
    from agent.local_providers import list_providers

    return JSONResponse({"providers": list_providers()})


@app.post("/providers")
async def register_provider_endpoint(request: Request) -> JSONResponse:
    """Register a local loopback provider or an explicitly opted-in cloud API."""
    from agent.local_providers import register_provider

    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    try:
        provider = register_provider(
            name=str(body.get("name", "")),
            base_url=str(body.get("base_url", "")),
            model=str(body.get("model", "")),
            cloud=bool(body.get("cloud", False)),
            api_key=str(body.get("api_key", "") or ""),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(provider)


@app.post("/providers/remove")
async def remove_provider_endpoint(request: Request) -> JSONResponse:
    from agent.local_providers import remove_provider

    try:
        body = await request.json()
    except Exception:
        body = {}
    name = str((body or {}).get("name", "")) if isinstance(body, dict) else ""
    return JSONResponse({"ok": remove_provider(name)})


@app.get("/model-options")
async def model_options_endpoint() -> JSONResponse:
    """Current vs optional models, annotated with hardware availability."""
    import setup as setup_module
    from system.profiler import detect_hardware, load_profile, model_options

    profile = load_profile() or detect_hardware()
    return JSONResponse({
        "hardware": profile.to_dict(),
        "options": model_options(profile),
        "current": setup_module.recommended_setup(profile)["models"],
    })


@app.post("/models/install")
async def install_model_endpoint(request: Request) -> JSONResponse:
    """Pull an opt-in model locally. Only known, hardware-compatible tags."""
    import setup as setup_module
    from system.profiler import MODEL_CATALOG, model_fits_hardware

    try:
        body = await request.json()
    except Exception:
        body = {}
    model = str((body or {}).get("model", "")).strip()
    if model not in MODEL_CATALOG:
        return JSONResponse({"ok": False, "error": "Unknown model."}, status_code=400)
    if not model_fits_hardware(model):
        return JSONResponse(
            {"ok": False, "error": f"This device cannot run {model}."}, status_code=400
        )
    result = await setup_module.pull_model(model, lambda *_args: None)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/models/use")
async def use_model_endpoint(request: Request) -> JSONResponse:
    from system.settings_tools import select_model

    try:
        body = await request.json()
    except Exception:
        body = {}
    summary = select_model(
        str((body or {}).get("model", "")), str((body or {}).get("role", "auto"))
    )
    ok = "now the" in summary
    return JSONResponse({"ok": ok, "summary": summary}, status_code=200 if ok else 400)


@app.get("/diagnostics")
async def get_diagnostics() -> JSONResponse:
    from system import settings_tools

    return JSONResponse(settings_tools.run_diagnostics())


# ---- model pull WebSocket (streams Ollama /api/pull progress) ----

@app.websocket("/setup/pull-model")
async def setup_pull_model(websocket: WebSocket):
    if not _ws_origin_allowed(websocket):
        await websocket.close(code=1008, reason="Origin not allowed")
        return
    await websocket.accept()
    logger.info("Setup pull-model client connected")

    # One ordered sender. Fire-and-forget send tasks race each other on the
    # same websocket and silently fail, which left the HUD stuck at 0%.
    progress_queue: asyncio.Queue[str] = asyncio.Queue()
    last_percent: dict[str, int] = {}

    async def _progress_sender() -> None:
        while True:
            payload = await progress_queue.get()
            try:
                await websocket.send_text(payload)
            except Exception:  # pragma: no cover - client disconnected
                progress_queue.task_done()
                return
            progress_queue.task_done()

    sender = asyncio.create_task(_progress_sender())

    def on_progress(label: str, percent: Optional[int], status: str) -> None:
        nonlocal model_name
        value = percent
        if value is None:
            # Ollama omits byte counts for some stages; keep the bar moving with
            # a conservative stage estimate rather than showing a frozen 0%.
            lowered = status.lower()
            if "manifest" in lowered:
                estimate = 5
            elif "download" in lowered or "pulling" in lowered:
                estimate = 45
            elif "verif" in lowered or "digest" in lowered:
                estimate = 75
            elif "writ" in lowered or "extract" in lowered:
                estimate = 90
            else:
                estimate = 20
            value = max(estimate, last_percent.get(model_name, 0))
        if value is not None:
            last_percent[model_name] = max(value, last_percent.get(model_name, 0))
        progress_queue.put_nowait(
            ServerMessage(
                type="pull_progress",
                model=model_name,
                text=status,
                percent=value,
                detail=label,
            ).to_json()
        )

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
            # Every queued frame is sent before the terminal message.
            await progress_queue.join()
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
    finally:
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:  # pragma: no cover - cancellation
            pass


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


async def emit_transcript(session: SessionState, send, text: str, role: str = "assistant") -> None:
    """Emit a clean plain-text turn for screen readers / refreshable Braille."""
    clean = " ".join(str(text or "").split())
    if not clean:
        return
    await send(ServerMessage(type="transcript", text=clean, role=role))


# ---- WebSocket control plane ----

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    if not _ws_origin_allowed(websocket):
        await websocket.close(code=1008, reason="Origin not allowed")
        return
    await websocket.accept()
    session = app_state.session_for(websocket)
    app_state.hud_sockets.add(websocket)
    app_state.send_locks[id(websocket)] = asyncio.Lock()
    logger.info("HUD connected (session %s)", id(websocket))

    async def send(msg: ServerMessage) -> None:
        # Background tasks may outlive this connection; no-op instead of
        # raising KeyError after the lock was removed on disconnect.
        lock = app_state.send_locks.get(id(websocket))
        if lock is None:
            return
        async with lock:
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
                app_state.last_input_mode = "typed"
                # Run in a background task so the receive loop stays free to
                # handle confirmations/progress during long tool calls (installs).
                asyncio.create_task(handle_text_input(session, send, msg.text or ""))

            elif msg.type == "confirm":
                # Tool-side confirmations (installer, etc.) block a worker thread.
                if tool_bus.resolve_confirmation(msg.request_id or "", bool(msg.approved)):
                    await send(
                        ServerMessage(
                            type="info",
                            text="Approved, starting installation." if msg.approved else "Cancelled.",
                        )
                    )
                else:
                    # Legacy safety-gate confirmation: re-run the brain with approval.
                    await handle_confirm(session, send, msg.request_id, bool(msg.approved))

            elif msg.type == "guidance_response":
                # Free-text answer to a spoken "I'm stuck, what should I do?" prompt.
                if tool_bus.resolve_guidance(msg.request_id or "", msg.text or ""):
                    await send(ServerMessage(type="info", text="Guidance received."))

            elif msg.type == "set_muted":
                app_state.muted = bool(msg.muted)
                await send(
                    ServerMessage(
                        type="info",
                        text="Microphone muted." if app_state.muted else "Microphone unmuted.",
                    )
                )

            elif msg.type == "set_listening_mode":
                mode = (msg.mode or "").lower()
                if mode == "sleep":
                    await enter_sleep(session, send)
                elif mode == "active":
                    await wake_up(session, send)
                    await start_listening(session, send)
                else:
                    await send(ServerMessage(type="error", detail="Unknown listening mode."))

            elif msg.type == "update_available":
                # The Tauri updater found a release; announce it aloud once.
                await on_update_available(
                    session, send, msg.version or "new", msg.notes
                )

            elif msg.type == "update_confirm":
                await resolve_update_confirmation(
                    session, send, bool(msg.approved)
                )

            elif msg.type == "update_status":
                # Offline / verification failures are logged, never spoken as
                # an update prompt (graceful fallback).
                logger.info("Update check status from shell: %s", msg.detail or "")
                await send(ServerMessage(type="info", text=msg.detail or "Update check finished."))

            elif msg.type == "permission_status":
                await _handle_permission_status(msg.permissions, send)

            elif msg.type == "be_quiet":
                if app_state.speaker is not None:
                    if hasattr(app_state.speaker, "be_quiet"):
                        app_state.speaker.be_quiet()
                    else:
                        app_state.speaker.interrupt()
                await send(ServerMessage(type="info", text="I'll be quiet."))

            elif msg.type == "cue":
                # Short shell cue (single-instance notice, autostart change).
                # Never routed through the brain.
                text = " ".join(str(msg.text or "").split())
                if text:
                    if app_state.speaker is not None:
                        try:
                            from audio.speech_queue import SpeechPriority

                            app_state.speaker.speak_priority(text, SpeechPriority.INTERRUPT)
                        except Exception:
                            logger.debug("Cue speak failed", exc_info=True)
                    await emit_transcript(session, send, text, "system")

            elif msg.type == "describe_screen":
                await _handle_describe_screen(msg.focus or "overview", send)

            elif msg.type == "run_diagnostics":
                await _handle_diagnostics(send)

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
        # With no HUD left, stop listening; an always-hot mic with no visible
        # state is both a privacy problem and a source of dead-send errors.
        if not app_state.hud_sockets:
            for task in (app_state.listening_task, app_state.wake_task):
                if task and not task.done():
                    task.cancel()
            app_state.listening_task = None
            app_state.wake_task = None
            if app_state.listener is not None:
                try:
                    app_state.listener.stop()
                except Exception:
                    logger.debug("Listener stop on disconnect failed", exc_info=True)
                app_state.listener = None


# ---- handlers ----

async def _handle_describe_screen(focus: str, send) -> None:
    """Tray/UI 'Describe Screen' uses the same local VLM path as voice."""
    from agent.vision_agent import VisionAgent

    try:
        text = await asyncio.to_thread(VisionAgent().describe, focus)
    except Exception:
        logger.exception("Tray describe-screen failed")
        text = "I couldn't read the screen just now. Please try again."
    await emit_transcript(None, send, text, "assistant")
    if app_state.speaker is not None:
        try:
            from audio.speech_queue import SpeechPriority

            app_state.speaker.speak_priority(text, SpeechPriority.INTERRUPT)
        except Exception:
            logger.debug("Tray description speak failed", exc_info=True)


async def _handle_diagnostics(send) -> None:
    """Tray 'Run Diagnostics' runs the same local report as Settings."""
    from system.settings_tools import run_diagnostics

    try:
        report = await asyncio.to_thread(run_diagnostics)
        summary = str(report.get("summary") or "Diagnostics finished.")
    except Exception:
        logger.exception("Tray diagnostics failed")
        summary = "Diagnostics could not run right now."
    await send(ServerMessage(type="info", text=summary))
    await emit_transcript(None, send, summary, "system")
    if app_state.speaker is not None:
        try:
            from audio.speech_queue import SpeechPriority

            app_state.speaker.speak_priority(summary, SpeechPriority.INTERRUPT)
        except Exception:
            logger.debug("Tray diagnostics speak failed", exc_info=True)


async def _handle_permission_status(permissions: Optional[dict], send) -> None:
    """Store shell permission diagnostics and speak plain-language recovery."""
    app_state.os_permissions = permissions
    recovery = (permissions or {}).get("recovery") or []
    if recovery:
        spoken = "Permission check. " + " ".join(str(r) for r in recovery)
        if app_state.speaker is not None:
            try:
                from audio.speech_queue import SpeechPriority

                app_state.speaker.speak_priority(spoken, SpeechPriority.INTERRUPT)
            except Exception:
                logger.debug("Permission prompt speak failed", exc_info=True)
    await send(ServerMessage(type="info", text="Permission check received."))


async def _try_checkpoint_phrase(session, send, text: str) -> bool:
    """Answer 'what step did we stop on?' and 'resume my last task'."""
    value = (text or "").lower()
    if "resume" not in value and "stop on" not in value and "left off" not in value:
        return False
    from agent.checkpoint import describe, load_last, resume_subgoals

    checkpoint = load_last()
    if checkpoint is None:
        await _speak_and_return(session, send, "I don't have a paused task to resume.")
        return True
    if "what step" in value or "stop on" in value or "left off" in value:
        await _speak_and_return(session, send, describe(checkpoint))
        return True
    remaining = resume_subgoals(checkpoint)
    await _speak_and_return(session, send, f"Resuming: {', '.join(remaining)}.")
    try:
        from agent.vision_agent import VisionAgent

        await asyncio.to_thread(
            VisionAgent().run_visual_task, "; then ".join(remaining)
        )
    except Exception:  # pragma: no cover - platform dependent
        logger.exception("Checkpoint resume failed")
    return True


async def _try_monitor_switch(session, send, text: str) -> bool:
    """Handle 'look at my second monitor' locally, without a model call."""
    from agent.vision_agent import parse_monitor_phrase, set_active_monitor

    monitor = parse_monitor_phrase(text)
    if monitor is None:
        return False
    reply = set_active_monitor(monitor)
    await send(ServerMessage(type="text_output", text=reply))
    await _speak_and_return(session, send, reply)
    return True


async def _try_mid_job_intent(session: SessionState, send, text: str) -> bool:
    """Fast local head: stop/status/screen are answered without a model call."""
    from agent.mid_job import classify

    intent = classify(text)
    if intent == "stop":
        abort_controller.abort("user said stop mid-job")
        await send(ServerMessage(type="automation_stopped", text="Automation stopped."))
        await _set_state(send, session, "IDLE")
        return True
    if intent == "status":
        reply = "I'm here and listening. Say stop to cancel a job."
        session.add_turn("assistant", reply)
        await _speak_and_return(session, send, reply)
        return True
    # Screen questions still go to the brain: its describe_screen tool knows
    # whether vision is available and speaks a clear error when it isn't.
    return False


def _preview_settings() -> dict:
    """Opt-in flag for automatic previews; offline settings simply mean off."""
    try:
        from system.settings_tools import load_settings

        return load_settings()
    except Exception:  # pragma: no cover - local config may be unavailable
        return {}


async def _build_and_store_preview(session: SessionState, send, goal: str) -> None:
    """Build a read-only preview for a goal and hold it for one decision."""
    try:
        if pick_engine(goal) == "vision":
            from agent.vision_agent import VisionAgent

            preview = await asyncio.to_thread(VisionAgent().build_preview, goal)
        else:
            preview = await asyncio.to_thread(app_state.brain.build_preview, goal)
    except Exception:  # pragma: no cover - model/model absent
        logger.exception("Could not build plan preview")
        await _announce_local(session, send, "I couldn't build a preview for that.")
        return
    session.pending_plan = preview
    await _announce_local(session, send, preview.spoken())


async def _route_plan_preview(
    session: SessionState, send, text: str
) -> tuple[bool, str]:
    """Return ``(handled, routed_text)`` for preview/decision utterances.

    A preview is a single held action, mirroring the tool approval rules: any
    unrelated speech, a stop phrase, or another decision drops it.
    """
    # A tool confirmation is the only other held approval; never stack them.
    if tool_bus.pending_ids():
        return False, text

    decision = classify_plan(text)
    pending = session.pending_plan

    if is_abort_phrase(text):
        if pending:
            session.pending_plan = None
            await _announce_local(session, send, "Preview discarded. Everything is halted.")
        return False, text

    if pending is not None:
        if decision.kind == "approve":
            session.pending_plan = None
            preview = pending
            try:
                if preview.engine == "vision":
                    from agent.vision_agent import VisionAgent

                    result = await asyncio.to_thread(
                        VisionAgent().run_visual_task,
                        preview.goal,
                        plan=preview.plan,
                        skip_indices=sorted(preview.skipped),
                    )
                else:
                    result = await asyncio.to_thread(
                        app_state.brain.execute_preview, preview
                    )
                await _speak_and_return(session, send, result)
            except Exception:  # pragma: no cover - desktop dependent
                logger.exception("Approved preview failed")
                await _announce_local(session, send, "I couldn't run that preview.")
            return True, ""
        if decision.kind == "skip":
            await _announce_local(session, send, pending.skip(decision.numbers))
            return True, ""
        if decision.kind == "cancel":
            session.pending_plan = None
            await _announce_local(session, send, "Preview discarded.")
            return True, ""
        session.pending_plan = None
        await _announce_local(session, send, "Preview discarded.")
        return False, text

    if decision.kind == "preview":
        await _build_and_store_preview(session, send, decision.goal)
        return True, ""
    if should_auto_preview(text, _preview_settings()):
        await _build_and_store_preview(session, send, text)
        return True, ""
    return False, text


async def _announce_local(session: SessionState, send, message: str) -> None:
    """Speak a local status change and expose it to the screen-reader log."""
    await emit_transcript(session, send, message, "system")
    if app_state.speaker:
        try:
            app_state.speaker.speak(message)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Dictation announcement failed", exc_info=True)


async def _try_text_edit_phrase(session: SessionState, send, text: str) -> bool:
    """Handle spoken selection/editing commands locally before the model."""
    reply = text_edit_tools.handle_text_edit_phrase(text, app_state.dictation.buffer)
    if reply is None:
        return False
    await _announce_local(session, send, reply)
    return True


async def _route_dictation(
    session: SessionState, send, text: str
) -> tuple[bool, str]:
    """Return ``(handled, routed_text)`` for one utterance.

    While dictation is active, speech is typed into the focused field and never
    sent to the brain. A stop phrase consumes the turn; a command trigger ends
    dictation and returns the remainder for normal agent routing.
    """
    dictation = app_state.dictation
    phrase = (text or "").strip()
    # Physical stop phrases always abort, even while dictating a document.
    if is_abort_phrase(phrase):
        abort_controller.abort(f"user said {phrase}")
        return True, ""
    if not dictation.active:
        if DICTATION_START_RE.match(phrase):
            await _announce_local(session, send, dictation.start())
            return True, ""
        return False, phrase

    result = dictation.feed(phrase)
    if result.backspaces:
        try:
            text_edit_tools.erase_last_chars(result.backspaces)
        except RuntimeError as exc:  # missing optional dependency
            await _announce_local(session, send, str(exc))
    if result.text:
        try:
            text_edit_tools.type_text(result.text)
        except RuntimeError as exc:  # missing optional dependency
            await _announce_local(session, send, str(exc))
        await emit_transcript(session, send, f"Typed: {result.text}", "system")
    if result.spoken:
        await _announce_local(session, send, result.spoken)
    if result.command:
        return False, result.command
    return True, ""


def _is_multi_step_gui_goal(text: str) -> bool:
    """True for goals with several desktop actions in one sentence."""
    value = (text or "").strip()
    if not MULTI_STEP_RE.search(value) or pick_engine(value) != "vision":
        return False
    actions = (
        "open", "start", "create", "new", "delete", "remove", "add",
        "click", "type", "save", "select", "name", "insert", "build",
    )
    return sum(
        1 for verb in actions if re.search(rf"\b{verb}\b", value, re.IGNORECASE)
    ) >= 2


_SETUP_ALLOWED_RE = re.compile(
    r"\b(setup|diagnostic|settings?|models?|update|dictat|be quiet|stop|help|"
    r"plugin|permission|repair|retry)\b",
    re.IGNORECASE,
)


async def _require_ready(session: SessionState, send, text: str) -> bool:
    """Refuse agent work until Ollama, the models and local weights exist."""
    state = setup_module.readiness()
    if state["ready"] or _SETUP_ALLOWED_RE.search(text or ""):
        return True
    detail = state["detail"]
    message = (
        f"I can't act yet. Setup is incomplete: {detail}. "
        "Open Settings or say 'run diagnostics' to fix it."
    )
    await emit_transcript(session, send, message, "system")
    await send(ServerMessage(type="error", detail=message))
    return False


async def handle_text_input(
    session: SessionState, send, text: str
) -> None:
    """Full voice turn: transcribe already done; think, act, speak."""
    if not await _require_ready(session, send, text):
        return
    handled, text = await _route_dictation(session, send, text)
    if handled:
        return
    if await _try_text_edit_phrase(session, send, text):
        return
    handled, text = await _route_plan_preview(session, send, text)
    if handled:
        return
    session.add_turn("user", text)
    # Mirror the user's own words into the shared chat log so the conversation
    # reads in order instead of showing only Murmur's replies and status lines.
    await emit_transcript(session, send, text, "user")
    if text_is_sleep_phrase(text):
        await enter_sleep(session, send)
        return
    if text_is_wake_phrase(text) and app_state.listening_mode == "sleep":
        await wake_up(session, send)
        await start_listening(session, send)
        return
    if await _try_checkpoint_phrase(session, send, text):
        return
    if await _try_monitor_switch(session, send, text):
        return
    if await _try_update_check_phrase(session, send, text):
        return
    if await _try_update_verbal_confirmation(session, send, text):
        return
    if await _try_plugin_phrase(session, send, text):
        return
    if await _try_demo_phrase(session, send, text):
        return
    if await _try_settings_phrase(session, send, text):
        return
    if await _try_context_phrase(session, send, text):
        return
    if await _try_mid_job_intent(session, send, text):
        return
    # If the user is answering a spoken confirmation, handle it here instead of
    # sending "yes"/"no" to the model.
    if _try_verbal_confirmation(text) is not None:
        await send(ServerMessage(type="text_output", text=text))
        return
    # Multi-step GUI goals go straight through the planner/verifier loop. Doing
    # them as isolated brain tool calls lost the plan and skipped verification.
    if _is_multi_step_gui_goal(text):
        await _working_on_it(session, send)
        await _set_state(send, session, "THINKING")
        try:
            from agent.vision_agent import VisionAgent

            reply = await asyncio.to_thread(VisionAgent().run_visual_task, text)
        except Exception as exc:
            logger.exception("Multi-step visual task failed")
            reason = " ".join(str(exc).split())[:160] or type(exc).__name__
            reply = (
                f"I couldn't finish that multi-step task: {reason}. "
                "Say 'stop' to cancel, or try again."
            )
        session.add_turn("assistant", reply)
        await _speak_and_return(session, send, reply)
        return
    await _working_on_it(session, send)
    await _set_state(send, session, "THINKING")

    try:
        # Offload the synchronous Ollama/tool loop so the event loop keeps
        # streaming progress and accepting confirmations during installs.
        async with app_state.turn_lock:
            reply = await asyncio.to_thread(
                app_state.brain.think_and_act,
                user_text=_augment_with_context(text, session),
                conversation_history=session.turns,
            )
    except Exception:
        logger.exception("Brain turn failed")
        await _set_state(send, session, "IDLE")
        await send(ServerMessage(type="error", detail="I had trouble thinking that through."))
        return

    session.add_turn("assistant", reply)
    await _speak_and_return(session, send, reply, stream=len(reply) > 200)


async def handle_confirm(
    session: SessionState, send, request_id: Optional[str], approved: bool
) -> None:
    """User answered a confirmation request from a destructive tool."""
    pending = session.pending.get(request_id) if request_id else None
    if not pending:
        await send(ServerMessage(type="error", detail="No pending confirmation."))
        await _set_state(send, session, "IDLE")
        return

    # All approvals are resolved through tool_bus (single-use, echo-gated).
    # Never install a process-wide auto-approve callback here.
    session.pending.pop(request_id, None)
    await send(
        ServerMessage(type="info", text="That approval is no longer pending.")
    )
    await _set_state(send, session, "IDLE")


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


def _echo_is_active() -> bool:
    """True while our own TTS or loopback audio could be heard as speech."""
    from audio.echo_guard import echo_is_active

    return echo_is_active()


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

    # A "yes" heard from our own speaker (or a call's echo) is never consent.
    if _echo_is_active():
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
        # A held approval belongs to one exact action. Anything else the user
        # says cancels it instead of leaving a stale "yes" target alive.
        tool_bus.drop_pending("unrelated utterance")
        return None
    decision = False if denied else approved
    # Resolve the most recent pending request.
    request_id = pending[-1]
    tool_bus.resolve_confirmation(request_id, decision)
    logger.info("Verbal confirmation %s for %s (heard: %r)", decision, request_id, text)
    _chime("confirmation" if decision else "error")
    if app_state.speaker is not None:
        from audio.speech_queue import SpeechPriority

        app_state.speaker.speak_priority(
            "Approved." if decision else "Cancelled.", SpeechPriority.INTERRUPT
        )
    return decision


# ---- sleep / wake state machine ----

from audio.wake_word import (  # noqa: E402
    WakeWordDetector, text_is_wake_phrase, text_is_sleep_phrase, SAMPLE_RATE,
)


def _get_wake_detector():
    """Lazy-load the offline wake-word detector."""
    if app_state.wake_detector is None:
        try:
            app_state.wake_detector = WakeWordDetector()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Wake-word detector init failed")
            app_state.wake_detector = False  # type: ignore[assignment]
    return app_state.wake_detector or None


def _apply_listening_mode(mode: str) -> None:
    """Switch between active VAD listening and sleep/wake-word standby."""
    assert mode in ("active", "sleep")
    app_state.listening_mode = mode


def _announce(text: str) -> None:
    if app_state.speaker is not None:
        try:
            app_state.speaker.speak(text)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Announcement failed")


async def enter_sleep(session: SessionState, send) -> None:
    """Stop active audio, switch to standby, and announce the change."""
    # Release the microphone so standby ignores all general room audio.
    if app_state.listening_task and not app_state.listening_task.done():
        app_state.listening_task.cancel()
        app_state.listening_task = None
    if app_state.listener is not None:
        try:
            app_state.listener.stop()
        except Exception:  # pragma: no cover - defensive
            logger.debug("Listener stop on sleep failed", exc_info=True)
        app_state.listener = None

    _apply_listening_mode("sleep")
    _chime("sleep")
    _announce("Going to sleep. Say hey Murmur to wake me.")
    await send(ServerMessage(type="state", status="SLEEPING", uptime_s=session.uptime()))
    await emit_transcript(session, send, "Going to sleep. Say hey Murmur to wake me.", "system")
    # Ensure any active wake task is running.
    if app_state.wake_task is None or app_state.wake_task.done():
        app_state.wake_task = asyncio.create_task(_wake_monitor(session, send))


async def wake_up(session: SessionState, send) -> None:
    """Leave standby, resume active listening, chime and speak 'I'm listening'."""
    _apply_listening_mode("active")
    _chime("wake")
    _announce("I'm listening")
    await send(ServerMessage(type="state", status="IDLE", uptime_s=session.uptime()))
    # Sleep emits a visible transcript line; wake must too, or the HUD keeps
    # showing the stale "Going to sleep" turn and looks like it never woke.
    await emit_transcript(session, send, "I'm listening.", "system")
    # Cancel the standby monitor; active listening resumes via start_listening.
    if app_state.wake_task is not None:
        app_state.wake_task.cancel()
        app_state.wake_task = None


async def _wake_monitor(session: SessionState, send) -> None:
    """While sleeping, poll the local wake-word detector without streaming audio."""
    import sounddevice as sd

    detector = _get_wake_detector()
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=int(SAMPLE_RATE * 0.5)) as stream:
            while not app_state._shutting_down and app_state.listening_mode == "sleep":
                indata, _ = await asyncio.to_thread(stream.read, int(SAMPLE_RATE * 0.5))
                pcm = indata.tobytes()
                if detector is not None and detector.detect(pcm):
                    await wake_up(session, send)
                    # Resume the active conversation loop.
                    await start_listening(session, send)
                    return
                await asyncio.sleep(0.1)
    except Exception:
        logger.exception("Wake monitor stopped", exc_info=True)


# ---- update notifications (driven by the Tauri updater commands) ----

def _spoken_release_summary(notes: str | None, limit: int = 240) -> str:
    """Condense GitHub release notes into a short, speakable summary."""
    if not notes:
        return ""
    text = " ".join(str(notes).split())
    text = re.sub(r"[#*_`>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


async def on_update_available(session: SessionState, send, version: str, notes: str | None) -> None:
    """Announce a discovered update to every HUD and speak the prompt aloud."""
    request_id = f"upd-{int(time.time() * 1000)}"
    summary = _spoken_release_summary(notes)
    app_state.pending_update = {
        "request_id": request_id,
        "version": version,
        "notes": notes or "",
    }
    prompt = (
        f"Version {version} is available. "
        + (f"{summary} " if summary else "")
        + "Would you like me to download and restart to install it?"
    )
    await broadcast_to_huds(
        ServerMessage(
            type="update_available",
            request_id=request_id,
            version=version,
            notes=summary,
            text=prompt,
        )
    )
    _announce(prompt)


async def resolve_update_confirmation(session: SessionState, send, approved: bool) -> None:
    """Apply the user's yes/no answer to a pending update prompt."""
    pending = app_state.pending_update
    if not pending:
        await send(ServerMessage(type="info", text="There is no pending update."))
        return
    request_id = pending.get("request_id", "")
    version = pending.get("version", "")
    app_state.pending_update = None
    if approved:
        await broadcast_to_huds(
            ServerMessage(
                type="update_install",
                request_id=request_id,
                version=version,
                text=f"Installing version {version}…",
            )
        )
        _announce(f"Installing version {version} now.")
    else:
        await send(ServerMessage(type="info", text="Update cancelled."))
        _announce("Okay, I won't update right now.")


_UPDATE_CHECK_RE = re.compile(
    r"\b(check|look) for (an )?(updates?|newer version)\b|\b(any )?updates? available\b",
    re.IGNORECASE,
)


async def _try_update_check_phrase(session: SessionState, send, text: str) -> bool:
    """Let the user ask 'check for updates' without going through the model."""
    if not _UPDATE_CHECK_RE.search(text or ""):
        return False
    await send(ServerMessage(type="update_check_request", text="Checking for updates…"))
    await emit_transcript(session, send, "Let me check for updates.", "system")
    _announce("Let me check for updates.")
    return True


async def _try_update_verbal_confirmation(session, send, text: str) -> bool:
    """Answer a spoken update prompt with yes/no before tool confirmations."""
    if not app_state.pending_update:
        return False
    if _echo_is_active():
        # TTS bleed from the spoken update prompt must not trigger an install.
        return False
    lowered = (text or "").lower()
    if _YES_RE.search(lowered):
        await resolve_update_confirmation(session, send, True)
        return True
    if _NO_RE.search(lowered):
        await resolve_update_confirmation(session, send, False)
        return True
    return False


# ---- local MCP plugin management phrases ----

_PLUGIN_LIST_RE = re.compile(
    r"\b(list|show|what|which)\b.*\b(plugins?|mcp tools?)\b|\b(plugins?|mcp tools?)\b.*\b(active|loaded|available)\b",
    re.IGNORECASE,
)
_PLUGIN_RELOAD_RE = re.compile(
    r"\b(reload|refresh|restart)\b.*\b(plugins?|mcp)\b", re.IGNORECASE
)


async def _try_plugin_phrase(session: SessionState, send, text: str) -> bool:
    """Handle plugin inspection/reload locally without a model call."""
    from tools import mcp_manager

    lowered = text or ""
    if _PLUGIN_RELOAD_RE.search(lowered):
        status = await asyncio.to_thread(mcp_manager.manager.reload)
        reply = status.get("summary", "Plugins reloaded.")
        await send(ServerMessage(type="info", text=reply))
        await _speak_and_return(session, send, reply)
        return True
    if _PLUGIN_LIST_RE.search(lowered):
        reply = mcp_manager.manager.spoken_status()
        await send(ServerMessage(type="info", text=reply))
        await _speak_and_return(session, send, reply)
        return True
    return False


# ---- guided eyes-free demo ----

_DEMO_START_RE = re.compile(
    r"\b(start|begin|run|open)\b.*\b(tutorial|demo|practice mode)\b|\bstart tutorial\b",
    re.IGNORECASE,
)
_DEMO_NEXT_RE = re.compile(r"^(next|continue|done|go on)\b", re.IGNORECASE)
_DEMO_STOP_RE = re.compile(r"\b(stop|exit|quit|end)\b.*\b(tutorial|demo|practice)\b", re.IGNORECASE)


async def _try_demo_phrase(session: SessionState, send, text: str) -> bool:
    """Drive the four-step practice walkthrough entirely by voice."""
    from system.demo import DemoSession

    value = (text or "").strip()
    if _DEMO_START_RE.search(value) or (
        app_state.demo is None and value.lower() == "tutorial"
    ):
        app_state.demo = DemoSession()
        reply = app_state.demo.next_step()
        await _speak_and_return(session, send, reply)
        return True
    if app_state.demo is None:
        return False
    if _DEMO_STOP_RE.search(value):
        reply = app_state.demo.finish()
        app_state.demo = None
        await _speak_and_return(session, send, reply)
        return True
    if _DEMO_NEXT_RE.search(value):
        reply = app_state.demo.next_step()
        if not app_state.demo.active:
            app_state.demo = None
        await _speak_and_return(session, send, reply)
        return True
    return False


# ---- local settings / diagnostics phrases ----

async def _try_settings_phrase(session: SessionState, send, text: str) -> bool:
    """Handle settings and diagnostics voice commands without a model call."""
    from system import settings_tools

    reply = settings_tools.handle_voice_command(text)
    if reply is None:
        return False
    # A spoken mode change must also change the live state machine; updating
    # the setting alone left the VAD listener or standby monitor inconsistent.
    # Only do this for actual mode commands, not every settings reply.
    if not re.search(r"wake[- ]word|standby|continuous listening|always listen|active listening", text or "", re.I):
        await send(ServerMessage(type="info", text=reply))
        await emit_transcript(session, send, reply, "system")
        await _set_state(send, session, "IDLE")
        return True
    wanted = settings_tools.load_settings().get("listening_mode", "active")
    if wanted == "wake" and app_state.listening_mode != "sleep":
        await enter_sleep(session, send)
    elif wanted == "active" and app_state.listening_mode == "sleep":
        await wake_up(session, send)
        await start_listening(session, send)
    await send(ServerMessage(type="info", text=reply))
    await emit_transcript(session, send, reply, "system")
    await _set_state(send, session, "IDLE")
    return True


# ---- clipboard / active context ----

async def _try_context_phrase(session: SessionState, send, text: str) -> bool:
    """Answer clipboard and recent-file questions locally."""
    from tools import context_tools

    context_tools.record_context(text, session)
    reply = context_tools.handle_context_phrase(text, session)
    if reply is None:
        return False
    await send(ServerMessage(type="info", text=reply))
    await emit_transcript(session, send, reply, "system")
    await _set_state(send, session, "IDLE")
    return True


def _augment_with_context(text: str, session: SessionState) -> str:
    """Resolve 'this'/'it' against session context before asking the model."""
    from tools import context_tools

    context_tools.record_context(text, session)
    resolved = context_tools.resolve_reference(text, session)
    if resolved:
        return f"{text}\n(Relevant context: {resolved})"
    return text


# ---- state helpers ----

def _chime(kind: str) -> None:
    """Play a state-transition earcon if the user enabled them."""
    if app_state.speaker is not None:
        try:
            app_state.speaker.chime(kind)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Earcon failed", exc_info=True)


async def _working_on_it(session: SessionState, send) -> None:
    """Tell the user immediately that a slow command has been accepted."""
    await emit_transcript(session, send, "Working on it.", "system")
    if getattr(app_state, "last_input_mode", "voice") == "typed":
        return  # typed mode is a silent chat; the message is already visible
    if app_state.speaker is not None:
        try:
            await asyncio.to_thread(app_state.speaker.speak, "Working on it.")
        except Exception:  # pragma: no cover - TTS dependent
            logger.debug("Working announcement failed", exc_info=True)


async def _set_state(send, session: SessionState, status: str) -> None:
    await send(ServerMessage(type="state", status=status, uptime_s=session.uptime()))
    cue = {
        "LISTENING": "listening",
        "IDLE": "listening",
        "THINKING": "thinking",
        "SPEAKING": "speaking",
        "CONFIRMATION_REQUIRED": "confirmation",
        "SLEEPING": "sleep",
    }.get(status)
    if cue:
        _chime(cue)


async def _speak_and_return(
    session: SessionState, send, reply: str, stream: bool = False
) -> None:
    """Speak the reply, then return to IDLE (listening).

    Long replies are split at sentence boundaries so synthesis starts before
    the whole response is assembled.
    """
    await emit_transcript(session, send, reply)
    if getattr(app_state, "last_input_mode", "voice") == "typed":
        # Typing mode is a silent chat: the reply is already on the HUD as a
        # message, so speaking it would just interrupt the user's reading.
        await _set_state(send, session, "IDLE")
        return
    await _set_state(send, session, "SPEAKING")
    if app_state.speaker:
        try:
            if stream and hasattr(app_state.speaker, "speak_streamed"):
                from audio.streaming import chunk_text

                app_state.speaker.speak_streamed(chunk_text(reply))
            else:
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
        if app_state.muted:
            logger.info("Ignoring utterance while muted")
            return
        app_state.last_input_mode = "voice"
        session.add_turn("user", text)
        confidence = getattr(app_state.listener, "last_confidence", "high")
        loop = app_state.loop or asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            _on_utterance_async(session, send, text, confidence), loop
        )

    app_state.listener.on_utterance = on_utterance
    app_state.listener.start()
    app_state.listening_task = asyncio.create_task(_listen_amplitude(session, send))
    await _set_state(send, session, "LISTENING")


async def _on_utterance_async(
    session, send, text: str, asr_confidence: str = "high"
) -> None:
    handled, text = await _route_dictation(session, send, text)
    if handled:
        return
    if await _try_text_edit_phrase(session, send, text):
        return
    handled, text = await _route_plan_preview(session, send, text)
    if handled:
        return
    # Sleep/wake commands are handled locally, never sent to the model.
    if text_is_sleep_phrase(text):
        await enter_sleep(session, send)
        return
    if text_is_wake_phrase(text):
        if app_state.listening_mode == "sleep":
            await wake_up(session, send)
            await start_listening(session, send)
            return
        # In active mode a wake phrase is just a normal utterance; fall through.
    if await _try_checkpoint_phrase(session, send, text):
        return
    if await _try_monitor_switch(session, send, text):
        return
    if await _try_update_check_phrase(session, send, text):
        return
    if await _try_update_verbal_confirmation(session, send, text):
        return
    if await _try_plugin_phrase(session, send, text):
        return
    if await _try_demo_phrase(session, send, text):
        return
    if await _try_settings_phrase(session, send, text):
        return
    if await _try_context_phrase(session, send, text):
        return

    # Verbal "yes, confirm" / "no, cancel" can answer a pending spoken prompt.
    if _try_verbal_confirmation(text) is not None:
        await send(ServerMessage(type="text_output", text=text))
        return
    await _working_on_it(session, send)
    await _set_state(send, session, "THINKING")
    try:
        async with app_state.turn_lock:
            reply = await asyncio.to_thread(
                app_state.brain.think_and_act,
                user_text=_augment_with_context(text, session),
                conversation_history=session.turns,
                asr_confidence=asr_confidence,
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
                indata, _ = await asyncio.to_thread(stream.read, 1600)
                rms = float((indata ** 2).mean() ** 0.5) if indata.size else 0.0
                # 0..1-ish amplitude for the UI.
                amp = 0.0 if app_state.muted else min(rms * 8.0, 1.0)
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

    global _uvicorn_server
    config = uvicorn.Config(app, host=BACKEND_HOST, port=BACKEND_PORT, log_level="info")
    _uvicorn_server = uvicorn.Server(config)
    _uvicorn_server.run()


if __name__ == "__main__":
    main()
