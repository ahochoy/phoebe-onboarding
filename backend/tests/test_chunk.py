import itertools

import pytest

from phoebe.ingest.chunk import Chunk, chunk_document, embedding_text
from phoebe.ingest.parse import ParsedDocument, Section, parse_markdown


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_small_sections_one_chunk_each():
    p = parse_markdown(b"# Leave\nPTO is 20 days.\n# Benefits\nDental.\n")
    cs = chunk_document(p, "Employee Handbook")
    assert [c.heading_path for c in cs] == [
        "Employee Handbook › Leave",
        "Employee Handbook › Benefits",
    ]
    assert [c.ordinal for c in cs] == [0, 1]
    assert all(p.full_text[c.start : c.end] == c.text for c in cs)


def test_long_section_splits_with_overlap_and_offsets():
    p = parse_markdown(f"# Big\n{_words(1000)}\n".encode())
    cs = chunk_document(p, "Doc")
    assert len(cs) == 3 and all(len(c.text.split()) <= 380 for c in cs)
    assert cs[0].text.split()[-40:] == cs[1].text.split()[:40]
    assert cs[1].text.split()[-40:] == cs[2].text.split()[:40]
    assert all(p.full_text[c.start : c.end] == c.text for c in cs)


def test_window_arithmetic_for_1000_words():
    # step = 380 - 40 = 340: windows [0,380) [340,720) [680,1000); next start 1020 > 1000.
    p = parse_markdown(f"# Big\n{_words(1000)}\n".encode())
    cs = chunk_document(p, "Doc")
    sizes = [len(c.text.split()) for c in cs]
    firsts = [c.text.split()[0] for c in cs]
    assert sizes == [380, 380, 320]
    assert firsts == ["w0", "w340", "w680"]
    assert cs[-1].text.split()[-1] == "w999"


def test_no_chunk_is_entirely_overlap():
    for n in (381, 400, 420, 700, 720, 721, 1020, 1021):
        p = parse_markdown(f"# S\n{_words(n)}\n".encode())
        cs = chunk_document(p, "D")
        assert cs[-1].text.split()[-1] == f"w{n - 1}"
        for a, b in itertools.pairwise(cs):
            new = len(b.text.split()) - 40
            assert new > 0, n
            assert len(a.text.split()) <= 380


def test_exactly_max_words_is_single_chunk():
    p = parse_markdown(f"# S\n{_words(380)}\n".encode())
    assert len(chunk_document(p, "D")) == 1


def test_empty_sections_skipped():
    cs = chunk_document(parse_markdown(b"# A\n\n# B\nreal text\n"), "D")
    assert [c.heading_path for c in cs] == ["D › B"]
    assert cs[0].ordinal == 0


def test_whitespace_only_section_skipped():
    p = ParsedDocument("   \n\nhello", [Section(("A",), 0, 3), Section(("B",), 5, 10)])
    cs = chunk_document(p, "D")
    assert [c.heading_path for c in cs] == ["D › B"]
    assert cs[0].start == 5 and cs[0].end == 10


def test_ordinal_counts_across_document():
    body = _words(500)
    p = parse_markdown(f"# A\n{body}\n# B\nshort\n".encode())
    cs = chunk_document(p, "D")
    assert [c.ordinal for c in cs] == [0, 1, 2]
    assert [c.heading_path for c in cs] == ["D › A", "D › A", "D › B"]


def test_offsets_exact_with_irregular_whitespace():
    p = parse_markdown(
        b"# A\n  alpha   beta\n\n  gamma\tdelta  \n# B\n\xc3\xa9t\xc3\xa9 caf\xc3\xa9\n"
    )
    cs = chunk_document(p, "D")
    assert all(p.full_text[c.start : c.end] == c.text for c in cs)
    assert cs[0].text == "alpha   beta\n\n  gamma\tdelta"


def test_heading_path_dedup_when_first_equals_title():
    p = parse_markdown(b"# Handbook\n## Leave\nPTO.\n")
    cs = chunk_document(p, "Handbook")
    assert [c.heading_path for c in cs] == ["Handbook › Leave"]


def test_heading_path_dedup_strips_and_is_case_sensitive():
    p = parse_markdown(b"# Handbook\nPTO.\n# handbook\nOther.\n")
    cs = chunk_document(p, "  Handbook ")
    assert [c.heading_path for c in cs] == ["Handbook", "Handbook › handbook"]


def test_empty_heading_path_uses_title():
    p = ParsedDocument("some text here", [Section((), 0, 14)])
    cs = chunk_document(p, "Notes")
    assert [c.heading_path for c in cs] == ["Notes"]


def test_multi_level_heading_path():
    p = parse_markdown(b"# A\n## B\ntext\n")
    assert chunk_document(p, "D")[0].heading_path == "D › A › B"


def test_custom_window_parameters():
    p = parse_markdown(f"# S\n{_words(10)}\n".encode())
    cs = chunk_document(p, "D", max_words=4, overlap_words=1)
    assert [c.text for c in cs] == ["w0 w1 w2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]


def test_zero_overlap():
    p = parse_markdown(f"# S\n{_words(8)}\n".encode())
    cs = chunk_document(p, "D", max_words=4, overlap_words=0)
    assert [c.text for c in cs] == ["w0 w1 w2 w3", "w4 w5 w6 w7"]


@pytest.mark.parametrize("max_words,overlap", [(40, 40), (10, 20), (10, -1)])
def test_invalid_parameters(max_words, overlap):
    p = parse_markdown(b"# A\ntext\n")
    with pytest.raises(ValueError):
        chunk_document(p, "D", max_words=max_words, overlap_words=overlap)


def test_embedding_text():
    c = Chunk(0, "D › A", "body text", 0, 9)
    assert embedding_text(c) == "D › A\n\nbody text"


def test_chunk_is_frozen():
    c = Chunk(0, "D", "x", 0, 1)
    with pytest.raises(AttributeError):
        c.text = "y"  # type: ignore[misc]
