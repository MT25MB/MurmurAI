"""Voice dictation typing and spoken text-editing helpers.

Tests exercise the public tool functions. Keyboard and clipboard side effects
are replaced at the module boundary so no real window is touched.
"""

from __future__ import annotations

import pytest

import tools.text_edit_tools as tet


class FakeKeyboard:
    def __init__(self):
        self.written: list[str] = []
        self.hotkeys: list[tuple[str, ...]] = []
        self.presses: list[tuple[str, int]] = []

    def write(self, text, interval=0.0):
        self.written.append(text)

    def hotkey(self, *keys):
        self.hotkeys.append(tuple(keys))

    def press(self, key, presses=1):
        self.presses.append((key, presses))


@pytest.fixture
def keyboard(monkeypatch):
    fake = FakeKeyboard()
    monkeypatch.setattr(tet, "_keyboard", lambda: fake)
    return fake


def test_type_text_writes_short_phrases_into_focused_field(keyboard):
    result = tet.type_text("hello world")

    assert keyboard.written == ["hello world"]
    assert keyboard.hotkeys == []
    assert "hello world" in result


def test_long_passages_paste_from_clipboard_and_restore_the_user_clipboard(
    keyboard, monkeypatch
):
    clipboard = {"value": "my original clipboard"}
    writes: list[str] = []
    clipboard_reads: list[bool] = []

    monkeypatch.setattr(tet, "_read_clipboard", lambda: clipboard_reads.append(True) or clipboard["value"])

    def write(value):
        writes.append(value)
        clipboard["value"] = value
        return True

    monkeypatch.setattr(tet, "_write_clipboard", write)
    passage = "A rather long dictated sentence. " * 12

    result = tet.type_text(passage)

    assert keyboard.written == []
    assert keyboard.hotkeys == [("ctrl", "v")]
    assert writes == [passage, "my original clipboard"]
    assert clipboard["value"] == "my original clipboard"
    assert "pasted" in result.lower()


def test_non_ascii_text_uses_clipboard_so_unicode_survives(keyboard, monkeypatch):
    writes: list[str] = []
    clipboard = {"value": "keep me"}
    monkeypatch.setattr(tet, "_read_clipboard", lambda: clipboard["value"])
    monkeypatch.setattr(
        tet,
        "_write_clipboard",
        lambda value: writes.append(value) or clipboard.update(value=value) or True,
    )

    tet.type_text("café 你好")

    assert keyboard.written == []
    assert keyboard.hotkeys == [("ctrl", "v")]
    assert writes == ["café 你好", "keep me"]


def test_missing_pyautogui_reports_an_actionable_error(monkeypatch):
    def unavailable():
        raise RuntimeError("Text editing needs pyautogui. Install it with `pip install pyautogui`.")

    monkeypatch.setattr(tet, "_keyboard", unavailable)

    with pytest.raises(RuntimeError, match="pyautogui"):
        tet.type_text("hello")
    assert "pyautogui" in tet.handle_text_edit_phrase("Select all")


def test_selection_actions_use_standard_keyboard_shortcuts(keyboard):
    tet.select_all()
    tet.copy_selection()
    tet.paste_here()
    tet.delete_word()

    modifier = "command" if tet.platform.system() == "Darwin" else "ctrl"
    assert keyboard.hotkeys == [
        (modifier, "a"),
        (modifier, "c"),
        (modifier, "v"),
        (modifier, "backspace"),
    ]


def test_scratch_that_erases_the_typed_characters(keyboard):
    tet.erase_last_chars(11)

    assert keyboard.presses == [("backspace", 11)]


def test_read_back_speaks_the_last_dictated_buffer(monkeypatch):
    spoken: list[str] = []
    monkeypatch.setattr(tet, "_speak", lambda text: spoken.append(text))

    result = tet.read_back_last_dictation("hello world")

    assert spoken == ["You typed: hello world"]
    assert "hello world" in result


def test_voice_phrases_dispatch_to_the_right_action(keyboard, monkeypatch):
    spoken: list[str] = []
    monkeypatch.setattr(tet, "_speak", lambda text: spoken.append(text))

    assert "select" in tet.handle_text_edit_phrase("Select all").lower()
    assert "copied" in tet.handle_text_edit_phrase("Copy selection").lower()
    assert "paste" in tet.handle_text_edit_phrase("Paste here").lower()
    assert "deleted" in tet.handle_text_edit_phrase("Delete word").lower()
    assert "hello" in tet.handle_text_edit_phrase(
        "Read back what you just typed", buffer="hello"
    ).lower()
    assert tet.handle_text_edit_phrase("What time is it?") is None

    assert len(keyboard.hotkeys) == 4


def test_text_edit_tools_are_discoverable_by_the_brain():
    import agent.brain as brain

    names = {tool["function"]["name"] for tool in brain.ALL_TOOLS}
    assert {
        "type_text",
        "select_all",
        "copy_selection",
        "paste_here",
        "delete_word",
        "read_back_last_dictation",
    } <= names


def test_brain_tool_dispatch_routes_to_text_edit_helpers(monkeypatch):
    from tools.os_tools import dispatch_tool
    from tools.safety import SafetyGate

    seen: list[str] = []
    monkeypatch.setattr(tet, "select_all", lambda: seen.append("select") or "Selected.")

    assert dispatch_tool("select_all", {}, SafetyGate()) == "Selected."
    assert seen == ["select"]
