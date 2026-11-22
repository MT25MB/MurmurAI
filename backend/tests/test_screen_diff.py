"""Lightweight post-action screen verification with explicit no-change verdict."""

from __future__ import annotations

import io

from PIL import Image

from agent.screen_diff import ScreenVerdict, diff_screens, verify_action


def _png(color=(255, 255, 255), size=(80, 60), block=None):
    image = Image.new("RGB", size, color)
    if block:
        for x in range(block[0], block[2]):
            for y in range(block[1], block[3]):
                image.putpixel((x, y), (0, 0, 0))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_identical_screens_are_no_change():
    shot = _png()
    assert diff_screens(shot, shot) == ScreenVerdict.NO_CHANGE


def test_changed_screen_is_detected():
    before = _png()
    after = _png(block=(10, 10, 40, 30))
    assert diff_screens(before, after) == ScreenVerdict.CHANGED


def test_tiny_change_below_threshold_is_ignored():
    before = _png()
    after = _png(block=(1, 1, 3, 3))
    assert diff_screens(before, after, threshold=0.02) == ScreenVerdict.NO_CHANGE


def test_invalid_images_are_errors():
    assert diff_screens(b"not a png", b"also not a png") == ScreenVerdict.ERROR


def test_verify_action_reports_no_change():
    shot = _png()
    result = verify_action("click", shot, shot)
    assert result["verdict"] == ScreenVerdict.NO_CHANGE
    assert result["changed"] is False


def test_verify_action_reports_change():
    result = verify_action("click", _png(), _png(block=(5, 5, 30, 30)))
    assert result["verdict"] == ScreenVerdict.CHANGED
    assert result["changed"] is True


def test_verify_action_respects_expected_no_visual_change():
    shot = _png()
    result = verify_action("wait", shot, shot, expected="no visual change expected")
    assert result["changed"] is False
    assert result["satisfied"] is True


def test_verify_action_for_scroll_allows_same_screen():
    shot = _png()
    result = verify_action("scroll", shot, shot)
    assert result["satisfied"] is True
