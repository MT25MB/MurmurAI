"""Local file search, spoken document reading and safe batch organization.

Everything runs on the user's machine. Navigation/batch operations never delete
files, and any action that would overwrite an existing file goes through the
same spoken CONFIRMATION_REQUIRED flow used by the installer and shell tools.
"""

from __future__ import annotations

import fnmatch
import glob
import logging
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("murmur_ai.tools.file_tools")

IGNORED_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", ".idea", ".vscode",
    "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages",
    "AppData", "Library", ".cache", ".npm", ".cargo", ".rustup",
}
LOCATION_PRESETS = {
    "home": Path.home(),
    "downloads": Path.home() / "Downloads",
    "desktop": Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
}

MAX_WALK_DEPTH = 6
MAX_SCAN_ENTRIES = 20000
SPOKEN_SUMMARY_CHARS = 1600


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _speak(text: str) -> None:
    try:  # pragma: no cover - TTS optional
        from audio.speaker_provider import get_speaker

        speaker = get_speaker()
        if speaker is not None:
            speaker.speak(text)
    except Exception:
        logger.debug("File summary speech failed", exc_info=True)


def resolve_location(location: str = "home") -> Path:
    key = (location or "home").strip().lower()
    if key in LOCATION_PRESETS:
        return LOCATION_PRESETS[key]
    return Path(os.path.expanduser(location or "~"))


@dataclass
class FoundFile:
    path: Path
    modified: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def folder(self) -> str:
        return str(self.path.parent)


def _age(timestamp: float) -> str:
    seconds = max(0, time.time() - timestamp)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _walk_search(root: Path, query: str, extension: Optional[str], limit: int) -> list[FoundFile]:
    """Scandir-based search with an ignore list and depth bound."""
    needle = (query or "").lower().strip()
    ext = (extension or "").lower().lstrip(".")
    matches: list[FoundFile] = []
    scanned = 0

    def visit(directory: Path, depth: int) -> None:
        nonlocal scanned
        if depth > MAX_WALK_DEPTH or scanned >= MAX_SCAN_ENTRIES:
            return
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned >= MAX_SCAN_ENTRIES:
                        return
                    name = entry.name
                    if entry.is_dir(follow_symlinks=False):
                        if name in IGNORED_DIRS or name.startswith("."):
                            continue
                        visit(Path(entry.path), depth + 1)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if ext and not name.lower().endswith("." + ext):
                        continue
                    if needle and needle not in name.lower():
                        continue
                    try:
                        matches.append(FoundFile(Path(entry.path), entry.stat().st_mtime))
                    except OSError:
                        continue
        except OSError:
            return

    visit(root, 0)
    matches.sort(key=lambda item: item.modified, reverse=True)
    return matches[:limit]


def _native_search(root: Path, query: str, extension: Optional[str], limit: int) -> list[FoundFile]:
    """Use mdfind / Windows Search when available, else return []."""
    needle = " ".join(filter(None, [query, extension or ""])).strip()
    if not needle:
        return []
    system = platform.system()
    command: list[str] = []
    if system == "Darwin" and shutil.which("mdfind"):
        command = ["mdfind", f"kMDItemFSName == '*{needle}*'c", "-onlyin", str(root)]
    elif system == "Windows":
        command = ["where", "/r", str(root), f"*{needle}*"]
    if not command:
        return []
    try:  # pragma: no cover - environment dependent
        output = subprocess.run(
            command, capture_output=True, text=True, timeout=8, check=False
        ).stdout
    except Exception:
        return []
    files: list[FoundFile] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        path = Path(line)
        if not path.is_file():
            continue
        try:
            files.append(FoundFile(path, path.stat().st_mtime))
        except OSError:
            continue
    files.sort(key=lambda item: item.modified, reverse=True)
    return files[:limit]


def find_files(
    query: str, location: str = "home", extension: Optional[str] = None, limit: int = 10
) -> str:
    """Find local files by name and speak a concise summary of the top matches."""
    root = resolve_location(location)
    if not root.is_dir():
        return f"I couldn't find the folder {location}."
    count = max(1, min(50, int(limit or 10)))
    matches = _native_search(root, query, extension, count)
    if not matches:
        matches = _walk_search(root, query, extension, count)

    if not matches:
        summary = f"I didn't find any files matching {query or extension or 'that'} in {location}."
    else:
        parts = [f"Found {len(matches)} file{'s' if len(matches) != 1 else ''} matching {query or extension or 'your search'}."]
        for item in matches:
            parts.append(
                f"{item.name} in {item.folder}, modified {_age(item.modified)}."
            )
        summary = " ".join(parts)

    _speak(summary)
    return summary


# ---------------------------------------------------------------------------
# Document reading
# ---------------------------------------------------------------------------

def _extract_pdf(path: Path) -> str:
    try:  # pragma: no cover - depends on installed extras
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        pass
    try:  # pragma: no cover - depends on installed extras
        import fitz  # type: ignore

        with fitz.open(str(path)) as document:
            return "\n".join(page.get_text() for page in document)
    except Exception:
        return ""
    return ""


def _extract_docx(path: Path) -> str:
    try:  # pragma: no cover - depends on installed extras
        from docx import Document  # type: ignore

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)
    except Exception:
        return ""


def _clean_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Keep blank-line separators intact so document sections can be split later.
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", text, flags=re.M)
    text = re.sub(r"[*_`>#]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_document(path: Path) -> str:
    """Return clean plain text from a supported local document."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _clean_markdown(text) if suffix != ".txt" else text.strip()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    return ""


def _sections(text: str) -> list[tuple[str, str]]:
    """Split text into (heading, body) sections on headings or blank gaps."""
    parts = re.split(r"\n\s*\n", text)
    sections: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        heading = lines[0].strip()[:80]
        sections.append((heading, part))
    return sections


def read_document_aloud(file_path: str, section_or_query: Optional[str] = None) -> str:
    """Read a local document aloud, optionally only a matching section."""
    path = Path(os.path.expanduser(file_path or ""))
    if not path.is_file():
        return f"I couldn't find the file {file_path}."
    if path.suffix.lower() not in {".txt", ".md", ".markdown", ".pdf", ".docx"}:
        return f"I can read text, Markdown, PDF and Word documents, not {path.suffix or 'that type'}."

    text = extract_document(path)
    if not text.strip():
        return (
            f"I couldn't extract text from {path.name}. "
            "For PDFs install pypdf; for Word documents install python-docx."
        )

    if section_or_query:
        needle = section_or_query.strip().lower()
        for heading, body in _sections(text):
            if needle in heading.lower() or needle in body.lower():
                excerpt = body[:SPOKEN_SUMMARY_CHARS]
                _speak(f"From {path.name}, section {heading}. {excerpt}")
                return f"{heading}: {excerpt}"
        return f"I couldn't find a section about {section_or_query} in {path.name}."

    excerpt = text[:SPOKEN_SUMMARY_CHARS]
    words = len(text.split())
    summary = (
        f"{path.name} has {words} words. Here are the first {len(excerpt.split())} words. "
        f"{excerpt}"
    )
    _speak(summary)
    return summary


# ---------------------------------------------------------------------------
# Safe organization
# ---------------------------------------------------------------------------

def _expand_sources(patterns: Any) -> list[Path]:
    if isinstance(patterns, str):
        patterns = [patterns]
    sources: list[Path] = []
    for pattern in patterns or []:
        text = os.path.expanduser(str(pattern))
        if any(char in text for char in "*?["):
            sources.extend(Path(p) for p in glob.glob(text, recursive=False))
        else:
            path = Path(text)
            if path.exists():
                sources.append(path)
    return sources


def organize_files(
    pattern_or_paths: list[str], destination_folder: str, action: str = "move"
) -> str:
    """Move, copy or rename local files. Overwrites always need confirmation."""
    action = (action or "move").strip().lower()
    if action not in ("move", "copy", "rename"):
        return f"Unsupported file action {action}. I can move, copy, or rename."

    sources = _expand_sources(pattern_or_paths)
    if not sources:
        return "I couldn't find any files matching those paths."
    destination = Path(os.path.expanduser(destination_folder or ""))

    if action == "rename" and len(sources) == 1 and destination.suffix:
        targets = [destination]
        destination_dir = destination.parent
    else:
        destination_dir = destination
        targets = [destination / source.name for source in sources]

    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return f"I couldn't create the destination folder {destination_dir}."

    moved: list[str] = []
    skipped: list[str] = []
    for source, target in zip(sources, targets):
        try:
            if source.resolve() == target.resolve():
                skipped.append(f"{source.name} (already there)")
                continue
            if target.exists():
                from tools.event_bus import tool_bus

                approved = tool_bus.request_confirmation(
                    f"{target.name} already exists. Overwrite it with {source.name}?",
                    f"{action} {source} -> {target}",
                    timeout=60,
                )
                if not approved:
                    skipped.append(f"{source.name} (overwrite cancelled)")
                    continue
            if action in ("move", "rename"):
                shutil.move(str(source), str(target))
            else:
                shutil.copy2(str(source), str(target))
            moved.append(f"{source.name} -> {target}")
        except Exception:
            logger.exception("File organization failed for %s", source)
            skipped.append(f"{source.name} (failed)")

    verb = {"move": "Moved", "copy": "Copied", "rename": "Renamed"}[action]
    summary = f"{verb} {len(moved)} file{'s' if len(moved) != 1 else ''}."
    if moved:
        summary += " " + "; ".join(moved[:10])
    if skipped:
        summary += " Skipped: " + "; ".join(skipped[:10]) + "."
    _speak(summary)
    return summary


FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": (
                "Find local files by name in Home/Downloads/Desktop/Documents or "
                "an explicit folder. Returns names, folders and modified dates and "
                "speaks the summary. Use for 'where is my passport scan'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Filename words to match."},
                    "location": {"type": "string", "description": "Preset or local folder path."},
                    "extension": {"type": "string", "description": "Optional extension filter."},
                    "limit": {"type": "integer", "description": "Maximum results."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document_aloud",
            "description": (
                "Read a local .txt, .md, .pdf or .docx document aloud (or a "
                "matching section) for blind/low-vision users."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the document."},
                    "section_or_query": {
                        "type": "string",
                        "description": "Optional heading or topic to read.",
                    },
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "organize_files",
            "description": (
                "Move, copy or rename local files into a destination folder. "
                "Overwrites require spoken confirmation. Never deletes files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern_or_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Paths or glob patterns to organize.",
                    },
                    "destination_folder": {
                        "type": "string",
                        "description": "Destination folder (or full rename target for one file).",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["move", "copy", "rename"],
                        "description": "What to do.",
                    },
                },
                "required": ["pattern_or_paths", "destination_folder"],
                "additionalProperties": False,
            },
        },
    },
]
