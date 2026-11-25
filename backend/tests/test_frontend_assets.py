"""Static guards for frontend assets that cannot be exercised in jsdom."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "src" / "index.css"


def test_working_bar_still_animates_with_reduced_motion():
    css = CSS.read_text(encoding="utf-8")
    assert "*:not(.progress-indeterminate)" in css, (
        "the global reduced-motion override must not freeze the working bar"
    )
    assert "animation-iteration-count: infinite" in css
