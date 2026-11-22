"""Incremental sentence-boundary chunking for streamed local TTS.

Tokens arrive from a local model as they are generated. Complete sentences are
released immediately so synthesis can begin while the model is still writing.
An abbreviation-aware lookahead prevents splitting after "Dr." or "Mr." when
the sentence continues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A boundary is only certain once a non-whitespace character follows the mark.
_END_MARK = re.compile(r"[.!?](?:[\"')\u2019\u201d])?")
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "a.m", "p.m", "u.s", "no", "fig", "inc", "ltd", "co",
}
_WORD = re.compile(r"[A-Za-z]+(?:[.\'][A-Za-z]+)*")


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str


class SentenceChunker:
    """Accumulates streamed text and yields sentences at safe boundaries."""

    def __init__(self, abbreviations: set[str] | None = None) -> None:
        self._buffer = ""
        self._index = 0
        self._pending: re.Match | None = None
        self._abbreviations = set(abbreviations or _ABBREVIATIONS)

    def _is_abbreviation(self, match: re.Match) -> bool:
        tail = self._buffer[: match.start()].split()
        if not tail:
            return False
        return tail[-1].lower().strip(".,") in self._abbreviations

    def _release(self, through: int) -> Sentence | None:
        text = self._buffer[:through].strip()
        self._buffer = self._buffer[through:]
        self._pending = None
        if not text:
            return None
        sentence = Sentence(index=self._index, text=text)
        self._index += 1
        return sentence

    def feed(self, chunk: str) -> list[Sentence]:
        """Accept the next streamed text fragment; return newly complete sentences."""
        if not chunk:
            return []
        self._buffer += chunk
        out: list[Sentence] = []
        search_from = 0
        while True:
            match = _END_MARK.search(self._buffer, search_from)
            if match is None:
                return out
            if match.group(0).startswith(".") and self._is_abbreviation(match):
                search_from = match.end()
                continue
            after = self._buffer[match.end():]
            if not after or not after[0].isspace():
                # End mark at the buffer edge needs lookahead to confirm.
                return out
            sentence = self._release(match.end())
            if sentence is not None:
                out.append(sentence)
            self._buffer = self._buffer.lstrip()
            search_from = 0

    def flush(self) -> list[Sentence]:
        """Release the remaining partial sentence at end of stream."""
        text = self._buffer.strip()
        self._buffer = ""
        self._pending = None
        if not text:
            return []
        sentence = Sentence(index=self._index, text=text)
        self._index += 1
        return [sentence]


def chunk_text(text: str) -> list[Sentence]:
    """Split a complete text into sentences in one call."""
    chunker = SentenceChunker()
    result = chunker.feed(text)
    result.extend(chunker.flush())
    return result
