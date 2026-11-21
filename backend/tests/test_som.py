"""Set-of-Marks element detection and coordinate mapping (mocked OpenCV)."""

from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

import agent.som_overlay as som


@pytest.fixture
def synthetic_ui():
    """A 400x300 dark UI with two bright buttons as PNG bytes."""
    img = Image.new("RGB", (400, 300), (15, 18, 24))
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 120, 60], fill=(220, 220, 230))   # button A
    d.rectangle([200, 100, 300, 140], fill=(220, 220, 230))  # button B
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_resolve_element_id():
    elements = {
        1: som.MarkedElement(1, 250.0, 133.3, (200, 100, 300, 166), "ui"),
        2: som.MarkedElement(2, 750.0, 500.0, (700, 400, 800, 600)),
    }
    assert som.resolve_element_id(elements, 1) == (250.0, 133.3)
    assert som.resolve_element_id(elements, 2) == (750.0, 500.0)
    assert som.resolve_element_id(elements, 99) is None


def test_coordinates_normalized_to_1000(monkeypatch, synthetic_ui):
    """Detected centers are stored normalized 0-1000, not raw pixels."""
    monkeypatch.setattr(som, "_accessibility_elements", lambda: [])
    # Deterministic contour output: two boxes on a 400x300 image.
    monkeypatch.setattr(
        som, "_opencv_elements",
        lambda png, w, h: [(50, 66, 300, 200, "ui"), (500, 333, 750, 466, "ui")],
    )
    result = som.annotate_screenshot(synthetic_ui)
    assert len(result.elements) == 2
    for el in result.elements.values():
        assert 0 <= el.center_x <= 1000
        assert 0 <= el.center_y <= 1000
    # boxes are supplied already-normalized; the stored center is their midpoint
    first = result.elements[1]
    assert 170 <= first.center_x <= 180 and 125 <= first.center_y <= 140


def test_annotated_output_is_valid_png(monkeypatch, synthetic_ui):
    monkeypatch.setattr(som, "_accessibility_elements", lambda: [])
    monkeypatch.setattr(som, "_opencv_elements", lambda png, w, h: [(100, 100, 400, 300, "ui")])
    result = som.annotate_screenshot(synthetic_ui)
    raw = base64.b64decode(result.annotated_png_base64)
    assert raw.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(raw))
    assert img.size == (400, 300)


def test_dedupe_overlapping_boxes():
    boxes = [(0, 0, 100, 100, "a"), (5, 5, 95, 95, "b"), (500, 500, 600, 600, "c")]
    merged = som._dedupe(boxes)
    assert len(merged) == 2
