"""Fast native accessibility-tree enumeration with graceful fallback."""

from __future__ import annotations

from tools import a11y_tree
from tools.a11y_tree import InteractiveElement, a11y_table, capture_tree, find_control


def _element(name, role="button", x=10, y=20, focused=False, enabled=True):
    return InteractiveElement(
        name=name,
        role=role,
        center_x=x,
        center_y=y,
        box=(0, 0, 100, 100),
        focused=focused,
        enabled=enabled,
        source="test",
    )


def test_capture_uses_injected_provider(monkeypatch):
    elements = [_element("Save", focused=True)]
    monkeypatch.setattr(a11y_tree, "_native_elements", lambda: elements)
    result = capture_tree(1000, 800, provider="test")
    assert result.available is True
    assert list(result.elements) == elements
    assert result.backend == "test"
    assert result.elapsed_ms >= 0


def test_capture_falls_back_gracefully(monkeypatch):
    def broken():
        raise OSError("no accessibility API")

    monkeypatch.setattr(a11y_tree, "_native_elements", broken)
    result = capture_tree(1000, 800, provider="test")
    assert result.available is False
    assert result.elements == ()


def test_table_is_bounded_and_token_efficient():
    elements = [_element(f"Control number {i}") for i in range(50)]
    table = a11y_table(elements, limit=10, name_chars=20)
    lines = table.splitlines()
    assert len(lines) == 10
    assert "[1]" in table and "Control number 0" in table
    assert all(len(line) < 80 for line in lines)


def test_table_marks_focused_and_disabled():
    elements = [_element("Save", focused=True), _element("Delete", enabled=False)]
    table = a11y_table(elements)
    assert "focused" in table.lower()
    assert "disabled" in table.lower()


def test_find_control_matches_name_case_insensitively():
    elements = [_element("Save File"), _element("Close")]
    assert find_control(elements, "save file") is elements[0]
    assert find_control(elements, "missing") is None


def test_find_control_skips_disabled():
    elements = [_element("Delete", enabled=False)]
    assert find_control(elements, "delete") is None


def test_vision_prompt_gets_a11y_context(monkeypatch):
    from agent import vision_agent

    monkeypatch.setattr(
        a11y_tree, "capture_tree",
        lambda w, h: a11y_tree.AccessibilityResult((_element("Save"),), "test", 1.0, True),
    )
    context = vision_agent.a11y_context(1000, 800)
    assert "Native accessibility controls" in context
    assert "Save" in context


def test_a11y_tool_resolves_named_control(monkeypatch):
    from tools.os_tools import dispatch_tool

    monkeypatch.setattr(
        a11y_tree, "capture_tree",
        lambda: a11y_tree.AccessibilityResult((_element("Save File"),), "test", 1.0, True),
    )
    result = dispatch_tool("list_a11y_controls", {"name_hint": "save file"}, None)
    assert "Save File" in result
    assert "click" in result.lower()


def test_a11y_tool_reports_when_tree_unavailable(monkeypatch):
    from tools.os_tools import dispatch_tool

    monkeypatch.setattr(
        a11y_tree, "capture_tree",
        lambda: a11y_tree.AccessibilityResult((), "none", 1.0, False),
    )
    result = dispatch_tool("list_a11y_controls", {}, None)
    assert "describe_screen" in result


def test_vision_prompt_has_no_a11y_context_when_unavailable(monkeypatch):
    from agent import vision_agent

    monkeypatch.setattr(
        a11y_tree, "capture_tree",
        lambda w, h: a11y_tree.AccessibilityResult((), "none", 1.0, False),
    )
    assert vision_agent.a11y_context(1000, 800) == ""
