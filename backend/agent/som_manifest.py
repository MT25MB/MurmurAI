"""Token-efficient element manifest for Set-of-Marks grounding.

One shared integer ID joins the annotated screenshot, a compact text table and
the model's action output. Geometry stays in a side map, not in the prompt, so
a small local VLM sees only short labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class ElementRecord:
    name: str
    role: str
    center_x: float
    center_y: float
    box: tuple[float, float, float, float] = (0, 0, 0, 0)
    source: str = "native"


@dataclass(frozen=True)
class Manifest:
    text: str
    positions: dict[int, tuple[float, float]] = field(default_factory=dict)


def _contained(a: ElementRecord, b: ElementRecord) -> bool:
    ax1, ay1, ax2, ay2 = a.box
    bx1, by1, bx2, by2 = b.box
    if ax2 <= ax1 or ay2 <= ay1 or bx2 <= bx1 or by2 <= by1:
        return False
    inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    return inter / max(1, min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1))) > 0.8


def _area(record: ElementRecord) -> float:
    x1, y1, x2, y2 = record.box
    return max(0, x2 - x1) * max(0, y2 - y1)


def merge_elements(elements: Iterable[ElementRecord], proximity: float = 8.0) -> list[ElementRecord]:
    """Drop contained duplicates and group nearby identical labels."""
    ordered = sorted(elements, key=_area)
    kept: list[ElementRecord] = []
    for element in ordered:
        duplicate = False
        for index, existing in enumerate(kept):
            if _contained(existing, element) and element.name.lower() == existing.name.lower():
                duplicate = True
                break
            if (
                element.name.lower() == existing.name.lower()
                and element.role.lower() == existing.role.lower()
                and abs(element.center_x - existing.center_x) <= proximity
                and abs(element.center_y - existing.center_y) <= proximity
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(element)
    return kept


def build_manifest(
    elements: Iterable[ElementRecord], limit: int = 24, name_chars: int = 32
) -> Manifest:
    """Render a bounded table: one line per element, no coordinates in text."""
    merged = merge_elements(elements)[:limit]
    lines: list[str] = []
    positions: dict[int, tuple[float, float]] = {}
    for index, element in enumerate(merged, start=1):
        label = (element.name or element.role)[:name_chars]
        role = "" if element.name else f" ({element.role})"
        lines.append(f"[{index}] {label}{role}")
        positions[index] = (round(element.center_x, 1), round(element.center_y, 1))
    return Manifest(text="\n".join(lines), positions=positions)
