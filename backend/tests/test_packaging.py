"""Package manifest templates and release checksum sync tests."""

from __future__ import annotations

import configparser
import hashlib
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from system.packaging_sync import (  # noqa: E402
    collect_artifacts,
    sha256_file,
    sync_manifests,
    token_map,
    write_sha256sums,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"


@pytest.fixture
def assets(tmp_path):
    directory = tmp_path / "assets"
    directory.mkdir()
    files = {
        "Murmur.AI_1.2.3_x64-setup.exe": b"exe",
        "Murmur.AI_1.2.3_x64_en-US.msi": b"msi",
        "Murmur.AI_1.2.3_aarch64.dmg": b"dmg",
        "Murmur.AI_1.2.3_amd64.AppImage": b"appimage",
        "Murmur.AI_1.2.3_amd64.deb": b"deb",
        "Murmur.AI_1.2.3_x64_en-US.msi.sig": b"sig",
        "latest.json": b"{}",
    }
    for name, content in files.items():
        (directory / name).write_bytes(content)
    return directory


def test_sha256_file(assets):
    path = assets / "Murmur.AI_1.2.3_aarch64.dmg"
    assert sha256_file(path) == hashlib.sha256(b"dmg").hexdigest()


def test_collect_artifacts_ignores_signatures_and_metadata(assets):
    artifacts = collect_artifacts(assets, "1.2.3")
    assert set(artifacts) == {"exe", "msi", "dmg", "appimage", "deb"}
    assert artifacts["msi"].url.endswith("/Murmur.AI_1.2.3_x64_en-US.msi")
    assert artifacts["msi"].sha256 == hashlib.sha256(b"msi").hexdigest()


def test_token_map_generates_url_and_hash_tokens(assets):
    artifacts = collect_artifacts(assets, "1.2.3")
    tokens = token_map("1.2.3", "2026-11-21", artifacts)
    assert tokens["{{VERSION}}"] == "1.2.3" and tokens["{{DATE}}"] == "2026-11-21"
    assert tokens["{{MSI_SHA256}}"] == hashlib.sha256(b"msi").hexdigest().upper()
    assert "1.2.3" in tokens["{{DMG_URL}}"]


def test_sync_manifests_replaces_all_placeholders(assets, tmp_path):
    # Self-contained templates with placeholders; repo templates may already be
    # synced by a release, which would leave nothing for this test to replace.
    target = tmp_path / "packaging"
    templates = {
        "winget/MurmurAI.yaml": (
            'PackageVersion: "{{VERSION}}"\nInstallerUrl: "{{MSI_URL}}"\n'
            'InstallerSha256: "{{MSI_SHA256}}"\n'
        ),
        "homebrew/murmur-ai.rb": (
            'version "{{VERSION}}"\nsha256 "{{DMG_SHA256}}"\nurl "{{DMG_URL}}"\n'
        ),
        "linux/murmur-ai.desktop": "Version={{VERSION}}\n",
        "linux/com.murmurai.MurmurAI.metainfo.xml": (
            '<release version="{{VERSION}}" date="{{DATE}}"/>\n'
        ),
    }
    for relative, content in templates.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    artifacts = collect_artifacts(assets, "1.2.3")
    changed = sync_manifests(target, "1.2.3", artifacts, "2026-11-21")
    assert len(changed) == 4
    for path in target.rglob("*"):
        if path.is_file():
            assert "{{" not in path.read_text(encoding="utf-8"), path
    assert 'PackageVersion: "1.2.3"' in (target / "winget" / "MurmurAI.yaml").read_text(encoding="utf-8")


def test_write_sha256sums(assets, tmp_path):
    artifacts = collect_artifacts(assets, "1.2.3")
    sums = write_sha256sums(artifacts, tmp_path / "SHA256SUMS.txt")
    lines = sums.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    assert all("  " in line for line in lines)
    assert any(line.endswith("Murmur.AI_1.2.3_aarch64.dmg") for line in lines)


def test_manifest_templates_are_valid():
    winget = yaml.safe_load((PACKAGING / "winget" / "MurmurAI.yaml").read_text(encoding="utf-8"))
    assert winget["PackageIdentifier"] == "MT25MB.MurmurAI"
    assert winget["Installers"][0]["InstallerType"] == "msi"

    cask = (PACKAGING / "homebrew" / "murmur-ai.rb").read_text(encoding="utf-8")
    assert 'cask "murmur-ai"' in cask and "sha256" in cask

    desktop = configparser.ConfigParser()
    desktop.read(PACKAGING / "linux" / "murmur-ai.desktop")
    assert "Accessibility" in desktop["Desktop Entry"]["Categories"]
    assert "Utility" in desktop["Desktop Entry"]["Categories"]

    meta = ET.parse(PACKAGING / "linux" / "com.murmurai.MurmurAI.metainfo.xml")
    categories = {node.text for node in meta.iter("category")}
    assert {"Accessibility", "Utility"} <= categories


def test_release_workflow_syncs_packages():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    assert "package-sync" in workflow["jobs"]
    assert workflow["jobs"]["package-sync"]["needs"] == "build"
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "SHA256SUMS.txt" in text
    assert "sync_packaging.py" in text
    assert "packaging/templates" in text, "release must restore placeholder templates"


def test_manifest_templates_keep_placeholders():
    templates = PACKAGING / "templates"
    for path in templates.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "{{VERSION}}" in text, path
    assert templates.exists()


def test_readme_documents_one_line_installs():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "winget install" in text
    assert "brew install --cask" in text
    assert "sha256sum -c SHA256SUMS.txt" in text
