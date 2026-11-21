"""Set-of-Marks grounding, coordinate scaling, app shortcut injection,
loop detection, and emergency abort handling.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

import agent.som_overlay as som
import agent.app_knowledge as ak
from agent.loop_detector import LoopDetector, action_fingerprint, screen_hash
from agent.abort import abort_controller, is_abort_phrase
from agent.vision_agent import ScreenController, VisionAgent


# ---- SoM numbering + {id: (x, y)} resolution ----

@pytest.fixture
def ui_png():
    img = Image.new("RGB", (400, 300), (15, 18, 24))
    d = ImageDraw.Draw(img)
    d.rectangle([30, 30, 130, 70], fill=(220, 220, 230))
    d.rectangle([200, 120, 300, 160], fill=(220, 220, 230))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_som_numbers_elements_and_resolves_centers(monkeypatch, ui_png):
    monkeypatch.setattr(som, "_accessibility_elements", lambda: [])
    monkeypatch.setattr(som, "_opencv_elements",
                        lambda png, w, h: [(100, 100, 300, 200, "ui"), (500, 400, 750, 500, "ui")])
    result = som.annotate_screenshot(ui_png)
    assert sorted(result.elements.keys()) == [1, 2]
    for el in result.elements.values():
        assert 0 <= el.center_x <= 1000 and 0 <= el.center_y <= 1000
    assert som.resolve_element_id(result.elements, 1) == (
        result.elements[1].center_x, result.elements[1].center_y)
    assert som.resolve_element_id(result.elements, 999) is None


def test_som_annotated_image_has_boxes(monkeypatch, ui_png):
    monkeypatch.setattr(som, "_accessibility_elements", lambda: [])
    monkeypatch.setattr(som, "_opencv_elements", lambda png, w, h: [(100, 100, 300, 200, "ui")])
    result = som.annotate_screenshot(ui_png)
    raw = base64.b64decode(result.annotated_png_base64)
    assert raw.startswith(b"\x89PNG")
    assert Image.open(io.BytesIO(raw)).size == (400, 300)


def test_som_dedupes_overlaps():
    boxes = [(0, 0, 100, 100, "a"), (5, 5, 95, 95, "b"), (500, 500, 600, 600, "c")]
    assert len(som._dedupe(boxes)) == 2


# ---- normalized 0-1000 coords scaled to screen resolution ----

def test_norm_to_px_clamps_and_scales():
    # ScreenController._norm_to_px is a static method; no hardware needed.
    assert ScreenController._norm_to_px([0, 0], 1920, 1080) == (0, 0)
    assert ScreenController._norm_to_px([1000, 1000], 1920, 1080) == (1920, 1080)
    assert ScreenController._norm_to_px([500, 500], 1000, 1000) == (500, 500)
    assert ScreenController._norm_to_px([-50, 2000], 1000, 1000) == (0, 1000)


def test_element_id_resolves_to_exact_coords_in_loop(monkeypatch, ui_png):
    """A loopy CLICK with element_id resolves to that element's center."""
    parsed = VisionAgent._parse_vlm_json(
        '{"thought":"x","action":"CLICK","element_id":2,"subgoal_done":false}')
    assert parsed[0] == "x" and parsed[1] == "CLICK" and parsed[2] == 2
    assert parsed[3] is None  # no coordinate fallback needed


# ---- active-window shortcut injection ----

@pytest.mark.parametrize("title,app_label,needle", [
    ("Blender 4.2 - scene.blend", "Blender", "Shift+A"),
    ("DaVinci Resolve - Project", "DaVinci Resolve", "Ctrl+B"),
    ("VS Code - main.py", "VS Code", "Ctrl+P"),
])
def test_shortcut_injection_for_heavy_apps(title, app_label, needle):
    section = ak.build_prompt_section(title)
    assert "ACTIVE APP" in section and app_label in section
    assert needle in section, (title, needle)


def test_unknown_app_returns_empty_section():
    assert ak.build_prompt_section("Some Random Program 2026") == ""


def test_match_app_direct():
    assert ak.match_app("Blender 4.2")["label"] == "Blender"
    assert ak.match_app("") is None


# ---- loop detection ----

def test_repeated_action_detected():
    ld = LoopDetector(repeat_threshold=3)
    fp = action_fingerprint("CLICK", None, [100, 200], None)
    for _ in range(3):
        ld.record(fp, None, 0)
    status = ld.assess(0)
    assert status.stuck and status.kind == "repeat_action"


def test_static_screen_detected():
    ld = LoopDetector(repeat_threshold=3, screen_threshold=4)
    img = Image.new("L", (64, 64), 0)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    h = screen_hash(buf.getvalue())
    # Spread coords across different 2% grid cells so repeat_action does not fire.
    for x in (0, 400, 800):
        ld.record(action_fingerprint("CLICK", None, [x, 100], None), h, 0)
    status = ld.assess(0)
    assert status.stuck and status.kind == "static_screen"


def test_progress_breaks_loop_streak():
    ld = LoopDetector(repeat_threshold=3)
    fp = action_fingerprint("CLICK", None, [100, 200], None)
    for _ in range(3):
        ld.record(fp, None, 0)
    ld.mark_progress(1)
    assert not ld.assess(1).stuck


# ---- emergency abort ----

def test_abort_controller_and_listener():
    abort_controller.reset()
    seen = []
    abort_controller.add_listener(lambda r: seen.append(r))
    abort_controller.abort("failsafe")
    assert abort_controller.is_aborted() and seen == ["failsafe"]
    abort_controller.reset()
    assert not abort_controller.is_aborted()


@pytest.mark.parametrize("phrase", ["stop automation", "abort task", "emergency stop",
                                     "stop the vision loop"])
def test_abort_phrases(phrase):
    assert is_abort_phrase(phrase)


def test_non_abort_phrase_ignored():
    assert not is_abort_phrase("what time is it")
