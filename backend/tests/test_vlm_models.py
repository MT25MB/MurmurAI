"""Multiple local VLM families and their coordinate conventions."""

from __future__ import annotations

from system.profiler import (
    VISION_MODELS,
    coordinate_mode,
    normalize_vlm_coords,
    recommend_config,
    detect_hardware,
    HardwareProfile,
)


def test_supported_vlm_families():
    for model in ("qwen3.5:9b", "gemma4:12b", "qwen2.5-vl:7b", "qwen2.5-vl:3b"):
        assert model in VISION_MODELS


def test_coordinate_modes_by_family():
    assert coordinate_mode("qwen2.5-vl:7b") == "normalized_1000"
    assert coordinate_mode("qwen3.5:9b") == "pixels"
    assert coordinate_mode("gemma4:12b") == "pixels"
    assert coordinate_mode("unknown:model") == "normalized_1000"


def test_normalized_coords_stay_normalized():
    x, y = normalize_vlm_coords([500, 400], 1920, 1080, "qwen2.5-vl:7b")
    assert (x, y) == (500, 400)


def test_pixel_coords_are_normalized():
    x, y = normalize_vlm_coords([960, 540], 1920, 1080, "gemma4:12b")
    assert x == 500 and y == 500


def test_pixel_coords_from_fractional_string():
    x, y = normalize_vlm_coords(["0.5", "0.25"], 1000, 800, "qwen3.5:9b")
    assert x == 500 and y == 250


def test_hardware_tier_recommends_supported_vision_model():
    profile = HardwareProfile(total_ram_gb=32, vram_gb=12, cpu_cores=8, tier="high")
    cfg = recommend_config(profile)
    assert cfg["vision_model"] in VISION_MODELS
