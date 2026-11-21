"""Clipboard, recent-file and deictic context resolution tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import agent.brain as brain
import main
import tools.context_tools as ct
import tools.os_tools as os_tools
from agent.state import SessionState


@pytest.fixture(autouse=True)
def _isolated_context(monkeypatch, tmp_path):
    ct._GLOBAL_CONTEXT.clear()
    monkeypatch.setattr(ct, "DIRECTORY_PRESETS", {
        "downloads": tmp_path / "downloads",
        "desktop": tmp_path / "desktop",
        "documents": tmp_path / "documents",
    })
    for path in ct.DIRECTORY_PRESETS.values():
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ct, "_speak", lambda text: None)
    yield
    ct._GLOBAL_CONTEXT.clear()


# ---- clipboard ----

def test_read_clipboard_stores_context(monkeypatch):
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "  my latest note  ")
    assert ct.read_clipboard() == "my latest note"
    assert ct._GLOBAL_CONTEXT["clipboard"] == "my latest note"


def test_read_clipboard_empty_is_clear(monkeypatch):
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "")
    assert "empty or unavailable" in ct.read_clipboard().lower()


def test_write_clipboard_success(monkeypatch):
    written = []
    monkeypatch.setattr(ct, "_clipboard_write", lambda text: written.append(text) or True)
    result = ct.write_clipboard("answer")
    assert written == ["answer"]
    assert "copied to clipboard" in result.lower()
    assert ct._GLOBAL_CONTEXT["clipboard"] == "answer"


def test_write_clipboard_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(ct, "_clipboard_write", lambda text: False)
    assert "couldn't access" in ct.write_clipboard("x").lower()


# ---- recent files ----

@pytest.fixture
def sample_files():
    root = ct.DIRECTORY_PRESETS["downloads"]
    now = time.time()
    for name, age, size in (
        ("report.pdf", 60, 1_500_000),
        ("screenshot.png", 300, 240_000),
        ("notes.txt", 900, 1_200),
    ):
        path = root / name
        path.write_bytes(b"x" * min(size, 100))
        import os

        os.utime(path, (now - age, now - age))
    return root


def test_list_recent_files_sorted_with_metadata(sample_files):
    files = ct.list_recent_files("downloads", 3)
    assert [f.name for f in files] == ["report.pdf", "screenshot.png", "notes.txt"]
    assert files[0].kind == "PDF" and files[1].kind == "PNG"
    assert files[0].size_bytes == 100


def test_inspect_recent_files_speaks_summary(sample_files, monkeypatch):
    spoken = []
    monkeypatch.setattr(ct, "_speak", lambda text: spoken.append(text))
    summary = ct.inspect_recent_files("downloads", 2)
    assert "report.pdf" in summary and "PDF" in summary
    assert "screenshot.png" in summary
    assert spoken and spoken[0] == summary
    assert ct._GLOBAL_CONTEXT["last_file"] == "report.pdf"


def test_find_recent_file_by_extension(sample_files):
    assert ct.find_recent_file("the pdf i just downloaded").name == "report.pdf"
    assert ct.find_recent_file("latest screenshot").name == "screenshot.png"


def test_inspect_empty_directory_is_clear():
    assert "didn't find any files" in ct.inspect_recent_files("documents").lower()


# ---- context resolution ----

def test_record_and_resolve_last_file():
    session = SessionState()
    ct.record_context("open the quarterly-report.pdf please", session)
    resolved = ct.resolve_reference("open it", session)
    assert resolved and "quarterly-report.pdf" in resolved
    assert session.recall("last_app") is None


def test_record_app_reference():
    session = SessionState()
    ct.record_context("Switch to Blender", session)
    assert session.recall("last_app") == "blender"


def test_resolve_copied_content(monkeypatch):
    session = SessionState()
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "meeting notes text")
    resolved = ct.resolve_reference("summarize what's copied", session)
    assert resolved == "meeting notes text"


def test_unrelated_text_has_no_context():
    assert ct.resolve_reference("what time is it") is None


# ---- voice routing ----

def test_voice_what_did_i_copy(monkeypatch, sample_files):
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "Drafts/intro.md")
    reply = ct.handle_context_phrase("What did I just copy?")
    assert "Drafts/intro.md" in reply


def test_voice_summarize_clipboard(monkeypatch):
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "one two three four")
    reply = ct.handle_context_phrase("Summarize my clipboard")
    assert "4 words" in reply and "one two three four" in reply


def test_voice_copy_last_result():
    session = SessionState()
    session.add_turn("assistant", "The answer is 42.")
    written = []
    import tools.context_tools as module

    original = module._clipboard_write
    module._clipboard_write = lambda text: written.append(text) or True
    try:
        reply = ct.handle_context_phrase("Copy that result to my clipboard", session)
    finally:
        module._clipboard_write = original
    assert written == ["The answer is 42."]
    assert "copied" in reply.lower()


def test_voice_recent_files_phrase(sample_files):
    reply = ct.handle_context_phrase("What did I just download?")
    assert "report.pdf" in reply


# ---- registration / routing ----

def test_context_tools_registered():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert {"read_clipboard", "write_clipboard", "inspect_recent_files"} <= set(names)


def test_dispatch_context_tools(monkeypatch):
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "hello")
    monkeypatch.setattr(ct, "_clipboard_write", lambda text: True)
    assert os_tools.dispatch_tool("read_clipboard", {}, None) == "hello"
    assert "copied" in os_tools.dispatch_tool("write_clipboard", {"text": "x"}, None).lower()
    assert "any files" in os_tools.dispatch_tool(
        "inspect_recent_files", {"directory": "documents", "limit": 2}, None
    ).lower()


@pytest.mark.asyncio
async def test_context_phrase_fast_path(monkeypatch):
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "copied text")
    sent = []

    async def send(message):
        sent.append(message)

    assert await main._try_context_phrase(SessionState(), send, "What's on my clipboard?") is True
    assert any(m.type == "info" for m in sent)
    assert await main._try_context_phrase(SessionState(), send, "What time is it?") is False


def test_reference_augmentation(monkeypatch):
    session = SessionState()
    ct.record_context("I downloaded report.pdf", session)
    monkeypatch.setattr(ct, "_clipboard_read", lambda: "")
    prompt = main._augment_with_context("Open it", session)
    assert "report.pdf" in prompt and "Relevant context" in prompt
    assert main._augment_with_context("Hello", session) == "Hello"
