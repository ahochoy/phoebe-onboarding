"""Document parsers: bytes/text in, clean text plus heading sections out.

Invariant for every parser: ``full_text`` is the section texts joined with
``"\\n\\n"``, and for each section ``full_text[s.start:s.end]`` is exactly that
section's text (no heading line; heading lives in ``heading_path``). Sections
are ordered and never overlap. A section may be empty (a heading with no body).

Resource limits: there is no in-process timeout. A pypdf hang is bounded by the
Lambda timeout (plan 4), and upload size is capped at 5 MB by the API (Task 13).
Parsers themselves cap page count, CSV rows and total extracted text.
"""

import csv
import io
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from pypdf import PdfReader

from phoebe.documents import DocType

MAX_CSV_ROWS = 5000
MAX_PDF_PAGES = 200
MAX_TEXT_CHARS = 2_000_000
CSV_ROWS_PER_SECTION = 25
MIN_PDF_CHARS = 20
_SEPARATOR = "\n\n"
_EMPTY = "Document is empty"


class ParseError(Exception):
    """A document could not be parsed; ``reason`` is safe to show to the user."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Section:
    heading_path: tuple[str, ...]
    start: int
    end: int


@dataclass
class ParsedDocument:
    full_text: str
    sections: list[Section]


def _clean(text: str) -> str:
    """Drop NUL (Postgres text rejects it) and replace lone surrogates."""
    text = text.replace("\x00", "")
    return text.encode("utf-8", "replace").decode("utf-8")


def _build(parts: list[tuple[tuple[str, ...], str]]) -> ParsedDocument:
    parts = [(tuple(_clean(h) for h in path), _clean(text)) for path, text in parts]
    if not any(text for _, text in parts):
        raise ParseError(_EMPTY)
    if sum(len(text) for _, text in parts) > MAX_TEXT_CHARS:
        raise ParseError("Document text too large")
    sections: list[Section] = []
    chunks: list[str] = []
    pos = 0
    for path, text in parts:
        if chunks:
            pos += len(_SEPARATOR)
        sections.append(Section(path, pos, pos + len(text)))
        chunks.append(text)
        pos += len(text)
    return ParsedDocument(_SEPARATOR.join(chunks), sections)


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ParseError("File is not UTF-8 text") from None
    return text.removeprefix("﻿")


def _newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# A heading item is (level, title); a text item is a str line.
_Item = tuple[int, str] | str


def _sections_from_items(items: list[_Item]) -> ParsedDocument:
    parts: list[tuple[tuple[str, ...], str]] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []

    def flush(start_of_doc: bool) -> None:
        text = "\n".join(lines).strip()
        if start_of_doc and not text:
            return  # nothing before the first heading
        parts.append((tuple(t for _, t in stack), text))

    first = True
    for item in items:
        if isinstance(item, str):
            lines.append(item)
            continue
        flush(first and not stack)
        first = False
        lines.clear()
        level, title = item
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
    flush(first and not stack)
    return _build(parts)


_HEADING_RE = re.compile(r"^ {0,3}(#{1,3})[ \t]+(.*)$")
_CLOSING_HASHES_RE = re.compile(r"[ \t]+#+$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def parse_markdown(data: bytes) -> ParsedDocument:
    return _parse_markdown_text(_decode(data))


def _parse_markdown_text(text: str) -> ParsedDocument:
    text = _newlines(_clean(text)).removeprefix("\ufeff")
    if not text.strip():
        raise ParseError(_EMPTY)
    items: list[_Item] = []
    fence: str | None = None
    for line in text.split("\n"):
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            items.append(line)
            continue
        h = None if fence else _HEADING_RE.match(line)
        title = _CLOSING_HASHES_RE.sub("", h.group(2).rstrip()).strip() if h else ""
        if h and title:
            items.append((len(h.group(1)), title))
        else:
            items.append(line)
    return _sections_from_items(items)


def parse_csv(data: bytes) -> ParsedDocument:
    text = _newlines(_decode(data))
    if not text.strip():
        raise ParseError(_EMPTY)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    rows: list[list[str]] = []
    try:
        for r in csv.reader(io.StringIO(text), delimiter=delimiter):
            if any(c.strip() for c in r):
                rows.append(r)
                if len(rows) > MAX_CSV_ROWS + 1:  # header + data rows
                    raise ParseError("CSV has more than 5,000 rows")
    except csv.Error:
        raise ParseError("Could not read CSV") from None
    if len(rows) < 2:
        raise ParseError(_EMPTY)
    headers = [h.strip() or f"Column {i}" for i, h in enumerate(rows[0], 1)]
    body = rows[1:]
    rendered = [
        "; ".join(
            f"{headers[i] if i < len(headers) else f'Column {i + 1}'}: {c.strip()}"
            for i, c in enumerate(row)
        )
        for row in body
    ]
    parts = []
    for i in range(0, len(rendered), CSV_ROWS_PER_SECTION):
        group = rendered[i : i + CSV_ROWS_PER_SECTION]
        parts.append(((f"Rows {i + 1}–{i + len(group)}",), "\n".join(group).strip()))
    return _build(parts)


def parse_pdf(data: bytes) -> ParsedDocument:
    pages: list[str] = []
    total = 0
    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
        if not encrypted and len(reader.pages) > MAX_PDF_PAGES:
            raise ParseError("PDF has too many pages")
        if not encrypted:
            for pg in reader.pages:
                text = _clean((pg.extract_text() or "").strip())
                total += len(text)
                if total > MAX_TEXT_CHARS:
                    raise ParseError("PDF text too large")
                pages.append(text)
    except ParseError:
        raise
    except Exception:  # noqa: BLE001 - pypdf raises many types on malformed input
        raise ParseError("Could not read PDF") from None
    if encrypted:
        raise ParseError("Could not read PDF")
    if total < MIN_PDF_CHARS:
        raise ParseError("No extractable text (scanned PDF?)")
    return _build([((f"Page {n}",), text) for n, text in enumerate(pages, 1)])


_DROP_TAGS = ["script", "style", "nav", "header", "footer", "aside"]
_BLOCK_TAGS = [
    "p", "div", "li", "ul", "ol", "tr", "table", "section", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "br", "hr",
]  # fmt: skip
_MARK = ""


def parse_html(html: str) -> ParsedDocument:
    try:
        items = _html_items(html)
    except Exception:  # noqa: BLE001 - bs4 can hit RecursionError on hostile nesting
        raise ParseError("Could not read HTML") from None
    return _sections_from_items(items)


def _html_items(html: str) -> list[_Item]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.find("body") or soup
    assert isinstance(root, (Tag, BeautifulSoup))
    for s in root.find_all(string=True):
        if _MARK in s:
            s.replace_with(NavigableString(s.replace(_MARK, "")))
    for h in root.find_all(["h1", "h2", "h3"]):
        title = " ".join(h.get_text(" ").split())
        h.replace_with(NavigableString(f"\n{_MARK}{h.name[1]}{_MARK}{title}\n"))
    for b in root.find_all(_BLOCK_TAGS):
        b.insert_before(NavigableString("\n"))
        b.insert_after(NavigableString("\n"))
    items: list[_Item] = []
    for raw in root.get_text("").split("\n"):
        line = " ".join(raw.split())
        if not line:
            continue
        m = re.match(f"^{_MARK}([123]){_MARK}(.*)$", line)
        if m and m.group(2):
            items.append((int(m.group(1)), m.group(2)))
        elif not m:
            items.append(line)
    return items


_MD_HEADING_LINE = re.compile(r"^#{1,3} ", re.MULTILINE)


def parse_plain(text: str) -> ParsedDocument:
    text = _newlines(text).removeprefix("﻿")
    if _MD_HEADING_LINE.search(text):
        return _parse_markdown_text(text)
    return _build([((), _clean(text).strip())])


def sniff_upload(filename: str, data: bytes) -> DocType:
    mismatch = ParseError("Unsupported or mismatched file type")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    is_pdf = data.startswith(b"%PDF-")
    if ext == "pdf":
        if is_pdf:
            return "pdf"
        raise mismatch
    if is_pdf or ext not in {"md", "markdown", "csv"}:
        raise mismatch
    if b"\x00" in data:
        raise mismatch
    if ext == "csv":
        return "csv"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise mismatch from None
    return "markdown"
