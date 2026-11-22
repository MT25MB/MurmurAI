"""Coarse-to-fine region cropping for dense UIs.

When several candidate controls cluster tightly, a full-screen screenshot is too
coarse for a small local VLM. Crop the target quadrant, upscale it, run fresh
Set-of-Marks on the crisp crop, and translate local crop coordinates back to
global monitor coordinates before clicking.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class CropResult:
    png: bytes
    region: tuple[int, int, int, int]
    zoomed_size: tuple[int, int]
    source_size: tuple[int, int]

    @property
    def base64(self) -> str:
        return base64.b64encode(self.png).decode("ascii")


def crop_region(
    png_bytes: bytes,
    region: tuple[int, int, int, int],
    zoom: int = 2,
) -> CropResult:
    """Crop a region from a screenshot and upscale it by ``zoom``."""
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    source_size = image.size
    x1, y1, x2, y2 = region
    x1 = max(0, min(source_size[0], x1))
    y1 = max(0, min(source_size[1], y1))
    x2 = max(x1, min(source_size[0], x2))
    y2 = max(y1, min(source_size[1], y2))
    crop = image.crop((x1, y1, x2, y2))
    factor = max(1, int(zoom))
    zoomed = crop.resize((crop.width * factor, crop.height * factor), Image.LANCZOS)
    out = io.BytesIO()
    zoomed.save(out, format="PNG", optimize=True)
    return CropResult(
        png=out.getvalue(),
        region=(x1, y1, x2, y2),
        zoomed_size=zoomed.size,
        source_size=source_size,
    )


def crop_to_global(
    local: tuple[float, float],
    region: tuple[int, int, int, int],
    source_size: tuple[int, int],
    monitor_left: int,
    monitor_top: int,
    monitor_size: tuple[int, int],
) -> tuple[int, int]:
    """Map a 0-1000 coordinate inside a crop to an absolute monitor pixel."""
    x1, y1, x2, y2 = region
    crop_w = max(1, x2 - x1)
    crop_h = max(1, y2 - y1)
    lx = max(0, min(1000, local[0])) / 1000 * crop_w
    ly = max(0, min(1000, local[1])) / 1000 * crop_h
    source_x = x1 + lx
    source_y = y1 + ly
    global_x = monitor_left + int(source_x / max(1, source_size[0]) * monitor_size[0])
    global_y = monitor_top + int(source_y / max(1, source_size[1]) * monitor_size[1])
    return global_x, global_y


def should_zoom(points: list[tuple[float, float]], spread: float = 30.0) -> bool:
    """True when candidate points cluster tightly enough to need a zoom crop."""
    if len(points) < 2:
        return False
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(xs) - min(xs)) < spread and (max(ys) - min(ys)) < spread


def quadrant_region(
    point: tuple[float, float],
    source_size: tuple[int, int],
    margin: int = 40,
) -> tuple[int, int, int, int]:
    """Return the source-pixel region around the quadrant containing ``point``."""
    width, height = source_size
    px = max(0, min(width, point[0] / 1000 * width))
    py = max(0, min(height, point[1] / 1000 * height))
    half_w, half_h = width / 2, height / 2
    x1 = 0 if px < half_w else half_w
    y1 = 0 if py < half_h else half_h
    return (
        max(0, int(x1 - margin)),
        max(0, int(y1 - margin)),
        min(width, int(x1 + half_w + margin)),
        min(height, int(y1 + half_h + margin)),
    )
