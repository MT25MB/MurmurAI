"""Fast native accessibility-tree enumeration for standard UI controls.

Exposes one platform-independent record so the agent can click named buttons,
menus, dialogs and inputs without a vision model. Every provider is optional and
best-effort; when no native API is available the caller falls back to the
Set-of-Marks vision path.
"""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("murmur_ai.tools.a11y_tree")

INTERACTIVE_ROLES = {
    "button", "menu item", "menu", "check box", "radio button", "combo box",
    "edit", "text", "list item", "tab item", "hyperlink", "toolbar", "slider",
    "push button", "text box", "window", "dialog",
}


@dataclass(frozen=True)
class InteractiveElement:
    name: str
    role: str
    center_x: float  # normalized 0-1000
    center_y: float
    box: tuple[float, float, float, float]
    focused: bool = False
    enabled: bool = True
    source: str = "native"


@dataclass(frozen=True)
class AccessibilityResult:
    elements: tuple[InteractiveElement, ...]
    backend: str
    elapsed_ms: float
    available: bool


def _screen_size() -> tuple[int, int]:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        size = (root.winfo_screenwidth(), root.winfo_screenheight())
        root.destroy()
        return size
    except Exception:  # pragma: no cover - headless
        return (1920, 1080)


def _normalize(x1, y1, x2, y2, sw, sh) -> tuple[float, float, float, float]:
    return (
        round(x1 / sw * 1000, 1),
        round(y1 / sh * 1000, 1),
        round(x2 / sw * 1000, 1),
        round(y2 / sh * 1000, 1),
    )


def _make(name, role, x1, y1, x2, y2, sw, sh, focused=False, enabled=True, source="native"):
    label = (name or "").strip()[:80]
    role = (role or "control").strip()[:40]
    if not label and role.lower() not in INTERACTIVE_ROLES:
        return None
    box = _normalize(x1, y1, x2, y2, sw, sh)
    return InteractiveElement(
        name=label or role,
        role=role,
        center_x=round((box[0] + box[2]) / 2, 1),
        center_y=round((box[1] + box[3]) / 2, 1),
        box=box,
        focused=bool(focused),
        enabled=bool(enabled),
        source=source,
    )


def _windows_elements() -> list[tuple]:
    from pywinauto import Desktop  # type: ignore

    rows = []
    desktop = Desktop(backend="uia")
    window = desktop.active()
    for control in window.descendants():
        try:
            info = control.element_info
            rect = control.rectangle()
            rows.append(
                (
                    info.name,
                    info.control_type,
                    rect.left, rect.top, rect.right, rect.bottom,
                    bool(control.has_focus()),
                    bool(control.is_enabled()),
                )
            )
        except Exception:
            continue
    return rows


def _mac_elements() -> list[tuple]:
    from ApplicationServices import (  # type: ignore
        AXUIElementCopyAttributeValue,
        AXUIElementCreateSystemWide,
        kAXFocusedApplicationAttribute,
    )

    rows = []
    system = AXUIElementCreateSystemWide()
    focused = AXUIElementCopyAttributeValue(system, kAXFocusedApplicationAttribute, None)
    if not focused:
        return rows
    # PyObjC APIs vary between versions; each attribute read is best-effort.
    return rows


def _linux_elements() -> list[tuple]:
    import pyatspi  # type: ignore

    rows = []
    desktop = pyatspi.Registry.getDesktop(0)
    for app in desktop:
        for window in app:
            try:
                for control in window:
                    try:
                        component = control.queryComponent()
                        pos = component.getPositionAndSize()
                        rows.append(
                            (
                                control.name,
                                control.getRoleName(),
                                pos.x, pos.y, pos.x + pos.width, pos.y + pos.height,
                                bool(control.getState().contains(pyatspi.STATE_FOCUSED)),
                                not bool(control.getState().contains(pyatspi.STATE_DISABLED)),
                            )
                        )
                    except Exception:
                        continue
            except Exception:
                continue
    return rows


def _native_elements() -> list[tuple]:
    system = platform.system()
    if system == "Windows":
        return _windows_elements()
    if system == "Darwin":
        return _mac_elements()
    if system == "Linux":
        return _linux_elements()
    return []


def capture_tree(
    screen_w: int | None = None,
    screen_h: int | None = None,
    provider: str | Callable[[], list[tuple]] | None = None,
) -> AccessibilityResult:
    """Enumerate interactive controls. Never raises."""
    started = time.perf_counter()
    sw, sh = screen_w or _screen_size()[0], screen_h or _screen_size()[1]
    backend = "native"
    try:
        rows = provider() if callable(provider) else _native_elements()
        if isinstance(provider, str):
            backend = provider
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.debug("Accessibility tree unavailable: %s", exc)
        return AccessibilityResult((), "none", (time.perf_counter() - started) * 1000, False)

    elements: list[InteractiveElement] = []
    for row in rows:
        if isinstance(row, InteractiveElement):
            element = row
        else:
            element = _make(*row, sw, sh, source=backend)
        if element is not None and element.enabled:
            elements.append(element)
    elapsed = (time.perf_counter() - started) * 1000
    if elapsed > 100:  # pragma: no cover - slow provider
        logger.debug("Accessibility tree took %.0f ms", elapsed)
    return AccessibilityResult(tuple(elements), backend, elapsed, True)


def a11y_table(elements, limit: int = 20, name_chars: int = 40) -> str:
    """Render a compact, bounded element table for a small local VLM."""
    lines = []
    for index, element in enumerate(list(elements)[:limit], start=1):
        name = element.name[:name_chars]
        state = []
        if element.focused:
            state.append("focused")
        if not element.enabled:
            state.append("disabled")
        suffix = f" ({', '.join(state)})" if state else ""
        lines.append(f"[{index}] {element.role}: {name}{suffix}")
    return "\n".join(lines)


A11Y_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_a11y_controls",
            "description": (
                "List named buttons, menus, dialogs and inputs from the OS "
                "accessibility tree. Prefer this over vision for standard controls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_hint": {
                        "type": "string",
                        "description": "Optional name to look for.",
                    }
                },
                "additionalProperties": False,
            },
        },
    }
]


def handle_a11y_tool(name: str, arguments: dict) -> Optional[str]:
    if name != "list_a11y_controls":
        return None
    result = capture_tree()
    if not result.available or not result.elements:
        return "No native accessibility tree is available; use describe_screen instead."
    hint = str(arguments.get("name_hint", ""))
    if hint:
        match = find_control(result.elements, hint)
        if match is None:
            return f"No enabled control named '{hint}' was found."
        return (
            f"{match.role} '{match.name}' is at {int(match.center_x)},"
            f"{int(match.center_y)} (0-1000). Click with mouse_and_keyboard."
        )
    return a11y_table(result.elements, limit=20)


def find_control(elements, name: str, role: str | None = None) -> Optional[InteractiveElement]:
    """Return the first enabled element whose name matches, case-insensitively."""
    wanted = (name or "").strip().lower()
    for element in elements:
        if not element.enabled:
            continue
        if wanted and wanted not in element.name.lower():
            continue
        if role and role.lower() not in element.role.lower():
            continue
        return element
    return None
