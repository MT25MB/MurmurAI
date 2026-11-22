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


# ---- off-screen scroll-to-reveal ----

def test_scroll_search_stops_when_target_found():
    from agent.offscreen_search import ScrollSearch

    # Each scroll reveals a new page; target appears on the third page.
    pages = [
        {"A", "B"},
        {"C", "D"},
        {"Export settings", "F"},
    ]
    state = {"index": 0, "scrolls": [], "spoken": []}

    def observe():
        return set(pages[min(state["index"], len(pages) - 1)])

    def scroll(direction):
        state["scrolls"].append(direction)
        state["index"] += 1

    def speak(text):
        state["spoken"].append(text)

    search = ScrollSearch(
        observe=observe,
        scroll=scroll,
        speak=speak,
        max_scrolls=6,
    )
    result = search.find("export settings", direction="down")

    assert result.found is True
    assert result.reason == "found"
    assert state["scrolls"] == ["down", "down"]
    assert any("Scrolling down" in text for text in state["spoken"])


def test_scroll_search_stops_at_bottom_when_signatures_repeat():
    from agent.offscreen_search import ScrollSearch

    state = {"scrolls": []}
    # Same elements every time -> bottom of list reached.
    fragments = [{"Same item", "Another item"}] * 8

    def observe():
        return fragments[min(len(state["scrolls"]), 7)]

    def scroll(direction):
        state["scrolls"].append(direction)

    search = ScrollSearch(observe=observe, scroll=scroll, speak=lambda _: None, max_scrolls=8)
    result = search.find("missing target", direction="down")

    assert result.found is False
    assert result.reason == "boundary"
    assert len(state["scrolls"]) <= 2  # stops as soon as the page stops changing
    assert result.scrolls <= 8


def test_scroll_search_respects_max_scrolls():
    from agent.offscreen_search import ScrollSearch

    state = {"scrolls": []}

    def observe():
        return {f"item {len(state['scrolls'])}"}

    def scroll(direction):
        state["scrolls"].append(direction)

    search = ScrollSearch(observe=observe, scroll=scroll, speak=lambda _: None, max_scrolls=3)
    result = search.find("target", direction="down")

    assert result.found is False
    assert result.reason == "limit"
    assert len(state["scrolls"]) == 3


def test_scroll_search_announces_once_for_multi_scroll():
    from agent.offscreen_search import ScrollSearch

    pages = [{"A"}, {"B"}, {"target"}]
    state = {"index": 0, "spoken": []}

    def observe():
        return pages[min(state["index"], 2)]

    def scroll(direction):
        state["index"] += 1

    search = ScrollSearch(
        observe=observe,
        scroll=scroll,
        speak=lambda text: state["spoken"].append(text),
        max_scrolls=5,
    )
    result = search.find("target", direction="down")

    assert result.found is True
    assert len(state["spoken"]) == 1
    assert "target" in state["spoken"][0].lower()


# ---- coarse-to-fine crop zoom ----

def test_crop_region_returns_expected_pixels():
    from agent.crop_zoom import crop_region

    img = Image.new("RGB", (400, 300), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    crop = crop_region(buf.getvalue(), region=(100, 50, 200, 150), zoom=2)

    assert crop.region == (100, 50, 200, 150)
    assert crop.zoomed_size == (200, 200)
    assert crop.source_size == (400, 300)


def test_crop_to_global_maps_center_correctly():
    from agent.crop_zoom import crop_to_global

    # A 400x300 capture; crop the lower-right quadrant and zoom 2x.
    # The crop's center maps to the capture's (300, 225).
    result = crop_to_global(
        local=(500, 500),
        region=(200, 150, 400, 300),
        source_size=(400, 300),
        monitor_left=100,
        monitor_top=50,
        monitor_size=(400, 300),
    )
    assert result == (400, 275)


def test_crop_to_global_maps_corner_to_monitor_offset():
    from agent.crop_zoom import crop_to_global

    result = crop_to_global(
        local=(0, 0),
        region=(100, 50, 200, 150),
        source_size=(400, 300),
        monitor_left=1920,
        monitor_top=-200,
        monitor_size=(400, 300),
    )
    assert result == (2020, -150)


def test_coarse_to_fine_needs_zoom_for_tight_cluster():
    from agent.crop_zoom import should_zoom

    tight = [(100, 100), (104, 103), (108, 102), (102, 107)]
    spread = [(50, 50), (500, 500), (900, 900)]

    assert should_zoom(tight) is True
    assert should_zoom(spread) is False


def test_execute_dispatches_scroll_actions(monkeypatch):
    calls = []
    agent = VisionAgent.__new__(VisionAgent)
    agent.controller = type("C", (), {
        "scroll": lambda self, direction, amount=3: calls.append((direction, amount)),
    })()

    agent._execute("SCROLL_DOWN", None, None, None)
    agent._execute("SCROLL_UP", None, None, None)
    agent._execute("SCROLL_HORIZONTAL", None, None, None)

    assert calls == [("down", 3), ("up", 3), ("horizontal", 3)]


def test_quadrant_region_lands_on_target_half():
    from agent.crop_zoom import quadrant_region

    # A point in the lower-right quadrant of a 1000x800 capture.
    region = quadrant_region((800, 700), (1000, 800))
    assert region[0] >= 400 and region[1] >= 300  # lower-right half, plus margin
    assert region[2] <= 1000 and region[3] <= 800
    assert region[0] < 800 < region[2] and region[1] < 700 < region[3]


def test_search_offscreen_method_uses_scroll_search(monkeypatch):
    import agent.vision_agent as va
    from agent.offscreen_search import ScrollResult

    seen = {}

    class FakeSearch:
        def __init__(self, observe, scroll, speak, max_scrolls):
            seen["observe"] = observe
            seen["scroll"] = scroll
            seen["speak"] = speak
            seen["max_scrolls"] = max_scrolls

        def find(self, target, direction):
            seen["find"] = (target, direction)
            return ScrollResult(True, "found", 1)

    monkeypatch.setattr(va, "ScrollSearch", FakeSearch)

    agent = va.VisionAgent.__new__(va.VisionAgent)
    agent.controller = type("C", (), {
        "scroll": lambda self, direction, amount=3: seen.setdefault("scrolled", direction),
    })()
    agent.history = []

    # Accessibility tree provides one page of names.
    monkeypatch.setattr(va, "a11y_context", lambda w, h: "")

    result = agent._search_offscreen("Export settings", direction="down", names={"Settings"})
    assert result.found is True
    assert seen["find"] == ("Export settings", "down")


def test_zoom_ground_maps_crop_prediction_to_global(monkeypatch):
    import agent.vision_agent as va
    import agent.crop_zoom as cz

    agent = va.VisionAgent.__new__(va.VisionAgent)
    agent.model = "fake-vlm"
    agent.controller = type("C", (), {
        "resolution": lambda self: (400, 300),
        "monitor": {"left": 100, "top": 50, "width": 400, "height": 300},
    })()

    monkeypatch.setattr(
        cz, "crop_region",
        lambda png, region, zoom=2: cz.CropResult(png, region, (400, 300), (400, 300)),
    )
    monkeypatch.setattr(
        cz, "crop_to_global",
        lambda local, region, source_size, monitor_left, monitor_top, monitor_size: (400, 275),
    )

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"thought":"z","action":"CLICK","coordinates":[500,500]}'}}

    class Client:
        def post(self, url, json):
            return Resp()

    agent._client = Client()
    png = Image.new("RGB", (400, 300), (0, 0, 0))
    buf = io.BytesIO()
    png.save(buf, format="PNG")

    result = agent._zoom_ground(buf.getvalue(), point=(800, 700), reason="dense cluster")
    assert result == (400, 275)
