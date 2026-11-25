"""Static guards for the Tauri shell hardening audit.

These are cheap source/config checks: they keep command handlers async and the
IPC capability narrowly scoped without needing a full desktop build in CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAURI = ROOT / "src-tauri"
SOURCE = TAURI / "src"

EXPECTED_PERMISSIONS = {
    "core:event:allow-listen",
    "core:event:allow-unlisten",
    "core:window:allow-start-dragging",
    "core:window:allow-minimize",
    "core:window:allow-close",
    "core:window:allow-set-size",
    "core:window:allow-set-resizable",
    "core:window:allow-center",
    "core:window:allow-set-position",
    "core:window:allow-set-focus",
}


def test_every_tauri_command_is_async():
    pattern = re.compile(
        r"#\[tauri::command\]\s*(?:pub\s+)?(async\s+)?fn\s+([A-Za-z0-9_]+)"
    )
    found: list[str] = []
    for source in SOURCE.glob("*.rs"):
        text = source.read_text(encoding="utf-8")
        for is_async, name in pattern.findall(text):
            assert is_async.strip() == "async", (
                f"{source.name}: command {name} does I/O and must be async "
                "so the UI and tray never stall"
            )
            found.append(name)
    # Guard against the regex silently matching nothing.
    assert {"check_for_updates", "install_update", "check_os_permissions", "restore_focus"} <= set(found)


def test_capabilities_are_scoped_to_the_main_window_only():
    capability_files = sorted((TAURI / "capabilities").glob("*.json"))
    assert capability_files
    for path in capability_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data.get("windows", [])) <= {"main", "cursor"}, (
            f"{path.name} grants IPC to an unexpected window"
        )
        assert data.get("platforms") == ["windows", "macOS", "linux"], (
            f"{path.name} must declare explicit desktop platform guards"
        )
        permissions = set(data.get("permissions", []))
        assert "core:default" not in permissions, "core:default grants far more than the HUD needs"
        assert not any("*" in permission for permission in permissions)
        assert permissions == EXPECTED_PERMISSIONS, (
            f"{path.name} permissions drifted: {permissions ^ EXPECTED_PERMISSIONS}"
        )


def test_tauri_config_has_one_hud_window_and_signed_updates():
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    windows = config["app"]["windows"]
    labels = [w["label"] for w in windows]
    assert "main" in labels
    # The second window is a click-through action marker, not a second HUD.
    assert "cursor" in labels
    cursor = next(w for w in windows if w["label"] == "cursor")
    assert cursor.get("ignoreCursorEvents") is True
    assert cursor.get("transparent") is True

    updater = config["plugins"]["updater"]
    assert updater["pubkey"], "signed updater public key is required"
    assert updater["endpoints"]
    assert all(url.startswith("https://") for url in updater["endpoints"])
