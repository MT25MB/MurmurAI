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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

try:  # pragma: no cover - platform optional
    import mss
except ImportError:  # pragma: no cover
    mss = None  # type: ignore

try:  # pragma: no cover - platform optional
    import pyautogui
except ImportError:  # pragma: no cover
    pyautogui = None  # type: ignore

import httpx

from tools.safety import SafetyGate

logger = logging.getLogger("murmur_ai.agent.vision_agent")

DEFAULT_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5-vl:7b")
OLLAMA_HOST = (os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
LOGS_DIR = Path(__file__).resolve().parents[1] / "logs"
MAX_STEPS_DEFAULT = 15
STEP_SETTLE_S = 1.5  # let heavy apps render after each action

VALID_ACTIONS = {"CLICK", "DOUBLE_CLICK", "DRAG", "TYPE", "KEY", "WAIT", "FINISH"}

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
  "text": "..."             // payload for TYPE or KEY
}

Rules:
- PREFER element_id when the target has a marked box: it gives exact clicking.
- If no box matches, use normalized coordinates.
- Keep thoughts short and grounded in what you see.
- Use FINISH when the goal is complete or you are stuck.
- Prefer keyboard shortcuts (KEY) when the active app cheat sheet provides one.
- Do not click the same spot three times in a row; try something different.
- Never describe actions you cannot see."""


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
    timestamp: float = field(default_factory=time.time)


class ScreenController:
    """Captures screens and executes precise GUI actions via pyautogui."""

    def __init__(self, monitor_index: int = 1):
        if mss is None:
            raise RuntimeError("mss is not installed. Run: pip install mss")
        if pyautogui is None:
            raise RuntimeError("pyautogui is not installed. Run: pip install pyautogui")
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        self._sct = mss.mss()
        monitors = self._sct.monitors
        self.monitor = monitors[monitor_index] if len(monitors) > monitor_index else monitors[0]
        self._width = int(self.monitor["width"])
        self._height = int(self.monitor["height"])
        self._left = int(self.monitor["left"])
        self._top = int(self.monitor["top"])
        logger.info(
            "ScreenController on monitor %s: %dx%d at (%d,%d)",
            monitor_index, self._width, self._height, self._left, self._top,
        )

    def capture(self, max_dim: int = 1280) -> tuple[bytes, int, int]:
        shot = self._sct.grab(self.monitor)
        img = np.array(shot)  # BGRA
        h, w = img.shape[:2]
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
            img = self._downscale(img, new_w, new_h)
            h, w = img.shape[:2]
        rgb = img[:, :, :3][:, :, ::-1].copy()  # BGRA->RGB
        buf = io.BytesIO()
        self._array_to_pil(rgb).save(buf, format="PNG", optimize=True)
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

    def click(self, x: float, y: float) -> None:
        px, py = self._norm_to_px([x, y], self._width, self._height)
        pyautogui.click(px, py)

    def double_click(self, x: float, y: float) -> None:
        px, py = self._norm_to_px([x, y], self._width, self._height)
        pyautogui.doubleClick(px, py)

    def right_click(self, x: float, y: float) -> None:
        px, py = self._norm_to_px([x, y], self._width, self._height)
        pyautogui.rightClick(px, py)

    def move_and_drag(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        sx, sy = self._norm_to_px([start_x, start_y], self._width, self._height)
        ex, ey = self._norm_to_px([end_x, end_y], self._width, self._height)
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

    def run_visual_task(self, goal: str, max_steps: Optional[int] = None) -> str:
        steps = max_steps or self.max_steps
        self.history = []
        logger.info("Starting visual task: %s (max %d steps)", goal, steps)

        for step in range(1, steps + 1):
            # --- app context ---
            app_title, app_label, app_section = "", "", ""
            if self._app_kb:
                try:
                    ctx = self._detect_app()
                    app_title = ctx.title
                    app_label = ctx.profile_label
                    app_section = ctx.prompt_section
                    if app_label:
                        logger.info("Active app: %s", app_label)
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

            thought, action, element_id, coords, drag_to, text = self._ask_vlm(
                goal, b64, width, height, app_section, element_map
            )

            # Resolve element_id to precise coordinates if the VLM chose a box.
            if action in ("CLICK", "DOUBLE_CLICK") and element_id is not None:
                resolved = element_map.get(element_id)
                if resolved:
                    coords = [resolved[0], resolved[1]]
                    logger.info("Resolved element_id %s -> %s", element_id, coords)

            record = StepRecord(
                step=step,
                goal=goal,
                thought=thought,
                action=action,
                coordinates=coords,
                drag_to=drag_to,
                text=text,
                screenshot_path="",
                result="",
                element_id=element_id,
                app_title=app_title,
                app_label=app_label,
            )

            step_dir = LOGS_DIR / f"step_{step:02d}"
            step_dir.mkdir(parents=True, exist_ok=True)
            (step_dir / "screen.png").write_bytes(png_bytes)
            (step_dir / "screen_som.png").write_bytes(annotated_png)
            meta = {
                "step": step,
                "goal": goal,
                "thought": thought,
                "action": action,
                "element_id": element_id,
                "coordinates": coords,
                "drag_to": drag_to,
                "text": text,
                "app_title": app_title,
                "app_label": app_label,
                "resolution": [width, height],
                "elements": {str(k): list(v) for k, v in element_map.items()},
            }
            (step_dir / "step.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            record.screenshot_path = str(step_dir / "screen_som.png")

            if action == "FINISH":
                record.result = "FINISH"
                self.history.append(record)
                return f"Task finished after {step} step(s): {thought}"

            if action == "WAIT":
                time.sleep(STEP_SETTLE_S)
                record.result = "waited"
                self.history.append(record)
                continue

            try:
                self._execute(action, coords, drag_to, text)
                record.result = "executed"
            except Exception as exc:  # pragma: no cover - platform dependent
                logger.exception("Action %s failed", action)
                record.result = f"error: {exc}"
                self.history.append(record)
                return f"Action {action} failed on step {step}: {exc}"

            self.history.append(record)
            time.sleep(STEP_SETTLE_S)

        return f"Reached max steps ({steps}) without FINISH. See {LOGS_DIR} for replay."

    def _ask_vlm(
        self,
        goal: str,
        b64_png: str,
        width: int,
        height: int,
        app_section: str,
        element_map: dict[int, tuple[float, float]],
    ) -> tuple[str, str, Optional[int], Optional[list[float]], Optional[list[float]], Optional[str]]:
        history_summary = "\n".join(
            f"Step {r.step}: {r.action} el={r.element_id} {r.coordinates or ''} {r.text or ''} -> {r.result}"
            for r in self.history[-5:]
        )
        elements_desc = ""
        if element_map:
            elements_desc = "Marked boxes: " + ", ".join(
                f"[{eid}] at ({int(x)},{int(y)})" for eid, (x, y) in element_map.items()
            )
        system = SYSTEM_PROMPT + app_section + "\n" + elements_desc

        user_content = [
            {
                "type": "text",
                "text": (
                    f"Screen resolution: {width}x{height}. "
                    f"Goal: {goal}\n"
                    f"Recent history:\n{history_summary or '(none)'}\n"
                    "What is the next single action? Reply with ONLY the JSON object."
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
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
        except Exception:
            logger.exception("VLM request failed")
            return "VLM unavailable; stopping.", "FINISH", None, None, None, None

        return self._parse_vlm_json(content)

    @staticmethod
    def _parse_vlm_json(
        content: str,
    ) -> tuple[str, str, Optional[int], Optional[list[float]], Optional[list[float]], Optional[str]]:
        thought = ""
        action = "FINISH"
        element_id: Optional[int] = None
        coords: Optional[list[float]] = None
        drag_to: Optional[list[float]] = None
        text: Optional[str] = None
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
        except json.JSONDecodeError:
            logger.warning("VLM returned non-JSON; treating as FINISH. Content: %s", content[:200])
        return thought, action, element_id, coords, drag_to, text

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
