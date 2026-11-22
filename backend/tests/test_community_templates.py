"""GitHub issue/PR templates are valid and contain the required guidance."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"


@pytest.mark.parametrize("name", [
    "bug_report.yml", "accessibility_feedback.yml", "shortcut_profile_request.yml", "config.yml"
])
def test_issue_forms_are_valid_yaml(name):
    data = yaml.safe_load((TEMPLATES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    if name != "config.yml":
        assert data["name"] and data["description"] and data["body"]
        assert all("id" in item or item.get("type") == "markdown" for item in data["body"])


def test_bug_report_asks_for_diagnostics_zip():
    text = (TEMPLATES / "bug_report.yml").read_text(encoding="utf-8").lower()
    assert "export diagnostics" in text
    assert "attach" in text and ".zip" in text


def test_pr_template_exists_with_checks():
    text = (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    assert "## What changed" in text
    assert "verify-all" in text
    assert "Accessibility" in text
