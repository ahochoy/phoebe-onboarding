"""Heading-aware chunker: one or more word-window chunks per non-empty section.

Offsets are absolute into ``ParsedDocument.full_text``: a chunk's ``start`` is
the start of its first word and ``end`` the end of its last word, so
``full_text[c.start:c.end] == c.text`` always holds (the UI highlights it).
"""

import re
from dataclasses import dataclass

from phoebe.ingest.parse import ParsedDocument

_SEP = " › "
_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: str
    text: str
    start: int
    end: int


def embedding_text(chunk: Chunk) -> str:
    return f"{chunk.heading_path}\n\n{chunk.text}"


def chunk_document(
    parsed: ParsedDocument,
    doc_title: str,
    *,
    max_words: int = 380,
    overlap_words: int = 40,
) -> list[Chunk]:
    if overlap_words < 0 or max_words <= overlap_words:
        raise ValueError("require 0 <= overlap_words < max_words")
    title = doc_title.strip()
    step = max_words - overlap_words
    chunks: list[Chunk] = []
    for section in parsed.sections:
        if section.end <= section.start:
            continue
        spans = [
            (m.start() + section.start, m.end() + section.start)
            for m in _WORD.finditer(parsed.full_text[section.start : section.end])
        ]
        if not spans:
            continue
        path = section.heading_path
        if path and path[0].strip() == title:
            path = path[1:]
        heading = _SEP.join((title, *path))
        first = 0
        while True:
            last = min(first + max_words, len(spans))
            start, end = spans[first][0], spans[last - 1][1]
            chunks.append(
                Chunk(len(chunks), heading, parsed.full_text[start:end], start, end)
            )
            # A window reaching the last word ends the section; a later start
            # would only produce a chunk made entirely of overlap.
            if last == len(spans):
                break
            first += step
    return chunks
