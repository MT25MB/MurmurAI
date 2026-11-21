"""Set-of-Marks (SoM) Visual Grounding for Murmur AI.

Before sending a screenshot to the local VLM (qwen2.5-vl:7b), this module
detects interactive UI elements (buttons, inputs, icons) using OpenCV
edge/contour detection plus OS accessibility trees where available, draws
clean numbered bounding boxes onto a copy of the screenshot, and returns
both the annotated image (base64) and a map of {element_id: (center_x, center_y)
in normalized 0-1000 coords}.

The VLM can then either:
  * output `element_id: int`  -> resolved to exact center coordinates, or
  * output fallback normalized `[x, y]` coordinates.

All dependencies are optional with graceful fallbacks so the agent never
hard-crashes on missing accessibility libraries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

try:  # pragma: no cover - platform optional
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore
    np = None  # type: ignore

logger = logging.getLogger("murmur_ai.agent.som_overlay")


@dataclass
class MarkedElement:
    element_id: int
    # Normalized 0-1000 coords of the element center.
    center_x: float
    center_y: float
    # Normalized 0-1000 bounding box.
    box: tuple[float, float, float, float]  # (x1, y1, x2, y2)
    label: str = ""


@dataclass
class SomResult:
    annotated_png_base64: str
    elements: dict[int, MarkedElement] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    used_opencv: bool = False
    used_accessibility: bool = False


def _try_import_accessibility():
    """Return the best available accessibility backend for this OS."""
    import platform

    system = platform.system()
    if system == "Windows":
        try:
            from pywinauto import Desktop  # type: ignore

            return ("pywinauto", Desktop)
        except ImportError:
            pass
    elif system == "Darwin":
        try:
            import atomac  # type: ignore

            return ("atomac", atomac)
        except ImportError:
            try:
                import PyObjCTools  # type: ignore  # noqa: F401

                return ("pyobjc", None)
            except ImportError:
                pass
    else:  # Linux
        try:
            import pyatspi  # type: ignore

            return ("pyatspi", pyatspi)
        except ImportError:
            pass
    return (None, None)


def _accessibility_elements() -> list[tuple[float, float, float, float, str]]:
    """Return [(x1, y1, x2, y2, label)] in normalized 0-1000 screen coords."""
    backend, cls = _try_import_accessibility()
    if backend is None:
        return []

    elements: list[tuple[float, float, float, float, str]] = []
    try:
        if backend == "pywinauto":
            desktop = cls(backend="uia")
            window = desktop.active()
            for ctrl in window.descendants():
                try:
                    rect = ctrl.rectangle()
                    label = (ctrl.window_text() or ctrl.friendly_class_name() or "").strip()
                    if not label:
                        continue
                    elements.append(
                        (
                            round(rect.left / 1000 * 1000),  # placeholder; real scale below
                            round(rect.top / 1000 * 1000),
                            round(rect.right / 1000 * 1000),
                            round(rect.bottom / 1000 * 1000),
                            label[:40],
                        )
                    )
                except Exception:
                    continue
        elif backend in ("atomac", "pyobjc"):
            # macOS: enumerate the frontmost app's UI elements.
            app = cls.getFocusedApplication()
            for el in app.AXChildren or []:
                try:
                    pos = el.AXPosition
                    size = el.AXSize
                    label = (el.AXTitle or el.AXRole or "").strip()
                    elements.append(
                        (int(pos.x), int(pos.y), int(pos.x + size.width), int(pos.y + size.height), label[:40])
                    )
                except Exception:
                    continue
        elif backend == "pyatspi":
            desktop = cls.Desktop
            for app in desktop:
                for win in app:
                    try:
                        for el in win:
                            try:
                                bbox = el.queryComponent().getPositionAndSize()
                                label = (el.name or el.roleName or "").strip()
                                elements.append(
                                    (bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3], label[:40])
                                )
                            except Exception:
                                continue
                    except Exception:
                        continue
    except Exception:  # pragma: no cover - platform dependent
        logger.exception("Accessibility enumeration failed, falling back to OpenCV")

    # Normalize to 0-1000 using screen size if available.
    normalized: list[tuple[float, float, float, float, str]] = []
    try:
        import platform as _plat
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        for x1, y1, x2, y2, label in elements:
            normalized.append(
                (
                    round(x1 / sw * 1000),
                    round(y1 / sh * 1000),
                    round(x2 / sw * 1000),
                    round(y2 / sh * 1000),
                    label,
                )
            )
    except Exception:
        normalized = elements  # already-ish normalized best-effort

    return normalized


def _opencv_elements(png_bytes: bytes, screen_w: int, screen_h: int) -> list[tuple[float, float, float, float, str]]:
    """Detect UI-ish rectangular regions via edge/contour detection."""
    if cv2 is None or np is None:
        return []

    try:
        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        elements: list[tuple[float, float, float, float, str]] = []
        min_area = (screen_w * screen_h) * 0.0004  # ignore tiny specks
        max_area = (screen_w * screen_h) * 0.35  # ignore near-full-screen blobs
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if area < min_area or area > max_area:
                continue
            aspect = w / h if h else 0
            if aspect < 0.1 or aspect > 10:
                continue
            # Only keep reasonably button-sized regions.
            if w < 24 or h < 18:
                continue
            elements.append(
                (
                    round(x / screen_w * 1000),
                    round(y / screen_h * 1000),
                    round((x + w) / screen_w * 1000),
                    round((y + h) / screen_h * 1000),
                    "ui",
                )
            )
        return elements
    except Exception:  # pragma: no cover - defensive
        logger.exception("OpenCV element detection failed")
        return []


def _dedupe(
    elements: list[tuple[float, float, float, float, str]],
) -> list[tuple[float, float, float, float, str]]:
    """Merge heavily overlapping boxes to avoid duplicate marks."""
    merged: list[tuple[float, float, float, float, str]] = []
    for box in elements:
        x1, y1, x2, y2, label = box
        placed = False
        for i, (mx1, my1, mx2, my2, mlabel) in enumerate(merged):
            ix = max(0, min(x2, mx2) - max(x1, mx1))
            iy = max(0, min(y2, my2) - max(y1, my1))
            inter = ix * iy
            if inter > 0:
                area_a = (x2 - x1) * (y2 - y1)
                area_b = (mx2 - mx1) * (my2 - my1)
                if inter / min(area_a, area_b) > 0.5:
                    merged[i] = (mx1, my1, mx2, my2, mlabel or label)
                    placed = True
                    break
        if not placed:
            merged.append(box)
    return merged


def annotate_screenshot(png_bytes: bytes) -> SomResult:
    """Return an annotated screenshot (base64 PNG) + element map.

    Draws high-contrast numbered bounding boxes [1], [2], ... onto a copy of
    the screenshot so the VLM can refer to elements by id.
    """
    from PIL import Image, ImageDraw, ImageFont  # type: ignore

    img = Image.open(__import__("io").BytesIO(png_bytes)).convert("RGB")
    width, height = img.size

    # Gather candidate elements from accessibility first, then OpenCV.
    acc_elems = _accessibility_elements()
    used_accessibility = bool(acc_elems)

    ocv_elems = _opencv_elements(png_bytes, width, height)
    used_opencv = bool(ocv_elems)

    combined = acc_elems + ocv_elems
    combined = _dedupe(combined)

    # Limit to a readable number of marks.
    combined = combined[:40]

    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    elements: dict[int, MarkedElement] = {}
    for idx, (x1, y1, x2, y2, label) in enumerate(combined, start=1):
        # Convert normalized 0-1000 back to pixels for drawing.
        px1 = int(x1 / 1000 * width)
        py1 = int(y1 / 1000 * height)
        px2 = int(x2 / 1000 * width)
        py2 = int(y2 / 1000 * height)

        cx = (px1 + px2) / 2
        cy = (py1 + py2) / 2

        # Draw bounding box (high-contrast magenta outline).
        draw.rectangle([px1, py1, px2, py2], outline=(255, 0, 255, 255), width=3)

        # Draw the number badge.
        badge = f"[{idx}]"
        tw, th = draw.textsize(badge, font=font) if hasattr(draw, "textsize") else (len(badge) * 9, 16)
        bx = min(max(int(cx - tw / 2), 0), width - tw)
        by = max(int(cy - th / 2 - 6), 0)
        draw.rectangle([bx, by, bx + tw, by + th], fill=(255, 0, 255, 235))
        draw.text((bx, by), badge, fill=(255, 255, 255), font=font)

        elements[idx] = MarkedElement(
            element_id=idx,
            center_x=round(cx / width * 1000, 1),
            center_y=round(cy / height * 1000, 1),
            box=(x1, y1, x2, y2),
            label=label,
        )

    buf = __import__("io").BytesIO()
    img.save(buf, format="PNG", optimize=True)
    import base64

    return SomResult(
        annotated_png_base64=base64.b64encode(buf.getvalue()).decode("ascii"),
        elements=elements,
        width=width,
        height=height,
        used_opencv=used_opencv,
        used_accessibility=used_accessibility,
    )


def resolve_element_id(
    elements: dict[int, MarkedElement], element_id: int
) -> Optional[tuple[float, float]]:
    """Resolve an element_id to normalized (center_x, center_y) coords."""
    el = elements.get(element_id)
    if el is None:
        return None
    return (el.center_x, el.center_y)
