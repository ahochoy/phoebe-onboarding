import pytest
from fpdf import FPDF

from phoebe.ingest.parse import (
    ParsedDocument,
    ParseError,
    parse_csv,
    parse_html,
    parse_markdown,
    parse_pdf,
    parse_plain,
    sniff_upload,
)


def make_pdf(pages: list[str]) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in pages:
        pdf.add_page()
        if text:
            pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def check_invariant(p: ParsedDocument) -> list[str]:
    """Sections are ordered, non-overlapping, in range; returns each section's text."""
    prev_end = 0
    out: list[str] = []
    for s in p.sections:
        assert prev_end <= s.start <= s.end <= len(p.full_text)
        prev_end = s.end
        text = p.full_text[s.start : s.end]
        assert text == text.strip()
        out.append(text)
    assert p.full_text == "\n\n".join(out)
    return out


# --- markdown ---


def test_markdown_heading_paths():
    p = parse_markdown(b"# Handbook\nintro\n## Leave\n### PTO\n20 days\n")
    assert [s.heading_path for s in p.sections] == [
        ("Handbook",),
        ("Handbook", "Leave"),
        ("Handbook", "Leave", "PTO"),
    ]
    pto = p.sections[2]
    assert "20 days" in p.full_text[pto.start : pto.end]
    assert check_invariant(p) == ["intro", "", "20 days"]


def test_markdown_excludes_heading_line_and_preamble():
    p = parse_markdown(b"Welcome text\n\n# A\nbody a\n## B\nbody b\n## C\nbody c\n")
    assert [s.heading_path for s in p.sections] == [(), ("A",), ("A", "B"), ("A", "C")]
    assert check_invariant(p) == ["Welcome text", "body a", "body b", "body c"]
    assert "# A" not in p.full_text


def test_markdown_level_reset():
    p = parse_markdown(b"# A\n## B\nb\n# C\nc\n## D\nd\n")
    assert [s.heading_path for s in p.sections] == [
        ("A",),
        ("A", "B"),
        ("C",),
        ("C", "D"),
    ]
    check_invariant(p)


def test_markdown_skipped_level_and_deeper_headings_are_text():
    p = parse_markdown(b"# A\n### C\nc\n#### Not a heading\nmore\n")
    assert [s.heading_path for s in p.sections] == [("A",), ("A", "C")]
    assert "#### Not a heading" in p.full_text
    check_invariant(p)


def test_markdown_fenced_code_headings_ignored():
    p = parse_markdown(b"# A\n```\n# not heading\n```\nafter\n~~~\n## nope\n~~~\n")
    assert [s.heading_path for s in p.sections] == [("A",)]
    assert "# not heading" in p.full_text and "## nope" in p.full_text
    check_invariant(p)


def test_markdown_bom_and_crlf():
    p = parse_markdown("﻿# A\r\nline\r\n".encode())
    assert p.sections[0].heading_path == ("A",)
    assert "\r" not in p.full_text and "﻿" not in p.full_text
    check_invariant(p)


def test_markdown_non_utf8_fails():
    with pytest.raises(ParseError, match="UTF-8"):
        parse_markdown("é".encode("latin-1"))


@pytest.mark.parametrize("data", [b"", b"  \n\t\n"])
def test_markdown_empty(data: bytes):
    with pytest.raises(ParseError) as e:
        parse_markdown(data)
    assert e.value.reason == "Document is empty" and str(e.value) == "Document is empty"


# --- csv ---


def test_csv_bom_semicolon():
    p = parse_csv("﻿Date;Holiday\n2026-12-25;Christmas\n".encode())
    assert "Date: 2026-12-25; Holiday: Christmas" in p.full_text
    assert [s.heading_path for s in p.sections] == [("Rows 1–1",)]
    check_invariant(p)


def test_csv_tab_and_grouping():
    rows = "\n".join(f"{i}\tv{i}" for i in range(1, 31))
    p = parse_csv(f"n\tval\n{rows}\n".encode())
    assert [s.heading_path for s in p.sections] == [("Rows 1–25",), ("Rows 26–30",)]
    texts = check_invariant(p)
    assert texts[0].splitlines()[0] == "n: 1; val: v1"
    assert len(texts[1].splitlines()) == 5


def test_csv_too_many_rows():
    body = "a\n" + "x\n" * 5001
    with pytest.raises(ParseError, match="5,000"):
        parse_csv(body.encode())
    parse_csv(("a\n" + "x\n" * 5000).encode())


def test_csv_errors():
    with pytest.raises(ParseError, match="UTF-8"):
        parse_csv("é,b\n1,2\n".encode("latin-1"))
    for data in (b"", b"\n\n", b"a,b\n"):
        with pytest.raises(ParseError, match="Document is empty"):
            parse_csv(data)


# --- pdf ---


def test_pdf_pages():
    p = parse_pdf(make_pdf(["Page one text about PTO", "Second page benefits"]))
    assert [s.heading_path for s in p.sections] == [("Page 1",), ("Page 2",)]
    texts = check_invariant(p)
    assert "PTO" in texts[0] and "benefits" in texts[1]


def test_pdf_blank_page_keeps_numbering():
    p = parse_pdf(make_pdf(["Page one text about PTO", "", "Third page benefits"]))
    assert [s.heading_path for s in p.sections] == [
        ("Page 1",),
        ("Page 2",),
        ("Page 3",),
    ]
    assert check_invariant(p)[1] == ""


def test_pdf_without_text_fails():
    with pytest.raises(ParseError, match="scanned"):
        parse_pdf(make_pdf([""]))


def test_pdf_garbage_fails():
    with pytest.raises(ParseError, match="Could not read PDF"):
        parse_pdf(b"%PDF-1.4 garbage")


# --- html ---


def test_html_main_content():
    p = parse_html(
        "<nav>menu</nav><main><h1>Benefits</h1><p>Dental</p></main><footer>x</footer>"
    )
    assert "menu" not in p.full_text and p.sections[0].heading_path == ("Benefits",)
    assert check_invariant(p) == ["Dental"]


def test_html_body_fallback_and_headings():
    html = (
        "<html><head><style>p{}</style></head><body><header>top</header>"
        "<script>alert(1)</script><p>Intro <b>bold</b> text</p>"
        "<h1>A</h1><p>a</p><h2>B</h2><p>b1</p><p>b2</p><aside>side</aside></body></html>"
    )
    p = parse_html(html)
    assert [s.heading_path for s in p.sections] == [(), ("A",), ("A", "B")]
    texts = check_invariant(p)
    assert texts == ["Intro bold text", "a", "b1\nb2"]
    for banned in ("top", "alert", "side", "p{}"):
        assert banned not in p.full_text


def test_html_article_preferred_and_empty():
    p = parse_html("<body><p>skip</p><article><h1>T</h1><p>x</p></article></body>")
    assert "skip" not in p.full_text
    with pytest.raises(ParseError, match="Document is empty"):
        parse_html("<nav>only nav</nav>")


# --- plain ---


def test_plain_with_headings_delegates():
    p = parse_plain("# Title\nbody\n## Sub\nmore")
    assert [s.heading_path for s in p.sections] == [("Title",), ("Title", "Sub")]
    check_invariant(p)


def test_plain_without_headings():
    p = parse_plain("  just text\r\nline two\n#hashtag not heading\n")
    assert [s.heading_path for s in p.sections] == [()]
    assert check_invariant(p) == ["just text\nline two\n#hashtag not heading"]


def test_plain_empty():
    with pytest.raises(ParseError, match="Document is empty"):
        parse_plain("  \n ")


# --- sniff ---


def test_sniff_ok():
    assert sniff_upload("a.PDF", b"%PDF-1.7 x") == "pdf"
    assert sniff_upload("a.md", "# hi é".encode()) == "markdown"
    assert sniff_upload("a.markdown", b"hi") == "markdown"
    assert sniff_upload("a.csv", b"a,b\n1,2\n") == "csv"


def test_sniff_mismatch():
    with pytest.raises(ParseError, match="mismatched"):
        sniff_upload("a.pdf", b"# not a pdf")


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.md", b"%PDF-1.4"),
        ("a.csv", b"%PDF-1.4"),
        ("a.md", "é".encode("latin-1")),
        ("a.csv", b"a\x00b"),
        ("a.exe", b"MZ"),
        ("noext", b"hi"),
    ],
)
def test_sniff_rejects(name: str, data: bytes):
    with pytest.raises(ParseError, match="Unsupported or mismatched file type"):
        sniff_upload(name, data)


# --- hardening ---


def test_nul_stripped_everywhere():
    for p in (
        parse_markdown(b"# A\x00B\nbo\x00dy\n"),
        parse_csv(b"a,b\n1\x00,2\n"),
        parse_plain("te\x00xt"),
    ):
        assert "\x00" not in p.full_text
        assert all("\x00" not in "".join(s.heading_path) for s in p.sections)
        check_invariant(p)
    assert parse_markdown(b"# A\x00B\nx").sections[0].heading_path == ("AB",)


def test_nul_only_is_empty():
    with pytest.raises(ParseError, match="Document is empty"):
        parse_plain("\x00\x00")


def test_lone_surrogate_plain():
    p = parse_plain("ok \ud800 text")
    p.full_text.encode("utf-8")
    check_invariant(p)
    p = parse_plain("# T\ud800\nbody \udfff")
    p.full_text.encode("utf-8")
    p.sections[0].heading_path[0].encode("utf-8")
    check_invariant(p)


def test_sniff_markdown_nul():
    with pytest.raises(ParseError, match="mismatched"):
        sniff_upload("a.md", b"# hi\x00")


def test_html_deep_nesting_never_raises_other():
    html = "<div>" * 5000 + "text" + "</div>" * 5000
    try:
        p = parse_html(html)
    except ParseError:
        return
    assert isinstance(p, ParsedDocument)


def test_pdf_page_cap(monkeypatch: pytest.MonkeyPatch):
    import phoebe.ingest.parse as m

    monkeypatch.setattr(m, "MAX_PDF_PAGES", 2)
    with pytest.raises(ParseError, match="too many pages"):
        parse_pdf(make_pdf(["page one text here", "page two text here", "page three"]))


def test_pdf_text_cap(monkeypatch: pytest.MonkeyPatch):
    import phoebe.ingest.parse as m

    monkeypatch.setattr(m, "MAX_TEXT_CHARS", 30)
    with pytest.raises(ParseError, match="PDF text too large"):
        parse_pdf(make_pdf(["page one text here", "page two text here"]))


def test_text_cap_other_parsers(monkeypatch: pytest.MonkeyPatch):
    import phoebe.ingest.parse as m

    monkeypatch.setattr(m, "MAX_TEXT_CHARS", 10)
    with pytest.raises(ParseError, match="too large"):
        parse_plain("x" * 11)
    with pytest.raises(ParseError, match="too large"):
        parse_markdown(b"# A\n" + b"y" * 11)


def test_csv_row_cap_is_lazy(monkeypatch: pytest.MonkeyPatch):
    import phoebe.ingest.parse as m

    seen = 0

    def reader(f, **kw):  # type: ignore[no-untyped-def]
        nonlocal seen
        yield ["h"]
        for _ in range(10**9):
            seen += 1
            yield ["x"]

    monkeypatch.setattr(m.csv, "reader", reader)
    with pytest.raises(ParseError, match="5,000"):
        parse_csv(b"h\nx\n")
    assert seen <= m.MAX_CSV_ROWS + 2


def test_markdown_heading_regex_not_quadratic():
    import time

    line = ("# " + "a " * 50000 + "x").encode()
    t = time.perf_counter()
    p = parse_markdown(line + b"\nbody")
    assert time.perf_counter() - t < 1
    assert p.sections[0].heading_path[0].endswith("x")


def test_markdown_closing_hashes():
    p = parse_markdown(b"# A ##\nx\n## B#\ny\n")
    assert [s.heading_path for s in p.sections] == [("A",), ("A", "B#")]
