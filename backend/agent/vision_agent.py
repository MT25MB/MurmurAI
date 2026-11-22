"""Visual computer-use agent loop for Murmur AI.

Drives local GUI automation for complex desktop apps (Blender, DaVinci Resolve,
browsers) entirely on-device via a local Ollama VLM (qwen2.5-vl:7b).

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
from agent.loop_detector import LoopDetector, action_fingerprint, screen_hash

logger = logging.getLogger("murmur_ai.agent.vision_agent")

DEFAULT_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5-vl:7b")
OLLAMA_HOST = (os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"
MAX_STEPS_DEFAULT = 15
STEP_SETTLE_S = 1.5  # let heavy apps render after each action

VALID_ACTIONS = {"CLICK", "DOUBLE_CLICK", "DRAG", "TYPE", "KEY", "WAIT", "FINISH"}

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
  "action": "CLICK | DOUBLE_CLICK | DRAG | TYPE | KEY | WAIT | FINISH",
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
- Use FINISH when the goal is complete or you are stuck.
- Prefer keyboard shortcuts (KEY) when the active app cheat sheet provides one.
- Do not click the same spot three times in a row; try something different.
- Set subgoal_done true only when the CURRENT subgoal is visibly complete.
- If you have repeated yourself or are unsure, prefer a keyboard shortcut or a
  menu/search action over another click. Never describe actions you cannot see."""


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
3. ALERTS: any dialog, error, or notification — quote its exact text.
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

    def click(self, x: float, y: float) -> None:
        self._action_cue(x, y)
        px, py = self.norm_to_global(x, y)
        pyautogui.click(px, py)

    def double_click(self, x: float, y: float) -> None:
        self._action_cue(x, y)
        px, py = self.norm_to_global(x, y)
        pyautogui.doubleClick(px, py)

    def right_click(self, x: float, y: float) -> None:
        self._action_cue(x, y)
        px, py = self.norm_to_global(x, y)
        pyautogui.rightClick(px, py)

    def move_and_drag(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        self._action_cue(start_x, start_y)
        sx, sy = self.norm_to_global(start_x, start_y)
        ex, ey = self.norm_to_global(end_x, end_y)
        pyautogui.moveTo(sx, sy)
        pyautogui.dragTo(ex, ey)

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
        model: str = DEFAULT_VISION_MODEL,
        host: str = OLLAMA_HOST,
        max_steps: int = MAX_STEPS_DEFAULT,
        controller: Optional[ScreenController] = None,
        safety: Optional[SafetyGate] = None,
        use_som: bool = True,
        use_app_knowledge: bool = True,
    ):
        self.model = model
        self.host = host.rstrip("/")
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
        self._recovery_attempts = 0
        self._recovery_hint = ""
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

    def run_visual_task(self, goal: str, max_steps: Optional[int] = None) -> str:
        steps = max_steps or self.max_steps
        self.history = []
        self.abort.reset()  # a fresh task clears any previous abort signal
        self.loop_detector.reset()
        self._recovery_attempts = 0
        self._recovery_hint = ""

        # 1) Plan: break a multi-step goal into ordered subgoals.
        self.plan = build_plan(goal)
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
            subgoal_idx = self.plan.active_index

            # --- app context ---
            app_title, app_label, app_section = "", "", ""
            if self._app_kb:
                try:
                    ctx = self._detect_app()
                    app_title = ctx.title
                    app_label = ctx.profile_label
                    app_section = ctx.prompt_section
                except Exception:
                    logger.exception("App context detection failed")

            # --- capture + SoM annotation ---
            png_bytes, width, height = self.controller.capture()
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
                "elements": {str(k): list(v) for k, v in element_map.items()},
            }
            (step_dir / "step.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            record.screenshot_path = str(step_dir / "screen_som.png")

            # --- FINISH from the model ends the whole task ---
            if action == "FINISH":
                record.result = "FINISH"
                self.history.append(record)
                self._speak("Task complete.")
                return f"Task finished after {step} step(s): {thought}"

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
            try:
                self._execute(action, coords, drag_to, text)
                record.result = "executed"
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

            # --- subgoal progress ---
            if subgoal_done:
                self.plan.complete_current()
                self.loop_detector.mark_progress(self.plan.active_index)
                self._recovery_attempts = 0
                self._recovery_hint = ""
                if active:
                    self._speak(f"Done: {active.text}")
                    logger.info("Subgoal complete: %s", active.text)
                if self.plan.all_done:
                    self._speak("All steps are done.")
                    return f"Task finished after {step} step(s)."

            self.history.append(record)
            time.sleep(STEP_SETTLE_S)

        return f"Reached max steps ({steps}) without FINISH. See {LOGS_DIR} for replay."

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
            elements_desc = "Marked boxes: " + ", ".join(
                f"[{eid}] at ({int(x)},{int(y)})" for eid, (x, y) in element_map.items()
            )
        system = SYSTEM_PROMPT + "\n" + elements_desc
        if app_section:
            system += "\n" + app_section
        if plan is not None:
            system += "\n" + plan.progress_section()
        if recovery_hint:
            system += "\n" + recovery_hint

        user_content = [
            {
                "type": "text",
                "text": (
                    f"Screen resolution: {width}x{height}.\n"
                    f"Overall goal: {goal}\n"
                    f"Recent actions (oldest to newest):\n{history_summary}\n"
                    "Take the next single action for the CURRENT subgoal only. "
                    "Reply with ONLY the JSON object."
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_png}"}},
        ]

        try:
            resp = self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    "stream": False,
                    "format": "json",
                    "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
        except Exception:
            logger.exception("VLM request failed")
            return "VLM unavailable; stopping.", "FINISH", None, None, None, None, False

        return self._parse_vlm_json(content)

    @staticmethod
    def _parse_vlm_json(
        content: str,
    ) -> tuple[str, str, Optional[int], Optional[list[float]], Optional[list[float]], Optional[str], bool]:
        thought = ""
        action = "FINISH"
        element_id: Optional[int] = None
        coords: Optional[list[float]] = None
        drag_to: Optional[list[float]] = None
        text: Optional[str] = None
        subgoal_done = False
        try:
            data = json.loads(content)
            thought = str(data.get("thought", ""))[:500]
            action = str(data.get("action", "FINISH")).upper()
            if action not in VALID_ACTIONS:
                action = "FINISH"
            raw_id = data.get("element_id")
            if raw_id is not None:
                try:
                    element_id = int(raw_id)
                except (ValueError, TypeError):
                    element_id = None
            raw_coords = data.get("coordinates")
            if raw_coords and len(raw_coords) == 2:
                coords = [float(raw_coords[0]), float(raw_coords[1])]
            raw_drag = data.get("drag_to")
            if raw_drag and len(raw_drag) == 2:
                drag_to = [float(raw_drag[0]), float(raw_drag[1])]
            text = data.get("text")
            if text is not None:
                text = str(text)
            subgoal_done = bool(data.get("subgoal_done", False))
        except json.JSONDecodeError:
            logger.warning("VLM returned non-JSON; treating as FINISH. Content: %s", content[:200])
        return thought, action, element_id, coords, drag_to, text, subgoal_done

    def _execute(
        self,
        action: str,
        coords: Optional[list[float]],
        drag_to: Optional[list[float]],
        text: Optional[str],
    ) -> None:
        if action == "CLICK" and coords:
            self.controller.click(coords[0], coords[1])
        elif action == "DOUBLE_CLICK" and coords:
            self.controller.double_click(coords[0], coords[1])
        elif action == "DRAG":
            if not coords or not drag_to:
                logger.warning("DRAG requires both coordinates and drag_to")
                return
            self.controller.move_and_drag(coords[0], coords[1], drag_to[0], drag_to[1])
        elif action == "TYPE" and text:
            self.controller.type_text(text)
        elif action == "KEY" and text:
            self.controller.press_key(text)
        elif action == "WAIT":
            time.sleep(STEP_SETTLE_S)
        else:
            logger.warning("Unsupported or incomplete action: %s", action)

    # ---- accessibility: blind-user screen description ----

    def describe(self, focus: str = "overview") -> str:
        """Capture the screen and return a blind-friendly spoken description.

        Does not speak by itself — returns text so callers decide how to deliver
        it (TTS, HUD, both). See `describe_screen()` for the speaking tool.
        """
        if mss is None:
            return "Screen capture is unavailable (mss is not installed)."

        png_bytes, width, height = self.controller.capture()
        b64_png = base64.b64encode(png_bytes).decode("ascii")

        hint = DESCRIBE_FOCUS_HINTS.get(focus, DESCRIBE_FOCUS_HINTS["overview"])
        system = DESCRIBE_SCREEN_PROMPT + "\n" + hint
        try:
            resp = self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        f"Screen resolution {width}x{height}. "
                                        "Describe this screen for the user now."
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64_png}"},
                                },
                            ],
                        },
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            description = str(
                resp.json().get("message", {}).get("content", "")
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


def describe_screen(focus: str = "overview") -> str:
    """Tool: describe the current screen aloud for a blind/low-vision user.

    Captures with mss, queries the local vision model with a blind-optimized
    prompt, then speaks the result through the shared LocalSpeaker so the user
    never has to read a visual HUD. Returns the spoken description as text.
    """
    agent = VisionAgent()
    description = agent.describe(focus=focus)

    # Speak it directly rather than requiring the user to look at any UI.
    speaker = None
    try:
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
    except Exception:  # pragma: no cover - defensive
        speaker = None
    if speaker is not None:
        try:
            speaker.speak(description)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to speak screen description")
    else:
        logger.info("No speaker configured; screen description text only: %s", description)

    return description
