"""Uninstall data choice: kept by default, cleared only when explicitly chosen."""

from __future__ import annotations

import json

from system import settings_tools
from system.uninstall import clear_data_requested, collect_data_paths, run_cleanup


def _root(tmp_path):
    root = tmp_path / ".murmur-ai"
    (root / "logs").mkdir(parents=True)
    (root / "models").mkdir(parents=True)
    for name in ("memories.json", "config.json", "setup_complete.json", "models/big.bin"):
        (root / name).write_text("x", encoding="utf-8")
    (root / "logs" / "session.log").write_text("x", encoding="utf-8")
    return root


def test_default_is_to_keep_data(tmp_path):
    root = _root(tmp_path)
    assert clear_data_requested(root) is False
    result = run_cleanup(home=tmp_path, apply=True)
    assert result["choice"] is False
    assert result["removed"] == []
    assert (root / "memories.json").exists()


def test_choice_is_persisted_in_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_tools, "CONFIG_PATH", tmp_path / "config.json")
    assert settings_tools.load_settings()["clear_data_on_uninstall"] is False
    saved = settings_tools.update_settings({"clear_data_on_uninstall": True})
    assert saved["clear_data_on_uninstall"] is True
    assert json.loads((tmp_path / "config.json").read_text())["clear_data_on_uninstall"] is True


def test_candidates_include_data_but_not_model_weights(tmp_path):
    root = _root(tmp_path)
    names = {p.relative_to(root).as_posix() for p in collect_data_paths(root)}
    assert "memories.json" in names
    assert "logs" in names
    assert "config.json" in names
    assert "models/big.bin" not in names
    assert all(not n.startswith("models/") for n in names)


def test_dry_run_reports_but_deletes_nothing(tmp_path):
    root = _root(tmp_path)
    (root / "config.json").write_text(
        json.dumps({"clear_data_on_uninstall": True}), encoding="utf-8"
    )

    result = run_cleanup(home=tmp_path, apply=False)

    assert result["choice"] is True
    assert result["applied"] is False
    assert result["candidates"]
    assert (root / "memories.json").exists()


def test_apply_with_choice_removes_data_but_keeps_models(tmp_path):
    root = _root(tmp_path)
    (root / "config.json").write_text(
        json.dumps({"clear_data_on_uninstall": True}), encoding="utf-8"
    )

    result = run_cleanup(home=tmp_path, apply=True)

    assert result["applied"] is True
    assert any(p.endswith("memories.json") for p in result["removed"])
    assert not (root / "memories.json").exists()
    assert not (root / "logs").exists()
    assert (root / "models" / "big.bin").exists()


def test_symlink_outside_data_dir_is_skipped(tmp_path):
    root = _root(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    link = root / "memories.json"
    link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows privileges
        return
    assert link not in collect_data_paths(root)
    assert outside.read_text() == "keep"


def test_voice_commands_set_and_query_uninstall_choice(monkeypatch):
    monkeypatch.setattr(settings_tools, "CONFIG_PATH", tmp_path_config())
    assert "keep" in settings_tools.handle_voice_command(
        "clear my data when you are uninstalled"
    ).lower() or "clear" in settings_tools.handle_voice_command(
        "clear my data when you are uninstalled"
    ).lower()
    assert settings_tools.load_settings()["clear_data_on_uninstall"] is True
    settings_tools.handle_voice_command("keep my data when you are uninstalled")
    assert settings_tools.load_settings()["clear_data_on_uninstall"] is False
    answer = settings_tools.handle_voice_command(
        "what happens to my data when you are uninstalled"
    )
    assert "keep" in answer.lower() or "kept" in answer.lower()


def tmp_path_config():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "config.json"
