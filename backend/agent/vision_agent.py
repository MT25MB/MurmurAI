"""Visual computer-use agent loop for Murmur AI.

Drives local GUI automation for complex desktop apps (Blender, DaVinci Resolve,
browsers) entirely on-device via a local Ollama VLM (qwen2.5vl:7b).

Accuracy upgrades:
- Set-of-Marks (SoM): interactive UI elements are detected (OpenCV contours +
  OS accessibility trees where available) and drawn as numbered boxes [1], [2]…
  The VLM can click by element_id, resolving to exact pixel centers.
- App knowledge: the foreground window title is detected before each step and
  that app's keyboard-shortcut cheat-sheet is injected into the system prompt,
  so the agent prefers fast hotkeys over slow mouse hunting.

Design rules:
- pyautogui's corner failsafe is always on.
- Each step's original + annotated screenshot and reasoning JSON are saved to
  backend/logs/ for visual replay.
- Destructive actions still route through the SafetyGate confirmation.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

try:  # pragma: no cover - platform optional
    import mss
except Exception:  # pragma: no cover - optional dep may be installed but unusable (headless/no PortAudio)
    mss = None  # type: ignore

try:  # pragma: no cover - platform optional
    import pyautogui
except Exception:  # pragma: no cover - optional dep may be installed but unusable (headless/no PortAudio)
    pyautogui = None  # type: ignore

import httpx

from tools.safety import SafetyGate
from tools.event_bus import tool_bus
from agent.state import ServerMessage
from agent.abort import abort_controller
from agent.task_plan import TaskPlan, build_plan, format_history
from agent.plan_preview import PlanPreview, extract_files
from agent.model_names import normalize_model
from local_endpoint import normalize_ollama_host
from agent.loop_detector import LoopDetector, action_fingerprint, screen_hash
from agent.offscreen_search import ScrollSearch

logger = logging.getLogger("murmur_ai.agent.vision_agent")


def _model_bool(value: object) -> bool:
    """Parse a model-supplied boolean strictly.

    A plain-text VLM reply can contain ``"false"`` as a string; ``bool("false")``
    is True, which would let the model claim a step succeeded without evidence.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _model_coords(value: object) -> Optional[list[float]]:
    """Return normalized [x, y] or None for any malformed model output."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        coords = [float(value[0]), float(value[1])]
    except (TypeError, ValueError, OverflowError):
        return None
    return coords if all(math.isfinite(n) and abs(n) < 1_000_000 for n in coords) else None


def run_agent_method(method: str, *args, **kwargs):
    """Construct a short-lived agent, run one method, always release it.

    Every agent registers an abort listener and an httpx client; leaking either
    on every voice turn accumulates memory and announces stale "stopped" cues.
    """
    agent = VisionAgent()
    try:
        return getattr(agent, method)(*args, **kwargs)
    finally:
        agent.close()


DEFAULT_VISION_MODEL = normalize_model(os.getenv("OLLAMA_VISION_MODEL", "qwen3.5:9b"))


def resolve_vision_model() -> str:
    """Read the live saved/env vision model at construction time.

    The module-level default is computed before hardware profiling and settings
    are applied, so using it directly made light-tier machines call a 7B vision
    model that was never pulled. When the chat model is a unified qwen3.5
    checkpoint, reuse it here so no second model needs to be loaded.
    """
    try:
        from system.settings_tools import load_settings

        value = load_settings().get("vision_model") or os.getenv(
            "OLLAMA_VISION_MODEL", DEFAULT_VISION_MODEL
        )
    except Exception:  # pragma: no cover - settings are optional
        value = os.getenv("OLLAMA_VISION_MODEL", DEFAULT_VISION_MODEL)
    value = normalize_model(value)
    from system.profiler import shared_multimodal_model

    return shared_multimodal_model(os.getenv("OLLAMA_MODEL", ""), value) or value
OLLAMA_HOST = normalize_ollama_host(os.getenv("OLLAMA_HOST"))
LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"
MAX_STEPS_DEFAULT = 15
STEP_SETTLE_S = 1.5  # let heavy apps render after each action

VALID_ACTIONS = {
    "CLICK", "DOUBLE_CLICK", "DRAG", "SCROLL_DOWN", "SCROLL_UP",
    "SCROLL_HORIZONTAL", "SCROLL_SEARCH", "ZOOM_CLICK", "TYPE", "KEY", "WAIT", "FINISH",
    "FAIL",
}

# Global capture target shared by every ScreenController. None means "follow
# the monitor containing the focused window" (the default).
_active_monitor_index: Optional[int] = None


def get_active_monitor() -> Optional[int]:
    """Return the user-selected 1-based monitor, or None for auto/focused."""
    return _active_monitor_index


def set_active_monitor(index: int | str) -> str:
    """Select the monitor used for capture. Returns a spoken confirmation."""
    global _active_monitor_index
    try:
        number = int(index)
    except (TypeError, ValueError):
        return f"{index} is not a monitor number."
    from tools.window_tools import get_monitors

    monitors = get_monitors()
    valid = {m["index"] for m in monitors}
    if number not in valid:
        return f"Monitor {number} does not exist. I can see {len(monitors)} monitor(s)."
    _active_monitor_index = number
    return f"Watching monitor {number}."


def reset_active_monitor() -> None:
    """Return to automatically following the focused window."""
    global _active_monitor_index
    _active_monitor_index = None


def parse_monitor_phrase(text: str) -> Optional[int]:
    """Parse 'look at my second monitor' / 'monitor 2' into a 1-based index."""
    if not text:
        return None
    words = {
        "first": 1, "primary": 1, "main": 1, "one": 1, "1": 1,
        "second": 2, "two": 2, "2": 2,
        "third": 3, "three": 3, "3": 3,
        "fourth": 4, "four": 4, "4": 4,
    }
    lowered = text.lower()
    if "monitor" not in lowered and "display" not in lowered and "screen" not in lowered:
        return None
    for word, number in words.items():
        if re.search(rf"\b{word}\b", lowered):
            return number
    return None


SYSTEM_PROMPT = """You are a visual computer-use agent operating a desktop GUI locally.
You receive a screenshot of the current screen. Interactive elements may be
marked with numbered magenta boxes like [1], [2], [3]. You must output ONE JSON
object per turn with these keys:

{
  "thought": "Brief reasoning about what is visible and the next action.",
  "action": "CLICK | DOUBLE_CLICK | DRAG | SCROLL_DOWN | SCROLL_UP | SCROLL_HORIZONTAL | SCROLL_SEARCH | ZOOM_CLICK | TYPE | KEY | WAIT | FINISH",
  "element_id": 3,          // optional: number of the marked box to target (preferred when a box exists)
  "coordinates": [x, y],    // fallback: 0-1000 normalized screen coords if no box fits
  "drag_to": [x2, y2],      // 0-1000 normalized end coords for DRAG
  "text": "...",            // payload for TYPE or KEY
  "subgoal_done": false     // true ONLY when the current subgoal is visibly complete
}

Rules:
- PREFER element_id when the target has a marked box: it gives exact clicking.
- If no box matches, use normalized coordinates.
- Keep thoughts short and grounded in what you see.
- Use SCROLL_SEARCH with "text" naming a control when it is not visible; the agent scrolls the pane within bounds and stops at the end.
- Use ZOOM_CLICK with "coordinates" at a tight cluster and "text" describing the target when icons are ambiguous; the agent crops and re-grounds on a crisp zoom.
- Use FINISH when the goal is complete or you are stuck.
- Prefer keyboard shortcuts (KEY) when the active app cheat sheet provides one.
- Do not click the same spot three times in a row; try something different.
- Set subgoal_done true only when the CURRENT subgoal is visibly complete.
- If you have repeated yourself or are unsure, prefer a keyboard shortcut or a
  menu/search action over another click. Never describe actions you cannot see."""


# Self-check asked on a fresh screenshot after an action. The action prompt's
# own "subgoal_done" flag is an intention; this pass requires visible evidence
# before the plan advances or the task is declared complete.
REFLECT_PROMPT = """You are verifying one step of a desktop automation task.
You are given the CURRENT screenshot after the last action, the subgoal, and
what the agent estimated it did. Decide whether the subgoal is now visibly
complete. Do NOT guess from intention alone: name the visible evidence.

Reply with ONLY a JSON object:
{
  "complete": true | false,
  "evidence": "short description of what you actually see",
  "next": "if incomplete, the single next action that would finish it"
}

Rules:
- "complete" is true only when the requested state is visibly present.
- An application merely being open does not satisfy later subgoals.
- If a dialog or splash screen is showing, the subgoal is not complete.
- Keep evidence and next under 120 characters each."""


# JSON-schema tool definition exposed to the local LLM.
DESCRIBE_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "describe_screen",
            "description": (
                "Describe what is currently on the screen ALOUD for a blind or "
                "low-vision user. Use when the user asks what's on screen, to read "
                "a dialog/error, or to find the focused control. Speaks the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "enum": ["overview", "focus", "dialogs", "text", "action"],
                        "description": "What to concentrate on. Default: overview.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


# A screen-description prompt engineered for blind / low-vision users.
# It deliberately avoids visual fluff ("a sleek blue button") and instead gives
# concise, structured, spatial information a screen-reader user can act on.
DESCRIBE_SCREEN_PROMPT = """You are describing a computer screen ALOUD to a blind user.
The user cannot see anything. Be concise, factual, and structured. Never mention
colors, styling, or visual decoration. Never say "as you can see" or "the screen
shows". Describe only what is functional and actionable.

Cover, in this order, but SKIP any section with nothing to report:
1. WINDOW: which application is active and its window/document title.
2. FOCUS: the currently focused control or selection (button, field, item).
3. ALERTS: any dialog, error, or notification, quote its exact text.
4. CONTENT: the essential text/content of the window, briefly.
5. NEXT: one concrete next action the user can take, if obvious.

Format with those short uppercase labels on separate lines. Keep the whole
response under 120 words. If the screen is empty or locked, say so plainly.
Do not invent details you cannot see."""


# Focus variants appended to the base prompt for targeted descriptions.
DESCRIBE_FOCUS_HINTS: dict[str, str] = {
    "overview": "Give a general overview of the whole screen.",
    "focus": "Concentrate on what has keyboard focus and what a keystroke would affect.",
    "dialogs": "Concentrate on any open dialog, error, or notification and its buttons.",
    "text": "Concentrate on reading the text content verbatim, top to bottom.",
    "action": "Concentrate on what the user can do next and the exact control or shortcut to use.",
}


@dataclass
class StepRecord:
    step: int
    goal: str
    thought: str
    action: str
    coordinates: Optional[list[float]]
    drag_to: Optional[list[float]]
    text: Optional[str]
    screenshot_path: str
    result: str
    element_id: Optional[int] = None
    app_title: str = ""
    app_label: str = ""
    recovery: str = ""
    subgoal_index: int = 0
    timestamp: float = field(default_factory=time.time)


class ScreenController:
    """Captures screens and executes precise GUI actions via pyautogui."""

    def __init__(self, monitor_index: Optional[int] = None):
        if mss is None:
            raise RuntimeError("mss is not installed. Run: pip install mss")
        if pyautogui is None:
            raise RuntimeError("pyautogui is not installed. Run: pip install pyautogui")
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        self._sct = mss.mss()
        self.monitors = self._discover_monitors()

        # A caller may pin a monitor; otherwise follow the user's global choice,
        # or the monitor holding the focused window.
        self.follow_focused = monitor_index is None and get_active_monitor() is None
        selected = monitor_index if monitor_index is not None else get_active_monitor()
        if selected is None:
            selected = self.focused_monitor_index()
        self.select_monitor(selected)

    def _discover_monitors(self) -> list[dict[str, int]]:
        """Normalize mss monitors into 1-based display descriptors."""
        raw = list(self._sct.monitors or [])
        if not raw:
            raw = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]
        # mss.monitors[0] is the virtual rectangle spanning every display.
        actual = raw[1:] if len(raw) > 1 else raw
        return [
            {
                "index": index,
                "left": int(mon["left"]),
                "top": int(mon["top"]),
                "width": int(mon["width"]),
                "height": int(mon["height"]),
            }
            for index, mon in enumerate(actual, start=1)
        ]

    def focused_monitor_index(self) -> int:
        """Return the monitor containing the currently focused window."""
        try:
            from tools.window_tools import list_windows, monitor_for_rect

            focused = next((w for w in list_windows() if w.focused), None)
            if focused is not None:
                return monitor_for_rect(
                    focused.left, focused.top, focused.width, focused.height,
                    self.monitors,
                )
        except Exception:
            logger.debug("Focused monitor detection failed", exc_info=True)
        return 1

    def select_monitor(self, index: int) -> None:
        """Pin capture and click mapping to a 1-based monitor index."""
        monitor = next((m for m in self.monitors if m["index"] == index), self.monitors[0])
        self.monitor_index = monitor["index"]
        # mss.grab expects a dict with left/top/width/height.
        self.monitor = {
            "left": monitor["left"],
            "top": monitor["top"],
            "width": monitor["width"],
            "height": monitor["height"],
        }
        self._width = monitor["width"]
        self._height = monitor["height"]
        self._left = monitor["left"]
        self._top = monitor["top"]
        logger.info(
            "ScreenController on monitor %s: %dx%d at (%d,%d)",
            self.monitor_index, self._width, self._height, self._left, self._top,
        )

    def list_monitors(self) -> list[dict[str, int]]:
        return list(self.monitors)

    def _sync_monitor(self) -> None:
        selected = get_active_monitor()
        if selected is not None:
            if selected != self.monitor_index:
                self.select_monitor(selected)
        elif self.follow_focused:
            target = self.focused_monitor_index()
            if target != self.monitor_index:
                self.select_monitor(target)

    def capture(self, max_dim: Optional[int] = None) -> tuple[bytes, int, int]:
        self._sync_monitor()
        shot = self._sct.grab(self.monitor)
        img = np.array(shot)  # BGRA
        h, w = img.shape[:2]
        rgb = img[:, :, :3][:, :, ::-1].copy()  # BGRA->RGB
        pil = self._array_to_pil(rgb)

        # Adaptive cap from the hardware profile. Downscaling before base64
        # encoding cuts VLM inference time substantially on 4K/high-DPI screens.
        if max_dim is None:
            try:
                max_dim = int(os.getenv("MURMUR_MAX_SCREEN_DIM", "1280"))
            except ValueError:
                max_dim = 1280

        if max_dim > 0 and max(w, h) > max_dim:
            # Aspect-preserving LANCZOS resize. Callers stay in normalized
            # 0-1000 coordinates so Set-of-Marks mapping is unaffected.
            from system.profiler import downscale_png

            raw = io.BytesIO()
            pil.save(raw, format="PNG")
            png, w, h = downscale_png(raw.getvalue(), max_dim)
            return png, w, h

        buf = io.BytesIO()
        pil.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), w, h

    def to_base64(self, png_bytes: bytes) -> str:
        return base64.b64encode(png_bytes).decode("ascii")

    def resolution(self) -> tuple[int, int]:
        return self._width, self._height

    @staticmethod
    def _norm_to_px(norm: list[float], width: int, height: int) -> tuple[int, int]:
        x = int(max(0, min(1000, norm[0])) / 1000 * width)
        y = int(max(0, min(1000, norm[1])) / 1000 * height)
        return x, y

    def norm_to_global(self, x: float, y: float) -> tuple[int, int]:
        """Map normalized 0-1000 coords to global screen (x, y).

        Includes the active monitor's left/top offset, which can be negative
        when a secondary display sits to the left of the primary.
        """
        local_x, local_y = self._norm_to_px([x, y], self._width, self._height)
        return self._left + local_x, self._top + local_y

    @staticmethod
    def _action_cue(x: float, y: float) -> None:
        """Play a positioned cue right before acting on a UI element."""
        try:
            from system.settings_tools import load_settings

            if not load_settings().get("spatial_audio_cues", True):
                return
            from audio.earcons import play_spatial_cue

            play_spatial_cue(x, y)
        except Exception:  # pragma: no cover - optional audio
            pass

    @staticmethod
    def _cursor_event(px: float, py: float, kind: str = "click") -> None:
        """Show where the agent is about to act (never a fabricated action)."""
        try:
            tool_bus.emit(
                ServerMessage(type="cursor", x=int(px), y=int(py), kind=kind)
            )
        except Exception:  # pragma: no cover - reporting must never block an action
            logger.debug("Cursor overlay event failed", exc_info=True)

    def click(self, x: float, y: float) -> None:
        self._action_cue(x, y)
        px, py = self.norm_to_global(x, y)
        self._cursor_event(px, py)
        pyautogui.click(px, py)

    def double_click(self, x: float, y: float) -> None:
        self._action_cue(x, y)
        px, py = self.norm_to_global(x, y)
        self._cursor_event(px, py)
        pyautogui.doubleClick(px, py)

    def right_click(self, x: float, y: float) -> None:
        self._action_cue(x, y)
        px, py = self.norm_to_global(x, y)
        self._cursor_event(px, py)
        pyautogui.rightClick(px, py)

    def move_and_drag(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        self._action_cue(start_x, start_y)
        sx, sy = self.norm_to_global(start_x, start_y)
        ex, ey = self.norm_to_global(end_x, end_y)
        self._cursor_event(sx, sy, "drag")
        self._cursor_event(ex, ey, "drag")
        pyautogui.moveTo(sx, sy)
        pyautogui.dragTo(ex, ey)

    def scroll(self, direction: str, amount: int = 3) -> None:
        """Scroll the active pane: down/up vertically, left/right horizontally."""
        direction = (direction or "down").lower()
        if direction in {"down", "up"}:
            delta = -abs(int(amount)) if direction == "down" else abs(int(amount))
            pyautogui.scroll(delta)
        elif direction in {"horizontal", "left", "right"}:
            key = "right" if direction == "right" else "left"
            for _ in range(max(1, abs(int(amount)))):
                pyautogui.press(key)

    def click_global(self, x: int, y: int) -> None:
        """Click an absolute monitor pixel (used after crop-to-global mapping)."""
        self._action_cue(x, y)
        self._cursor_event(x, y)
        pyautogui.click(x, y)

    def type_text(self, text: str) -> None:
        pyautogui.write(text)

    def press_key(self, key: str) -> None:
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)

    @staticmethod
    def _downscale(img: np.ndarray, new_w: int, new_h: int) -> np.ndarray:
        h, w = img.shape[:2]
        ys = np.linspace(0, h, new_h + 1).astype(int)
        xs = np.linspace(0, w, new_w + 1).astype(int)
        out = np.empty((new_h, new_w, img.shape[2]), dtype=img.dtype)
        for i in range(new_h):
            for j in range(new_w):
                block = img[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
                if block.size:
                    out[i, j] = block.reshape(-1, block.shape[-1]).mean(axis=0)
        return out

    @staticmethod
    def _array_to_pil(rgb: np.ndarray):
        from PIL import Image  # type: ignore
        return Image.fromarray(rgb)


class VisionAgent:
    """ReAct visual task loop backed by a local Ollama VLM + SoM + app knowledge."""

    def __init__(
        self,
        model: str | None = None,
        host: str = OLLAMA_HOST,
        max_steps: int = MAX_STEPS_DEFAULT,
        controller: Optional[ScreenController] = None,
        safety: Optional[SafetyGate] = None,
        use_som: bool = True,
        use_app_knowledge: bool = True,
    ):
        self.model = resolve_vision_model() if model is None else normalize_model(model)
        self.host = normalize_ollama_host(host).rstrip("/")
        self.max_steps = max_steps
        self.controller = controller or ScreenController()
        self.safety = safety or SafetyGate()
        self.use_som = use_som
        self.use_app_knowledge = use_app_knowledge
        self._client = httpx.Client(base_url=self.host, timeout=180.0)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.history: list[StepRecord] = []

        # Planning / loop recovery / abort wiring.
        self.abort = abort_controller
        self.loop_detector = LoopDetector()
        self.plan: Optional[TaskPlan] = None
        self.last_preview: Optional[PlanPreview] = None
        self._recovery_attempts = 0
        self._recovery_hint = ""
        # Last capture detail, exposed for logging and tests.
        self.last_capture_detail = "standard"
        # Evidence check after each claimed completion. Disable only for
        # deterministic tests with mocked VLM responses: MURMUR_VLM_REFLECT=0.
        self.reflect = os.getenv("MURMUR_VLM_REFLECT", "1").strip() not in {"0", "false", "False"}
        self._announce_stop = self._make_stop_announcer()
        self.abort.add_listener(self._announce_stop)

        self._som = None
        self._app_kb = None
        if use_som:
            try:
                from agent.som_overlay import annotate_screenshot, resolve_element_id
                self._annotate = annotate_screenshot
                self._resolve_id = resolve_element_id
                self._som = True
            except Exception:
                logger.exception("SoM module unavailable; falling back to raw coords")
                self._som = None
        if use_app_knowledge:
            try:
                from agent.app_knowledge import detect_app_context
                self._detect_app = detect_app_context
                self._app_kb = True
            except Exception:
                logger.exception("App knowledge module unavailable")
                self._app_kb = None

    # ---- announcements ----

    @staticmethod
    def _speak(text: str) -> None:
        """Speak an announcement through the shared speaker, if available."""
        try:
            from audio.speaker_provider import get_speaker

            speaker = get_speaker()
            if speaker is not None:
                speaker.speak(text)
                return
        except Exception:  # pragma: no cover - defensive
            pass
        logger.info("[announce] %s", text)

    @staticmethod
    def _make_stop_announcer():
        """Build an abort listener that announces the reason aloud."""
        def announcer(reason: str) -> None:
            VisionAgent._speak(f"Automation stopped. {reason}")
            tool_bus.emit(
                ServerMessage(type="automation_stopped", text=f"Automation stopped. {reason}")
            )
        return announcer

    @staticmethod
    def _app_name_from_launch_subgoal(text: str) -> str:
        value = str(text or "").strip()
        if re.search(
            r"\b(and|then|project|file|document|new|save|delete|add|create|name)\b",
            value, re.IGNORECASE,
        ):
            return ""
        match = re.search(
            r"^\s*(?:please\s+)?(?:open|launch|start|run)\s+(?:up\s+)?(?:the\s+)?"
            r"(.+?)(?:\s+app(?:lication)?|\s+for\s+me)?\s*[.!]?\s*$",
            value, re.IGNORECASE,
        )
        if not match:
            return ""
        app = re.sub(r"^(?:my|the)\s+", "", match.group(1).strip(), flags=re.IGNORECASE)
        app = app.strip(" '\".,")
        return app if len(app) >= 2 and len(app.split()) <= 5 else ""

    def _capture_for_vlm(self) -> tuple[bytes, int, int]:
        """Capture a screen at the detail level this VLM can use well.

        Dynamic-resolution families (Qwen3-VL / Qwen3.5 / Qwen3.8) receive a
        full-detail frame (up to 4096x4096) on dense creative interfaces where
        small controls and timeline cells matter. Standard desktops keep the
        configured downscale so inference stays fast.
        """
        max_dim: Optional[int] = None
        try:
            from system.profiler import MAX_DYNAMIC_SCREEN_DIM, supports_dynamic_resolution
            from agent.app_knowledge import is_dense_creative_app

            if supports_dynamic_resolution(self.model) and self._app_kb:
                title = str(getattr(self._detect_app(), "title", "") or "")
                if is_dense_creative_app(title):
                    max_dim = MAX_DYNAMIC_SCREEN_DIM
        except Exception:
            logger.debug("Dynamic resolution check failed; using standard capture", exc_info=True)

        png, width, height = self.controller.capture(max_dim=max_dim)
        self.last_capture_detail = "high-resolution" if max_dim else "standard"
        return png, width, height

    def _app_already_open(self, text: str) -> bool:
        """Avoid re-launching an app that is already the active window."""
        app = self._app_name_from_launch_subgoal(text)
        if not app or not self._app_kb:
            return False
        try:
            title = str(getattr(self._detect_app(), "title", "") or "").lower()
        except Exception:
            return False
        return app.lower() in title

    @staticmethod
    def _launch_app_from_subgoal(text: str) -> bool:
        """Open an app deterministically when the subgoal is just 'open X'.

        A VLM cannot launch an installed app reliably by clicking; the OS tool
        resolves Start Menu shortcuts, App Paths and Store apps instead.
        """
        app = VisionAgent._app_name_from_launch_subgoal(text)
        if not app:
            return False
        from tools.os_tools import open_application

        result = open_application(app)
        if not result.startswith("Opened"):
            logger.info("Deterministic app launch failed for %r: %s", app, result)
            return False
        spoken = f"Opened {app}."
        VisionAgent._speak(spoken)
        tool_bus.emit(ServerMessage(type="transcript", text=spoken, role="system"))
        return True

    def _vision_model_available(self) -> tuple[bool, str]:
        """Check the exact vision model this agent will call before any action."""
        try:
            from setup import ollama_status, pulled_models

            status = ollama_status()
            if not status.get("running"):
                return False, "Ollama is not running, so the vision model cannot be used."
            if not pulled_models([self.model]).get(self.model):
                return False, f"Vision model {self.model} is not installed in Ollama."
        except Exception as exc:  # pragma: no cover - environment dependent
            return False, f"Vision check failed: {' '.join(str(exc).split())[:140]}"
        return True, ""

    def build_preview(self, goal: str) -> PlanPreview:
        """Read-only preview of the visual subgoals; no capture or clicking."""
        plan = build_plan(goal)
        steps = [subgoal.text for subgoal in plan.subgoals] or [goal]
        hints: list[str] = []
        joined = " ".join(steps).lower()
        for keyword, tool in (
            ("click", "pyautogui.click"),
            ("type", "pyautogui.write"),
            ("scroll", "pyautogui.scroll"),
            ("save", "file_tools"),
            ("open ", "os_tools"),
        ):
            if keyword in joined and tool not in hints:
                hints.append(tool)
        files = extract_files(steps)
        for name in extract_files(goal):
            if name not in files:
                files.append(name)
        return PlanPreview(
            goal=goal,
            steps=steps,
            tools=["vision_agent", *hints],
            files=files,
            engine="vision",
            plan=plan,
        )

    def run_visual_task(
        self,
        goal: str,
        max_steps: Optional[int] = None,
        dry_run: bool = False,
        plan: Optional[TaskPlan] = None,
        skip_indices: Optional[list[int]] = None,
    ) -> str:
        if dry_run:
            preview = self.build_preview(goal)
            self.last_preview = preview
            self._speak(preview.spoken())
            return preview.spoken()

        available, reason = self._vision_model_available()
        if not available:
            self._speak(reason)
            return reason

        # Resolved after planning: multi-step goals need more than the default
        # budget so the agent does not stop halfway through an app workflow.
        steps = max_steps or 0
        self.history = []
        self.abort.reset()  # a fresh task clears any previous abort signal
        self.loop_detector.reset()
        self._recovery_attempts = 0
        self._recovery_hint = ""
        self._fail_streak = 0

        # 1) Plan: break a multi-step goal into ordered subgoals, or reuse the
        #    approved preview so execution matches what the user heard.
        self.plan = plan or build_plan(goal)
        if not max_steps:
            steps = max(self.max_steps, len(self.plan.subgoals) * 4)
        for index in skip_indices or []:
            if 1 <= index <= len(self.plan.subgoals):
                self.plan.subgoals[index - 1].done = True
        while self.plan.current() and self.plan.current().done:
            self.plan.active_index += 1
        self._speak(
            f"Starting task with {len(self.plan.subgoals)} step"
            f"{'s' if len(self.plan.subgoals) != 1 else ''}."
        )
        logger.info("Starting visual task: %s | plan: %s (max %d steps)", goal,
                    [s.text for s in self.plan.subgoals], steps)

        for step in range(1, steps + 1):
            # --- hard abort check (spoken phrase / UI / failsafe listener) ---
            if self.abort.is_aborted():
                return f"Automation stopped: {self.abort.reason} (after {step - 1} steps)."

            # If the plan is complete, finish cleanly.
            if self.plan.all_done:
                self._speak("All steps are done.")
                return f"Task finished after {step - 1} step(s)."

            active = self.plan.current()
            if active is None:
                # An empty plan (e.g. a preview with everything skipped) has
                # no current step and must not be dereferenced.
                self._speak("Nothing to do.")
                return "Nothing to do."
            subgoal_idx = self.plan.active_index

            # An already-open app needs no launch; that subgoal is satisfied.
            if self._app_already_open(active.text):
                spoken = f"{VisionAgent._app_name_from_launch_subgoal(active.text)} is already open."
                self._speak(spoken)
                tool_bus.emit(ServerMessage(type="transcript", text=spoken, role="system"))
                self.plan.complete_current()
                self.loop_detector.mark_progress(self.plan.active_index)
                continue

            # Launch-only subgoals are handled by the OS resolver, not the VLM.
            if self._launch_app_from_subgoal(active.text):
                self.plan.complete_current()
                self.loop_detector.mark_progress(self.plan.active_index)
                continue

            # --- app context ---
            app_title, app_label, app_section = "", "", ""
            if self._app_kb:
                try:
                    ctx = self._detect_app()
                    app_title = ctx.title
                    app_label = ctx.profile_label
                    app_section = ctx.prompt_section
                    from skills.pack_loader import app_context, load_packs

                    app_section += "\n" + app_context(load_packs(), app_title)
                except Exception:
                    logger.exception("App context detection failed")

            # --- capture + SoM annotation ---
            png_bytes, width, height = self._capture_for_vlm()
            annotated_png = png_bytes
            element_map: dict[int, tuple[float, float]] = {}
            if self._som:
                try:
                    som_result = self._annotate(png_bytes)
                    annotated_png = base64.b64decode(som_result.annotated_png_base64)
                    element_map = {
                        eid: (el.center_x, el.center_y)
                        for eid, el in som_result.elements.items()
                    }
                except Exception:
                    logger.exception("SoM annotation failed; using raw screenshot")

            b64 = self.controller.to_base64(annotated_png)

            # --- ask the VLM (plan + bounded recent history + recovery hint) ---
            thought, action, element_id, coords, drag_to, text, subgoal_done = self._ask_vlm(
                goal, b64, width, height, app_section, element_map,
                self.plan, self._recovery_hint,
            )

            # Different local VLM families emit normalized or pixel coordinates.
            from system.profiler import normalize_vlm_coords

            if coords:
                coords = list(normalize_vlm_coords(coords, width, height, self.model))
            if drag_to:
                drag_to = list(normalize_vlm_coords(drag_to, width, height, self.model))

            # Resolve element_id to precise coordinates if the VLM chose a box.
            if action in ("CLICK", "DOUBLE_CLICK") and element_id is not None:
                resolved = element_map.get(element_id)
                if resolved:
                    coords = [resolved[0], resolved[1]]
                    logger.info("Resolved element_id %s -> %s", element_id, coords)

            record = StepRecord(
                step=step, goal=goal, thought=thought, action=action,
                coordinates=coords, drag_to=drag_to, text=text,
                screenshot_path="", result="", element_id=element_id,
                app_title=app_title, app_label=app_label,
                subgoal_index=subgoal_idx,
            )

            # --- persist step artifacts for replay ---
            step_dir = LOGS_DIR / f"step_{step:02d}"
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / "screen.png").write_bytes(png_bytes)
            (step_dir / "screen_som.png").write_bytes(annotated_png)
            meta = {
                "step": step, "goal": goal, "thought": thought, "action": action,
                "element_id": element_id, "coordinates": coords, "drag_to": drag_to,
                "text": text, "subgoal_index": subgoal_idx,
                "subgoal": active.text if active else "", "subgoal_done": subgoal_done,
                "app_title": app_title, "app_label": app_label,
                "resolution": [width, height],
                "capture_detail": self.last_capture_detail,
                "elements": {str(k): list(v) for k, v in element_map.items()},
            }
            (step_dir / "step.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            record.screenshot_path = str(step_dir / "screen_som.png")

            # --- FINISH is only a claim; verify it against the current screen ---
            if action == "FINISH":
                finish_png, _, _ = self._capture_for_vlm()
                finish_b64 = self.controller.to_base64(finish_png)
                confirmed = self._subgoal_complete(
                    active.text if active else goal, goal, finish_b64,
                    width, height, app_section, thought,
                )
                record.result = "FINISH (reflected: " + ("complete)" if confirmed else "incomplete)")
                self.history.append(record)
                if not confirmed:
                    time.sleep(STEP_SETTLE_S)
                    continue
                if active:
                    self.plan.complete_current()
                    self.loop_detector.mark_progress(self.plan.active_index)
                    self._speak(f"Done: {active.text}")
                if self.plan.all_done:
                    self._speak("All steps are done.")
                    return f"Task finished after {step} step(s)."
                continue

            # A single model failure is transient; try an alternative path
            # before giving up. Only repeated failures abort the task.
            if action == "FAIL":
                self._fail_streak += 1
                record.result = "FAIL"
                self.history.append(record)
                if self._fail_streak >= 2:
                    return (
                        f"Task stopped after {step} step(s): "
                        f"{thought or 'vision model unavailable'}"
                    )
                self._recovery_hint = (
                    "The vision model could not choose an action. Inspect the screen "
                    "and try a simpler direct step or an alternative path."
                )
                time.sleep(STEP_SETTLE_S)
                continue

            # --- bounded off-screen search and zoom re-grounding ---
            if action == "SCROLL_SEARCH":
                result = self._search_offscreen(text or (active.text if active else "target"))
                record.result = "searched:" + result.reason
                record.text = text
                self.history.append(record)
                time.sleep(STEP_SETTLE_S)
                continue

            if action == "ZOOM_CLICK":
                point = coords or [500, 500]
                global_point = self._zoom_ground(
                    png_bytes, (point[0], point[1]), reason=text or "dense cluster"
                )
                if global_point is not None:
                    self.controller.click_global(*global_point)
                    record.result = "clicked:zoom"
                else:
                    record.result = "zoom:no-target"
                record.coordinates = list(global_point) if global_point else coords
                self.history.append(record)
                time.sleep(STEP_SETTLE_S)
                continue

            # --- loop detection on the action BEFORE executing ---
            fp = action_fingerprint(action, element_id, coords, text)
            scr_hash = screen_hash(png_bytes)
            self.loop_detector.record(fp, scr_hash, subgoal_idx)
            status = self.loop_detector.assess(subgoal_idx)

            if status.stuck:
                outcome = self._recover(subgoal_idx, status, active)
                record.recovery = status.kind
                record.result = outcome
                self.history.append(record)
                if self.abort.is_aborted():
                    return f"Automation stopped: {self.abort.reason} (after {step} steps)."
                if outcome.startswith("guidance:"):
                    # User guidance is folded into the recovery hint for next step.
                    self.plan.subgoals[subgoal_idx].text += f" (user said: {outcome[9:][:120]})"
                # Recovery consumed this step; do not execute the loopy action.
                time.sleep(STEP_SETTLE_S)
                continue

            if action == "WAIT":
                time.sleep(STEP_SETTLE_S)
                record.result = "waited"
                self.history.append(record)
                continue

            # --- execute with failsafe handling ---
            after_png: Optional[bytes] = None
            try:
                executed = self._execute(action, coords, drag_to, text)
                if not executed:
                    # An unresolved element or unsupported action must never be
                    # logged (or spoken) as a completed GUI step.
                    record.result = "no-op"
                    self._recovery_hint = (
                        f"The last action ({action}) could not be performed: "
                        "missing target or unsupported action. Try an alternative path."
                    )
                    self.history.append(record)
                    time.sleep(STEP_SETTLE_S)
                    continue
                record.result = "executed"
                self._fail_streak = 0
                # Verify the action actually changed the UI. A static screen
                # after a click/shortcut feeds an alternative-path hint next step.
                if action not in {"WAIT", "FINISH", "FAIL", "DONE"}:
                    after_png = self._verify_post_action(png_bytes, action)
            except Exception as exc:
                # PyAutoGUI FailSafeException (mouse in a corner) aborts everything.
                if "failsafe" in type(exc).__name__.lower() or "fail-safe" in str(exc).lower():
                    self.abort.abort("failsafe triggered (mouse moved to a screen corner)")
                    record.result = "failsafe-abort"
                    self.history.append(record)
                    return f"Automation stopped: failsafe triggered after {step} steps."
                logger.exception("Action %s failed", action)
                record.result = f"error: {exc}"
                self.history.append(record)
                return f"Action {action} failed on step {step}: {exc}"

            # --- subgoal progress: decide from fresh-screen evidence, not the
            # model's optional `subgoal_done` flag. Small local models often
            # omit that flag even when the step is visibly complete. ---
            if after_png is None:
                fresh_png, _, _ = self._capture_for_vlm()
                after_png = fresh_png
            if after_png is not None:
                after_b64 = self.controller.to_base64(after_png)
                complete = self._subgoal_complete(
                    active.text if active else goal, goal, after_b64,
                    width, height, app_section, thought,
                )
                if not complete and subgoal_done:
                    record.result += "; subgoal not reflected as complete"
                    self.history.append(record)
                    time.sleep(STEP_SETTLE_S)
                    continue
                if complete:
                    self.plan.complete_current()
                    self.loop_detector.mark_progress(self.plan.active_index)
                    self._recovery_attempts = 0
                    self._recovery_hint = ""
                    if active:
                        self._speak(f"Done: {active.text}")
                        logger.info("Subgoal complete: %s", active.text)
                    from agent.checkpoint import record_progress

                    record_progress(
                        goal,
                        [s.text for s in self.plan.subgoals],
                        [s.text for s in self.plan.subgoals if s.done],
                        self.plan.active_index,
                    )
                    if self.plan.all_done:
                        self._speak("All steps are done.")
                        return f"Task finished after {step} step(s)."

            self.history.append(record)
            time.sleep(STEP_SETTLE_S)

        return f"Reached max steps ({steps}) without FINISH. See {LOGS_DIR} for replay."

    def _verify_post_action(self, before_png: bytes, action: str) -> Optional[bytes]:
        """Compare the screen after an action; return the fresh screenshot.

        The returned frame is reused for evidence-based subgoal verification so
        the model re-checks the result instead of trusting its own intention.
        """
        from agent.screen_diff import verify_action

        after_png: Optional[bytes] = None
        try:
            time.sleep(STEP_SETTLE_S)
            after_png, _, _ = self._capture_for_vlm()
            result = verify_action(action.lower(), before_png, after_png)
            record = {"action": action, **{k: (v.value if hasattr(v, "value") else v) for k, v in result.items()}}
            logger.info("Post-action verification: %s", record)
            if result["verdict"].value == "no_change" and not result["satisfied"]:
                self._recovery_attempts += 1
                self._recovery_hint = (
                    f"RECOVERY: the last {action} did not change the screen. "
                    "Try a keyboard shortcut, the app menu, or a different control."
                )
        except Exception:  # pragma: no cover - verification must not break the loop
            logger.debug("Post-action verification failed", exc_info=True)
        return after_png

    def _subgoal_complete(
        self,
        active_text: str,
        goal: str,
        after_b64: str,
        width: int,
        height: int,
        app_section: str,
        thought: str,
    ) -> bool:
        """Require visible evidence before advancing the plan.

        With reflection disabled (deterministic tests) this keeps the previous
        trust-the-VLM behaviour. Otherwise a failed or negative check is a
        "no": the loop feeds the evidence back as a recovery hint and retries.
        """
        if not self.reflect:
            return True
        complete, evidence = self._reflect_on_subgoal(
            goal, active_text, after_b64, width, height, app_section, thought
        )
        if complete:
            self._recovery_hint = ""
            self._recovery_attempts = 0
            return True
        detail = evidence or "no visible evidence yet"
        self._recovery_attempts += 1
        self._recovery_hint = (
            f"RECOVERY: the current subgoal is not visibly done ({detail}). "
            "Inspect the screen and take the next single action. Do not claim completion "
            "until the requested state is visible."
        )
        return False

    def _search_offscreen(
        self,
        target: str,
        direction: str = "down",
        names: set[str] | None = None,
        max_scrolls: int = 6,
    ):
        """Scroll the active pane looking for a control not currently visible."""
        def observe() -> set[str]:
            if names is not None:
                return set(names)
            from tools.a11y_tree import capture_tree

            tree = capture_tree()
            return {element.name for element in tree.elements}

        def scroll(which: str) -> None:
            self.controller.scroll(which, 3)
            time.sleep(STEP_SETTLE_S)

        search = ScrollSearch(
            observe=observe,
            scroll=scroll,
            speak=self._speak,
            max_scrolls=max_scrolls,
        )
        return search.find(target, direction=direction)

    def _zoom_ground(
        self,
        png: bytes,
        point: tuple[float, float],
        reason: str = "",
        zoom: int = 2,
    ) -> tuple[int, int] | None:
        """Re-ground on a zoomed crop and translate the result to global coords."""
        import base64

        from agent.crop_zoom import crop_region, crop_to_global, quadrant_region

        monitor = self.controller.monitor
        region = quadrant_region(point, (monitor["width"], monitor["height"]))
        crop = crop_region(png, region, zoom=zoom)
        b64 = base64.b64encode(crop.png).decode("ascii")

        # Fresh Set-of-Marks on the crisp crop gives local IDs and boxes.
        from agent.som_overlay import annotate_screenshot

        som_result = annotate_screenshot(crop.png)
        label = ", ".join(
            f"[{eid}] {el.label}" for eid, el in list(som_result.elements.items())[:12]
        )
        prompt = (
            "Click the target in this zoomed region. "
            + (f"Reason: {reason}. " if reason else "")
            + f"Marked controls: {label}. "
            "Reply with one JSON object: {\"action\":\"CLICK\",\"coordinates\":[x,y]} "
            "using 0-1000 coords inside this crop."
        )
        try:
            response = self._chat_with_image("", prompt, b64, format_json=True)
            content = (response.get("message") or {}).get("content") or ""
            parsed = self._parse_vlm_json(content)
            coords = parsed[3]  # (thought, action, element_id, coordinates, ...)
            if not coords:
                return None
            return crop_to_global(
                (coords[0], coords[1]),
                crop.region,
                crop.source_size,
                monitor["left"],
                monitor["top"],
                (monitor["width"], monitor["height"]),
            )
        except Exception:  # pragma: no cover - VLM/backend dependent
            logger.debug("Zoom grounding failed", exc_info=True)
            return None

    def _recover(self, subgoal_idx: int, status, active) -> str:
        """Recovery policy: try an alternative path, then ask the user verbally."""
        self._recovery_attempts += 1
        logger.warning("Loop detected (%s): %s", status.kind, status.detail)

        if self._recovery_attempts == 1:
            # First recovery: nudge the VLM toward a different interaction path.
            self._recovery_hint = (
                "RECOVERY: you appear stuck. Do NOT repeat the same action. "
                "Try a keyboard shortcut, the application's menu or command/search palette, "
                "or click a different control to achieve the current subgoal."
            )
            self._speak("That didn't work. Trying a different approach.")
            return f"auto-recovery:{status.kind}"

        # Second (and later) recovery: stop spinning and ask the user for help.
        question = (
            f"I'm stuck on: {active.text if active else 'the current step'}. "
            f"{status.detail} What should I do instead?"
        )
        answer = tool_bus.request_guidance(question)
        if answer is None or not answer.strip():
            self.abort.abort("no guidance received while stuck")
            return "abort:no-guidance"
        return f"guidance:{answer.strip()}"

    @staticmethod
    def _ollama_error(response) -> str:
        """Pull Ollama's own error message without leaking HTTP client details."""
        try:
            data = response.json()
            detail = data.get("error") if isinstance(data, dict) else str(data)
        except Exception:
            detail = getattr(response, "text", "") or ""
        return " ".join(str(detail or "").split())[:240]

    @staticmethod
    def _shrink_b64_png(b64_png: str, max_dim: int = 768) -> str | None:
        """Downscale a capture for a retry, or None if it is already small."""
        try:
            from PIL import Image  # type: ignore

            raw = base64.b64decode(b64_png)
            image = Image.open(io.BytesIO(raw))
            if max(image.size) <= max_dim:
                return None
            image.thumbnail(
                (max_dim, max_dim),
                getattr(Image, "Resampling", Image).LANCZOS,
            )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:  # pragma: no cover - optional image backend
            return None

    def _chat_with_image(
        self, system: str, prompt: str, b64_png: str, format_json: bool = False
    ) -> dict:
        """Send a screen to Ollama using its native ``images`` field.

        Ollama's /api/chat expects string message content plus a separate
        ``images`` array. OpenAI-style ``image_url`` content parts return 400
        ("cannot unmarshal array into ... content of type string"), which made
        every vision step look like a dead model.
        """
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt, "images": [b64_png]},
            ],
            "stream": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        }
        # Ollama's vision models can return empty content when format=json is
        # forced; the prompt already asks for JSON and `_parse_vlm_json` extracts
        # it from plain text (including fenced replies).
        _ = format_json
        response = self._client.post("/api/chat", json=payload)
        status = getattr(response, "status_code", 200)

        # A 500 on a high-resolution capture is usually Ollama running out of
        # vision context. Retry once with a smaller image and context before
        # giving up, so one oversized frame does not kill the whole task.
        if status >= 500:
            detail = self._ollama_error(response)
            smaller = self._shrink_b64_png(b64_png)
            if smaller:
                payload["messages"][1]["images"] = [smaller]
                payload["options"] = {"num_ctx": 4096}
                response = self._client.post("/api/chat", json=payload)
                status = getattr(response, "status_code", 200)

        if status >= 400 or not getattr(response, "is_success", True):
            detail = self._ollama_error(response) or "no detail reported"
            raise RuntimeError(
                f"Local vision model could not answer ({status}): {detail}"
            )
        return response.json()

    def _reflect_on_subgoal(
        self,
        goal: str,
        subgoal: str,
        b64_png: str,
        width: int,
        height: int,
        app_section: str,
        last_thought: str,
    ) -> tuple[bool, str]:
        """Ask the VLM to verify the subgoal on a fresh post-action screenshot.

        Returns ``(complete, evidence)``. Any failure is treated as "not
        complete" so the agent never claims success without evidence.
        """
        system = REFLECT_PROMPT
        if app_section:
            system += "\n" + app_section
        prompt = (
            f"Overall goal: {goal}\n"
            f"Current subgoal: {subgoal}\n"
            f"Agent's last thought: {last_thought[:300]}\n"
            f"Screen resolution: {width}x{height}.\n"
            "Inspect the current screen and reply with ONLY the JSON object."
        )
        try:
            response = self._chat_with_image(system, prompt, b64_png, format_json=True)
            content = response.get("message", {}).get("content", "{}")
            data = self._extract_json(content)
            complete = _model_bool(data.get("complete", False))
            evidence = str(data.get("evidence") or data.get("next") or "").strip()[:160]
            return complete, evidence
        except Exception:
            logger.exception("VLM reflection failed; refusing to mark subgoal complete")
            return False, "verification unavailable"

    def _ask_vlm(
        self,
        goal: str,
        b64_png: str,
        width: int,
        height: int,
        app_section: str,
        element_map: dict[int, tuple[float, float]],
        plan: Optional[TaskPlan] = None,
        recovery_hint: str = "",
    ) -> tuple[str, str, Optional[int], Optional[list[float]], Optional[list[float]], Optional[str], bool]:
        history_summary = format_history(self.history)
        elements_desc = ""
        if element_map:
            # Keep geometry in the side map; the prompt only carries IDs.
            elements_desc = "Marked boxes: " + ", ".join(
                f"[{eid}]" for eid in element_map
            )
        system = SYSTEM_PROMPT + "\n" + elements_desc
        system += a11y_context(width, height)
        if app_section:
            system += "\n" + app_section
        if plan is not None:
            system += "\n" + plan.progress_section()
        if recovery_hint:
            system += "\n" + recovery_hint

        prompt = (
            f"Screen resolution: {width}x{height}.\n"
            f"Overall goal: {goal}\n"
            f"Recent actions (oldest to newest):\n{history_summary}\n"
            "Take the next single action for the CURRENT subgoal only. "
            "Reply with ONLY the JSON object."
        )

        try:
            response = self._chat_with_image(system, prompt, b64_png, format_json=True)
            content = response.get("message", {}).get("content", "{}")
        except Exception as exc:
            logger.exception("VLM request failed")
            detail = " ".join(str(exc).split())[:160] or type(exc).__name__
            # Never turn a failed model call into a successful FINISH.
            return f"Vision request failed: {detail}", "FAIL", None, None, None, None, False

        parsed = self._parse_vlm_json(content)
        if parsed[1] == "FAIL" and not parsed[0].strip():
            # An empty FAIL is not information: retry once with a smaller
            # capture before abandoning the task.
            smaller = self._shrink_b64_png(b64_png)
            if smaller:
                try:
                    retry = self._chat_with_image(system, prompt, smaller, format_json=True)
                    retried = self._parse_vlm_json(
                        retry.get("message", {}).get("content", "{}")
                    )
                    if retried[1] != "FAIL" or retried[0].strip():
                        return retried
                except Exception:  # pragma: no cover - retry is best effort
                    logger.debug("Vision empty-FAIL retry failed", exc_info=True)
            excerpt = " ".join(str(content or "").split())[:120]
            detail = f"Local vision model {self.model} did not return a usable action"
            if excerpt:
                detail += f" (reply: {excerpt})"
            return detail, "FAIL", None, None, None, None, False
        return parsed

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Parse a JSON object from a plain or fenced model reply."""
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else {}
            except (ValueError, TypeError):
                pass
        return {}

    @staticmethod
    def _parse_vlm_json(
        content: str,
    ) -> tuple[str, str, Optional[int], Optional[list[float]], Optional[list[float]], Optional[str], bool]:
        thought = ""
        action = "FAIL"
        element_id: Optional[int] = None
        coords: Optional[list[float]] = None
        drag_to: Optional[list[float]] = None
        text: Optional[str] = None
        subgoal_done = False
        data = VisionAgent._extract_json(content)
        if data:
            thought = str(data.get("thought", ""))[:500]
            action = str(data.get("action", "FAIL")).upper()
            if action not in VALID_ACTIONS:
                action = "FAIL"
            raw_id = data.get("element_id")
            if raw_id is not None:
                try:
                    element_id = int(raw_id)
                except (ValueError, TypeError):
                    element_id = None
            coords = _model_coords(data.get("coordinates"))
            drag_to = _model_coords(data.get("drag_to"))
            text = data.get("text")
            if text is not None:
                text = str(text)
            subgoal_done = _model_bool(data.get("subgoal_done", False))
        if not data:
            logger.warning("VLM returned non-JSON; refusing to claim completion. Content: %s", str(content)[:200])
        return thought, action, element_id, coords, drag_to, text, subgoal_done

    def _execute(
        self,
        action: str,
        coords: Optional[list[float]],
        drag_to: Optional[list[float]],
        text: Optional[str],
    ) -> bool:
        """Run one input action. Returns False when nothing was actually done."""
        if action == "CLICK" and coords:
            self.controller.click(coords[0], coords[1])
        elif action == "DOUBLE_CLICK" and coords:
            self.controller.double_click(coords[0], coords[1])
        elif action == "DRAG":
            if not coords or not drag_to:
                logger.warning("DRAG requires both coordinates and drag_to")
                return False
            self.controller.move_and_drag(coords[0], coords[1], drag_to[0], drag_to[1])
        elif action in {"SCROLL_DOWN", "SCROLL_UP", "SCROLL_HORIZONTAL"}:
            direction = action.replace("SCROLL_", "").lower()
            self.controller.scroll(direction, 3)
        elif action == "TYPE" and text:
            self.controller.type_text(text)
        elif action == "KEY" and text:
            self.controller.press_key(text)
        elif action == "WAIT":
            time.sleep(STEP_SETTLE_S)
        else:
            logger.warning("Unsupported or incomplete action: %s", action)
            return False
        return True

    # ---- accessibility: blind-user screen description ----

    def close(self) -> None:
        """Release listeners/clients owned by this short-lived agent."""
        try:
            self.abort.remove_listener(self._announce_stop)
        except Exception:  # pragma: no cover - partially initialized agent
            pass
        try:
            self._client.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def describe(self, focus: str = "overview") -> str:
        """Capture the screen and return a blind-friendly spoken description.

        Does not speak by itself, returns text so callers decide how to deliver
        it (TTS, HUD, both). See `describe_screen()` for the speaking tool.
        """
        if mss is None:
            return "Screen capture is unavailable (mss is not installed)."

        png_bytes, width, height = self.controller.capture()
        b64_png = base64.b64encode(png_bytes).decode("ascii")

        hint = DESCRIBE_FOCUS_HINTS.get(focus, DESCRIBE_FOCUS_HINTS["overview"])
        system = DESCRIBE_SCREEN_PROMPT + "\n" + hint
        try:
            prompt = (
                f"Screen resolution {width}x{height}. "
                "Describe this screen for the user now."
            )
            response = self._chat_with_image(system, prompt, b64_png)
            description = str(
                response.get("message", {}).get("content", "")
            ).strip()
        except Exception:  # pragma: no cover - network/model dependent
            logger.exception("Screen description request failed")
            return "I couldn't read the screen just now. Please try again."

        if not description:
            return "I couldn't make out anything useful on the screen."

        # Save the frame + description for replay/debugging.
        try:
            step_dir = LOGS_DIR / "describe"
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / "screen.png").write_bytes(png_bytes)
            (step_dir / "description.txt").write_text(description, encoding="utf-8")
        except OSError:  # pragma: no cover - defensive
            logger.debug("Could not save description log", exc_info=True)

        return description


def a11y_context(width: int, height: int) -> str:
    """Compact accessibility context for the VLM, empty when unavailable."""
    from tools.a11y_tree import a11y_table, capture_tree

    tree = capture_tree(int(width), int(height))
    if tree.available and tree.elements:
        return (
            "\nNative accessibility controls (prefer these by name for "
            "buttons, menus and inputs):\n" + a11y_table(tree.elements, limit=12)
        )
    return ""


def describe_screen(focus: str = "overview") -> str:
    """Tool: describe the current screen aloud for a blind/low-vision user.

    Captures with mss, queries the local vision model with a blind-optimized
    prompt, then speaks the result through the shared LocalSpeaker so the user
    never has to read a visual HUD. Returns the spoken description as text.
    """
    agent = VisionAgent()
    try:
        description = agent.describe(focus=focus)
    finally:
        # describe_screen is called per question; leaving the abort listener
        # registered made one abort announce N times after N descriptions.
        agent.close()

    # Speak it directly rather than requiring the user to look at any UI.
    speaker = None
    try:
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
    except Exception:  # pragma: no cover - defensive
        speaker = None
    if speaker is not None:
        try:
            if hasattr(speaker, "speak_streamed"):
                from audio.streaming import chunk_text

                speaker.speak_streamed(chunk_text(description))
            else:
                speaker.speak(description)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to speak screen description")
    else:
        logger.info("No speaker configured; screen description text only: %s", description)

    return description
