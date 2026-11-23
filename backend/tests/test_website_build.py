"""Guard the website build that powers the download button.

The CI deploy installs only `website/` dependencies, so the static build must
not typecheck root-owned Vitest test files. A regression here silently freezes
the deployed site at an old version.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBSITE = ROOT / "website"


def test_website_build_does_not_need_the_root_test_runner():
    tsconfig = json.loads((WEBSITE / "tsconfig.json").read_text(encoding="utf-8"))
    excluded = tsconfig.get("exclude", [])
    assert any("*.test.ts" in pattern for pattern in excluded)
    assert any("*.test.tsx" in pattern for pattern in excluded)

    package = json.loads((WEBSITE / "package.json").read_text(encoding="utf-8"))
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    assert "vitest" not in dependencies  # tests run from the repository root


def test_download_button_resolves_the_highest_version_not_the_date_latest():
    config = (WEBSITE / "src" / "config.ts").read_text(encoding="utf-8")
    assert "RELEASES_API" in config
    assert "releases?per_page=100" in config
