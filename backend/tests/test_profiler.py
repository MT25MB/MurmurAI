"""Hardware profiling and latency-optimization tests.

All detection is deterministic here: OS/commands are mocked so the suite runs
identically on CI and developer machines, and no profile is written to the real
home directory.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

import setup as app_setup
import system.profiler as profiler
from agent.brain import Brain
from agent.vision_agent import VisionAgent
from system.profiler import HardwareProfile

ENV_KEYS = [
    profiler.ENV_CHAT_MODEL,
    profiler.ENV_VISION_MODEL,
    profiler.ENV_WHISPER_MODEL,
    profiler.ENV_WHISPER_COMPUTE,
    profiler.ENV_WHISPER_DEVICE,
    profiler.ENV_MAX_SCREEN_DIM,
    profiler.ENV_KEEP_ALIVE,
]


@pytest.fixture(autouse=True)
def _isolated_profile(monkeypatch, tmp_path):
    """Never touch the real ~/.murmur-ai profile; clear profiler env vars."""
    monkeypatch.setattr(profiler, "PROFILE_PATH", tmp_path / "hardware_profile.json")
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


# ---- detection ----

@pytest.mark.parametrize("system_name,machine,vram,expected_backend", [
    ("Windows", "AMD64", 8.0, "CUDA"),
    ("Linux", "x86_64", 0.0, "CPU"),
    ("Darwin", "arm64", 0.0, "Metal"),
    ("Darwin", "x86_64", 0.0, "CPU"),
])
def test_detect_backend(monkeypatch, system_name, machine, vram, expected_backend):
    monkeypatch.setattr(profiler.platform, "system", lambda: system_name)
    monkeypatch.setattr(profiler.platform, "machine", lambda: machine)
    monkeypatch.setattr(profiler, "_total_ram_gb", lambda: 16.0)
    monkeypatch.setattr(profiler, "_nvidia_vram_gb", lambda: vram)
    p = profiler.detect_hardware()
    assert p.compute_backend == expected_backend


@pytest.mark.parametrize("ram,vram,expected_tier", [
    (32.0, 0.0, "high"),   # high RAM
    (8.0, 8.0, "high"),    # high VRAM
    (12.0, 0.0, "light"),  # mid RAM, no GPU
    (8.0, 0.0, "light"),   # light
    (6.0, 0.0, "ultra_light"),  # edge machine, CPU only
    (7.0, 3.0, "ultra_light"),  # under 4 GB VRAM and under 8 GB RAM
    (32.0, 24.0, "workstation"),  # big GPU wins even with modest RAM
])
def test_detect_tier(monkeypatch, ram, vram, expected_tier):
    monkeypatch.setattr(profiler.platform, "system", lambda: "Linux")
    monkeypatch.setattr(profiler, "_total_ram_gb", lambda: ram)
    monkeypatch.setattr(profiler, "_nvidia_vram_gb", lambda: vram)
    assert profiler.detect_hardware().tier == expected_tier


def test_detect_hardware_falls_back_without_tools(monkeypatch):
    monkeypatch.setattr(profiler, "_total_ram_gb", lambda: 0.0)
    monkeypatch.setattr(profiler, "_nvidia_vram_gb", lambda: 0.0)
    p = profiler.detect_hardware()
    assert p.tier == "light" and p.compute_backend == "CPU" and p.cpu_cores >= 1


def test_nvidia_vram_missing_tool_returns_zero(monkeypatch):
    monkeypatch.setattr(profiler.shutil, "which", lambda name: None)
    assert profiler._nvidia_vram_gb() == 0.0


def test_nvidia_vram_parses_smi(monkeypatch):
    class FakeResult:
        stdout = "8192\n4096\n"

    monkeypatch.setattr(profiler.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(profiler.subprocess, "run", lambda *a, **k: FakeResult())
    assert profiler._nvidia_vram_gb() == 8.0


# ---- tier recommendations ----

def test_high_tier_config_uses_current_models():
    cfg = profiler.recommend_config(HardwareProfile(
        total_ram_gb=32, vram_gb=8, cpu_cores=16, compute_backend="CUDA", tier="high"
    ))
    assert cfg["chat_model"] == "qwen2.5:7b"
    assert cfg["vision_model"] == "qwen2.5vl:7b"
    assert cfg["model_family"] == profiler.LEGACY_FAMILY
    assert cfg["unified_multimodal"] is False
    assert cfg["shared_model"] is None
    assert cfg["warm_models"] == ["qwen2.5:7b", "qwen2.5vl:7b"]
    assert cfg["whisper_model"] == "small.en"
    assert cfg["whisper_compute_type"] == "float16"
    assert cfg["whisper_device"] == "cuda"
    assert cfg["keep_alive"] == "30m"


def test_light_tier_config_uses_current_models():
    cfg = profiler.recommend_config(HardwareProfile(
        total_ram_gb=8, vram_gb=0, cpu_cores=4, compute_backend="CPU", tier="light"
    ))
    assert cfg["chat_model"] == "qwen2.5:3b"
    assert cfg["vision_model"] == "qwen2.5vl:3b"
    assert cfg["whisper_model"] == "tiny.en"
    assert cfg["whisper_compute_type"] == "int8"
    assert cfg["whisper_device"] == "cpu"


def test_workstation_tier_does_not_force_27b_by_default():
    cfg = profiler.recommend_config(HardwareProfile(
        total_ram_gb=64, vram_gb=24, cpu_cores=32, compute_backend="CUDA", tier="workstation"
    ))
    assert cfg["chat_model"] == "qwen2.5:7b"
    assert cfg["vision_model"] == "qwen2.5vl:7b"
    assert "qwen3.5:27b" not in cfg["required_models"]


# ---- opt-in unified multimodal tiering ----

def test_unified_tiers_share_one_warm_model(monkeypatch):
    monkeypatch.setenv(profiler.ENV_MODEL_FAMILY, "qwen3.5")
    for tier, unified in (("light", "qwen3.5:4b"), ("high", "qwen3.5:9b"), ("workstation", "qwen3.5:27b")):
        cfg = profiler.recommend_config(HardwareProfile(tier=tier))
        assert cfg["unified_multimodal"] is True
        assert cfg["chat_model"] == cfg["vision_model"] == unified
        assert cfg["warm_models"] == [unified]  # no unload/reload between voice and screen
        assert cfg["shared_model"] == unified
        assert unified in profiler.VISION_MODELS


def test_is_unified_multimodal_and_shared_model():
    assert profiler.is_unified_multimodal("qwen3.5:9b")
    assert profiler.is_unified_multimodal("QWEN3.5:4B")
    assert not profiler.is_unified_multimodal("qwen2.5vl:7b")
    assert not profiler.is_unified_multimodal("gemma4:12b")
    assert profiler.shared_multimodal_model("qwen3.5:9b", "qwen3.5:9b") == "qwen3.5:9b"
    assert profiler.shared_multimodal_model("qwen3.5:9b") == "qwen3.5:9b"
    # Explicit legacy vision override is respected, never silently replaced.
    assert profiler.shared_multimodal_model("qwen3.5:9b", "qwen2.5vl:7b") is None
    assert profiler.shared_multimodal_model("qwen2.5:7b", "qwen2.5vl:7b") is None


# ---- late-2026 checkpoint support ----

def test_new_checkpoints_are_registered_and_hardware_gated():
    expected = {
        "lfm3-vl:2b", "qwen3.5:2b", "qwen3-vl:8b", "gemma4:e4b",
        "gemma4:12b", "gemma4:26b", "qwen3.8:27b",
    }
    assert expected <= set(profiler.MODEL_CATALOG)
    assert expected <= set(profiler.VISION_MODELS)

    tiny = HardwareProfile(total_ram_gb=6, vram_gb=0, tier="ultra_light", compute_backend="CPU")
    mid = HardwareProfile(total_ram_gb=32, vram_gb=8, tier="high", compute_backend="CUDA")
    big = HardwareProfile(total_ram_gb=128, vram_gb=24, tier="workstation", compute_backend="CUDA")

    assert profiler.model_fits_hardware("lfm3-vl:2b", tiny)
    assert not profiler.model_fits_hardware("qwen3.8:27b", tiny)
    assert profiler.model_fits_hardware("gemma4:e4b", mid)
    assert profiler.model_fits_hardware("qwen3-vl:8b", mid)
    assert profiler.model_fits_hardware("qwen3.8:27b", big)
    assert profiler.model_fits_hardware("gemma4:26b", big)


def test_tier_recommendations_cover_three_hardware_classes():
    ultra = profiler.recommended_models_for_tier("ultra_light")
    assert ultra["vision"][0] == "lfm3-vl:2b"
    assert ultra["fast"][0] == "qwen3.5:0.8b"

    mid = profiler.recommended_models_for_tier("high")
    assert mid["vision"][0] == "gemma4:e4b"
    assert "qwen3-vl:8b" in mid["vision"]
    assert "qwen3.5:9b" in mid["vision"]

    high = profiler.recommended_models_for_tier("workstation")
    assert high["vision"][0] == "gemma4:12b"
    assert "gemma4:26b" in high["vision"]
    assert "qwen3.8:27b" in high["vision"]


def test_new_family_tier_configs(monkeypatch):
    monkeypatch.setenv(profiler.ENV_MODEL_FAMILY, "qwen3.8")
    ws = profiler.recommend_config(HardwareProfile(tier="workstation"))
    assert ws["chat_model"] == ws["vision_model"] == "qwen3.8:27b"
    assert ws["unified_multimodal"] is True
    assert ws["warm_models"] == ["qwen3.8:27b"]

    monkeypatch.setenv(profiler.ENV_MODEL_FAMILY, "gemma4")
    gemma = profiler.recommend_config(HardwareProfile(tier="high"))
    assert gemma["vision_model"] == "gemma4:e4b"
    assert gemma["alternate_vision_model"] == "qwen3-vl:8b"
    assert gemma["unified_multimodal"] is False

    monkeypatch.setenv(profiler.ENV_MODEL_FAMILY, "lfm3-vl")
    edge = profiler.recommend_config(HardwareProfile(tier="ultra_light"))
    assert edge["vision_model"] == "lfm3-vl:2b"
    assert edge["fast_model"] == "qwen3.5:0.8b"


def test_dynamic_resolution_support_by_family():
    for model in ("qwen3-vl:8b", "qwen3.5:9b", "qwen3.8:27b"):
        assert profiler.supports_dynamic_resolution(model)
        assert profiler.coordinate_mode(model) == "pixels"
    for model in ("qwen2.5vl:7b", "gemma4:e4b", "lfm3-vl:2b"):
        assert not profiler.supports_dynamic_resolution(model)
    assert profiler.MAX_DYNAMIC_SCREEN_DIM == 4096


def test_legacy_family_fallback_preserved(monkeypatch):
    monkeypatch.setenv(profiler.ENV_MODEL_FAMILY, "qwen2.5vl")
    high = profiler.recommend_config(HardwareProfile(tier="high"))
    assert high["chat_model"] == "qwen2.5:7b"
    assert high["vision_model"] == "qwen2.5vl:7b"
    assert high["unified_multimodal"] is False
    assert high["shared_model"] is None
    assert high["warm_models"] == ["qwen2.5:7b", "qwen2.5vl:7b"]
    assert high["required_models"] == ["qwen2.5:7b", "qwen2.5vl:7b"]

    light = profiler.recommend_config(HardwareProfile(tier="light"))
    assert light["chat_model"] == "qwen2.5:3b"
    assert light["vision_model"] == "qwen2.5vl:3b"
    assert profiler.coordinate_mode(light["vision_model"]) == "normalized_1000"


def test_metal_high_uses_int8_float16_on_cpu():
    cfg = profiler.recommend_config(HardwareProfile(
        total_ram_gb=24, vram_gb=0, cpu_cores=8, compute_backend="Metal", tier="high"
    ))
    assert cfg["whisper_compute_type"] == "int8_float16"
    assert cfg["whisper_device"] == "cpu"


# ---- persistence + application ----

def test_profile_persists_and_reloads():
    p = HardwareProfile(total_ram_gb=16, vram_gb=0, cpu_cores=8, compute_backend="CPU", tier="high")
    profiler.save_profile(p)
    loaded = profiler.load_profile()
    assert loaded is not None and loaded.total_ram_gb == 16 and loaded.tier == "high"


def test_load_profile_corrupt_returns_none(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(profiler, "PROFILE_PATH", bad)
    assert profiler.load_profile() is None


def test_configure_applies_env_and_returns_config():
    cfg = profiler.configure_from_hardware(
        HardwareProfile(total_ram_gb=8, vram_gb=0, cpu_cores=4, tier="light"),
        persist=False,
    )
    import os
    assert os.environ[profiler.ENV_CHAT_MODEL] == "qwen2.5:3b"
    assert os.environ[profiler.ENV_VISION_MODEL] == "qwen2.5vl:3b"
    assert profiler.ENV_FAST_MODEL not in os.environ
    assert os.environ[profiler.ENV_MAX_SCREEN_DIM] == "1024"
    assert cfg["chat_model"] == "qwen2.5:3b"


def test_user_env_wins_over_recommendation(monkeypatch):
    monkeypatch.setenv(profiler.ENV_CHAT_MODEL, "my-custom:9b")
    cfg = profiler.configure_from_hardware(
        HardwareProfile(tier="light"), persist=False
    )
    assert cfg["chat_model"] == "my-custom:9b"


def test_saved_override_wins_over_recommendation():
    p = HardwareProfile(tier="high", overrides={profiler.ENV_CHAT_MODEL: "override:7b"})
    cfg = profiler.configure_from_hardware(p, persist=False)
    assert cfg["chat_model"] == "override:7b"


def test_setup_recommended_setup_uses_current_models():
    rec = app_setup.recommended_setup(HardwareProfile(tier="high", compute_backend="CUDA"))
    assert rec["models"] == ["qwen2.5:7b", "qwen2.5vl:7b"]
    assert len(rec["model_labels"]) == 2
    assert rec["unified_multimodal"] is False
    assert rec["warm_models"] == ["qwen2.5:7b", "qwen2.5vl:7b"]
    assert all(item["tier"] == "upgrade" for item in rec["upgrades"])


def test_model_gating_and_upgrade_options():
    light = HardwareProfile(total_ram_gb=8, vram_gb=0, tier="light")
    high = HardwareProfile(total_ram_gb=32, vram_gb=0, tier="high")
    workstation = HardwareProfile(total_ram_gb=64, vram_gb=24, tier="workstation")

    assert profiler.model_fits_hardware("qwen3.5:4b", light) is True
    assert profiler.model_fits_hardware("qwen3.5:9b", light) is False
    assert profiler.model_fits_hardware("qwen3.5:9b", high) is True
    assert profiler.model_fits_hardware("qwen3.5:27b", high) is False
    assert profiler.model_fits_hardware("qwen3.5:27b", workstation) is True
    assert profiler.model_fits_hardware("not-a-model", workstation) is False

    options = profiler.model_options(light)
    assert any(option["name"] == "qwen2.5:3b" and option["tier"] == "current" for option in options)
    assert all(
        option["available"] and option["tier"] == "upgrade"
        for option in profiler.upgrade_options(light)
    )
    assert not any(
        option["name"] == "qwen3.5:9b" for option in profiler.upgrade_options(light)
    )
    assert "need" in next(
        option["reason"] for option in options if option["name"] == "qwen3.5:9b"
    ).lower()


def test_setup_recommended_setup_legacy_family(monkeypatch):
    monkeypatch.setenv(profiler.ENV_MODEL_FAMILY, "qwen2.5vl")
    rec = app_setup.recommended_setup(HardwareProfile(tier="light"))
    assert rec["models"] == ["qwen2.5:3b", "qwen2.5vl:3b"]
    assert rec["warm_models"] == ["qwen2.5:3b", "qwen2.5vl:3b"]
    assert rec["unified_multimodal"] is False


def test_warm_models_defaults_to_current_pair(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            calls.append(json["model"])
            return FakeResp()

    monkeypatch.setattr(app_setup.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        profiler, "load_profile", lambda: HardwareProfile(tier="high", compute_backend="CUDA")
    )
    result = asyncio.run(app_setup.warm_models())

    assert result == {"qwen2.5:7b": True, "qwen2.5vl:7b": True}
    assert calls == ["qwen2.5:7b", "qwen2.5vl:7b"]  # current pair, no upgrade forced


def test_brain_and_vision_share_unified_model(monkeypatch):
    import system.settings_tools as settings_tools

    monkeypatch.setattr(settings_tools, "load_settings", lambda: {})
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.delenv("OLLAMA_VISION_MODEL", raising=False)
    brain = Brain()
    assert brain.unified_multimodal is True
    assert brain.vision_model == "qwen3.5:9b"

    from agent.vision_agent import resolve_vision_model

    assert resolve_vision_model() == "qwen3.5:9b"


def test_explicit_legacy_vision_model_is_not_replaced(monkeypatch):
    import system.settings_tools as settings_tools

    monkeypatch.setattr(settings_tools, "load_settings", lambda: {})
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("OLLAMA_VISION_MODEL", "qwen2.5vl:7b")
    brain = Brain()
    assert brain.unified_multimodal is False
    assert brain.vision_model == "qwen2.5vl:7b"

    from agent.vision_agent import resolve_vision_model

    assert resolve_vision_model() == "qwen2.5vl:7b"


def test_warm_models_posts_keep_alive(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            calls.append((url, json))
            return FakeResp()

    monkeypatch.setattr(app_setup.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(app_setup.warm_models(["chat:7b", "vision:7b"]))

    assert result == {"chat:7b": True, "vision:7b": True}
    assert all(c[1]["keep_alive"] == "30m" for c in calls)
    assert all(c[0].endswith("/api/generate") for c in calls)


# ---- latency helpers ----

def test_downscale_preserves_aspect_ratio():
    img = Image.new("RGB", (4000, 2000), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out, w, h = profiler.downscale_png(buf.getvalue(), 1000)
    assert (w, h) == (1000, 500)
    out_img = Image.open(io.BytesIO(out))
    assert out_img.size == (1000, 500)


def test_downscale_noop_when_small():
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original = buf.getvalue()
    out, w, h = profiler.downscale_png(original, 1000)
    assert out == original and (w, h) == (200, 100)


def test_prewarm_audio_nonfatal(monkeypatch):
    class StubSpeaker:
        def __init__(self): self.called = False
        def _try_kokoro(self):
            self.called = True
            return True

    s = StubSpeaker()
    result = profiler.prewarm_audio(s)
    assert isinstance(result, dict) and s.called


def test_prewarm_audio_survives_missing_deps(monkeypatch):
    import sys

    # A None entry in sys.modules makes import_module raise ImportError.
    monkeypatch.setitem(sys.modules, "kokoro", None)
    monkeypatch.setitem(sys.modules, "silero_vad", None)
    result = profiler.prewarm_audio(None)
    assert result == {"kokoro": False, "silero_vad": False}


# ---- keep_alive on chat paths ----

def test_brain_chat_sends_keep_alive():
    captured = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "ok"}}

    brain = Brain()
    brain._client.post = lambda url, json=None: (captured.update(json), Resp())[1]
    brain.think_and_act("hi")
    assert captured["keep_alive"] == "30m"


def test_vision_ask_vlm_sends_keep_alive():
    captured = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "{}"}}

    agent = object.__new__(VisionAgent)
    agent.history = []
    agent.model = "vision:7b"
    agent._client = type("C", (), {"post": lambda self, url, json=None: (captured.update(json), Resp())[1]})()

    agent._ask_vlm("goal", "b64", 1920, 1080, "", {})
    assert captured["keep_alive"] == "30m"
