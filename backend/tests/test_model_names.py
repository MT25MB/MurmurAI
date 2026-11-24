"""Ollama model names must use the real library tags."""

from __future__ import annotations

import json

from agent.model_names import normalize_model
from setup import REQUIRED_MODELS


def test_legacy_hyphenated_vision_model_is_normalized():
    legacy = "qwen2.5" + "-vl"
    assert normalize_model(f"{legacy}:7b") == "qwen2.5vl:7b"
    assert normalize_model(f"{legacy}:3b") == "qwen2.5vl:3b"
    assert normalize_model("qwen2.5vl:7b") == "qwen2.5vl:7b"
    assert normalize_model("") == ""


def test_required_models_use_ollama_library_names():
    assert "qwen2.5vl:7b" in REQUIRED_MODELS
    legacy = "qwen2.5" + "-vl"
    assert not any(name.startswith(legacy) for name in REQUIRED_MODELS)


def test_saved_vision_model_setting_is_normalized(monkeypatch, tmp_path):
    import system.settings_tools as st

    config = tmp_path / "config.json"
    legacy = "qwen2.5" + "-vl:7b"
    config.write_text(json.dumps({"vision_model": legacy}), encoding="utf-8")
    monkeypatch.setattr(st, "CONFIG_PATH", config)
    monkeypatch.setattr(st, "_CACHE", None)

    assert st.load_settings()["vision_model"] == "qwen2.5vl:7b"
