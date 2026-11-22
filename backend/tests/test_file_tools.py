"""Local file search, spoken document reading and safe batch tools."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import agent.brain as brain
import tools.file_tools as ft
import tools.os_tools as os_tools


class FakeBus:
    def __init__(self, approved: bool = True):
        self.approved = approved
        self.calls: list[tuple[str, str]] = []

    def request_confirmation(self, description, command, timeout=180):
        self.calls.append((description, command))
        return self.approved


def make_pdf(text: str) -> bytes:
    """Build a tiny valid PDF containing one text line (no extra deps)."""
    stream = (
        b"BT /F1 16 Tf 72 700 Td (" + text.encode("latin-1", "replace") + b") Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return out


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(ft, "_speak", lambda text: None)
    monkeypatch.setattr(ft, "LOCATION_PRESETS", {
        "home": tmp_path,
        "downloads": tmp_path / "downloads",
        "desktop": tmp_path / "desktop",
        "documents": tmp_path / "documents",
    })
    for path in ft.LOCATION_PRESETS.values():
        path.mkdir(parents=True, exist_ok=True)
    yield


# ---- search ----

def test_find_files_scandir_with_ignore_list(monkeypatch, tmp_path):
    monkeypatch.setattr(ft, "_native_search", lambda *a, **k: [])
    root = ft.LOCATION_PRESETS["downloads"]
    (root / "report-2026.pdf").write_text("x", encoding="utf-8")
    (root / "notes.md").write_text("x", encoding="utf-8")
    ignore = root / "node_modules"
    ignore.mkdir()
    (ignore / "report-secret.pdf").write_text("x", encoding="utf-8")
    older = time.time() - 10 * 86400
    os.utime(root / "notes.md", (older, older))

    summary = ft.find_files("report", "downloads", limit=5)
    assert "report-2026.pdf" in summary
    assert "report-secret.pdf" not in summary
    assert "modified" in summary


def test_find_files_extension_filter(monkeypatch):
    monkeypatch.setattr(ft, "_native_search", lambda *a, **k: [])
    root = ft.LOCATION_PRESETS["downloads"]
    (root / "a.png").write_text("x", encoding="utf-8")
    (root / "b.txt").write_text("x", encoding="utf-8")
    summary = ft.find_files("", "downloads", extension="png")
    assert "a.png" in summary and "b.txt" not in summary


def test_find_files_native_results(monkeypatch, tmp_path):
    path = tmp_path / "mdfind-hit.docx"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        ft, "_native_search",
        lambda root, query, ext, limit: [ft.FoundFile(path, time.time())],
    )
    assert "mdfind-hit.docx" in ft.find_files("mdfind", "home")


def test_find_files_missing_location_messages():
    assert "couldn't find the folder" in ft.find_files("x", "/definitely/not/here").lower()


# ---- document reading ----

def test_read_text_document(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Project kickoff notes. Next steps are clear.", encoding="utf-8")
    assert "Project kickoff notes" in ft.read_document_aloud(str(path))


def test_read_markdown_strips_syntax(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text(
        "# Setup Guide\n\nVisit [the site](https://example.com) and run `code`.\n\n"
        "## Safety\n\nAlways confirm destructive actions.",
        encoding="utf-8",
    )
    text = ft.read_document_aloud(str(path))
    assert "Setup Guide" in text and "the site" in text
    assert "`" not in text and "](" not in text


def test_read_section_by_query(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# Intro\nWelcome here.\n\n## Safety\nAlways confirm actions.", encoding="utf-8")
    section = ft.read_document_aloud(str(path), "safety")
    assert "Safety" in section and "confirm" in section
    assert "Welcome" not in section


def test_read_pdf(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(make_pdf("Quarterly Report Highlights"))
    result = ft.read_document_aloud(str(path))
    assert "Quarterly Report Highlights" in result


def test_read_docx(tmp_path):
    from docx import Document

    path = tmp_path / "memo.docx"
    document = Document()
    document.add_paragraph("Board meeting minutes")
    document.add_paragraph("Budget approved.")
    document.save(str(path))
    result = ft.read_document_aloud(str(path))
    assert "Board meeting minutes" in result and "Budget approved" in result


def test_read_missing_or_unsupported(tmp_path):
    assert "couldn't find" in ft.read_document_aloud(str(tmp_path / "missing.txt")).lower()
    path = tmp_path / "data.xlsx"
    path.write_text("x", encoding="utf-8")
    assert "I can read text" in ft.read_document_aloud(str(path))


# ---- organizing ----

def test_organize_move(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    dest = tmp_path / "moved"
    result = ft.organize_files([str(src)], str(dest), "move")
    assert "Moved 1 file" in result
    assert (dest / "a.txt").read_text(encoding="utf-8") == "hello"
    assert not src.exists()


def test_organize_copy_and_rename(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    ft.organize_files([str(src)], str(tmp_path / "copied"), "copy")
    assert src.exists() and (tmp_path / "copied" / "a.txt").exists()

    target = tmp_path / "renamed.txt"
    result = ft.organize_files([str(src)], str(target), "rename")
    assert "Renamed 1 file" in result and target.exists()


def test_organize_overwrite_requires_confirmation(monkeypatch, tmp_path):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    src = src_dir / "a.txt"
    src.write_text("new", encoding="utf-8")
    (dest_dir / "a.txt").write_text("old", encoding="utf-8")

    bus = FakeBus(approved=False)
    monkeypatch.setattr("tools.event_bus.tool_bus", bus)
    result = ft.organize_files([str(src)], str(dest_dir), "copy")
    assert "overwrite cancelled" in result.lower()
    assert (dest_dir / "a.txt").read_text(encoding="utf-8") == "old"
    assert bus.calls

    bus.approved = True
    result = ft.organize_files([str(src)], str(dest_dir), "copy")
    assert "Copied 1 file" in result
    assert (dest_dir / "a.txt").read_text(encoding="utf-8") == "new"


def test_organize_invalid_action(tmp_path):
    assert "unsupported file action" in ft.organize_files([], str(tmp_path), "delete").lower()
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    assert "couldn't find any files" in ft.organize_files(
        [str(tmp_path / "missing.txt")], str(tmp_path / "d")
    ).lower()


# ---- registration / routing ----

def test_file_tools_registered():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert {"find_files", "read_document_aloud", "organize_files"} <= set(names)


def test_dispatch_file_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(ft, "find_files", lambda *a, **k: "found")
    monkeypatch.setattr(ft, "read_document_aloud", lambda *a, **k: "read")
    monkeypatch.setattr(ft, "organize_files", lambda *a, **k: "organized")
    assert os_tools.dispatch_tool("find_files", {"query": "x"}, None) == "found"
    assert os_tools.dispatch_tool("read_document_aloud", {"file_path": "x"}, None) == "read"
    assert os_tools.dispatch_tool("organize_files", {"pattern_or_paths": [], "destination_folder": "d"}, None) == "organized"
