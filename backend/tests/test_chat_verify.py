from phoebe.chat.verify import Verified, verify
from phoebe.retrieve import Passage


def _passages(n: int) -> list[Passage]:
    return [
        Passage(
            chunk_id=f"c{i}",
            document_id=f"d{i}",
            document_title=f"Doc {i}",
            heading_path=f"H{i}",
            text="t",
            start=i,
            end=i + 10,
            score=0.1,
            vector_rank=i,
            text_rank=i,
            similarity=0.9,
        )
        for i in range(1, n + 1)
    ]


def test_verify_accepts_and_renumbers() -> None:
    out = verify("A [P3].\n\nB [P1][P3].", _passages(3))
    assert isinstance(out, Verified)
    assert out.text == "A [1].\n\nB [2][1]."
    assert [c.n for c in out.citations] == [1, 2]
    assert [c.chunk_id for c in out.citations] == ["c3", "c1"]
    first = out.citations[0]
    assert first.model_dump() == {
        "n": 1,
        "chunk_id": "c3",
        "document_id": "d3",
        "document_title": "Doc 3",
        "heading_path": "H3",
        "start": 3,
        "end": 13,
    }


def test_verify_rejects_unknown_label() -> None:
    assert verify("A [P4].", _passages(3)) is None
    assert verify("A [P0].", _passages(3)) is None


def test_verify_rejects_uncited_paragraph() -> None:
    assert verify("A [P1].\n\nB has no label.", _passages(2)) is None


def test_verify_rejects_no_labels() -> None:
    assert verify("Just text.", _passages(2)) is None


def test_verify_rejects_no_answer() -> None:
    assert verify("NO_ANSWER", _passages(2)) is None
    assert verify("  NO_ANSWER\n", _passages(2)) is None
    assert verify("NO_ANSWER but [P1]", _passages(2)) is None


def test_verify_exempts_heading_line() -> None:
    out = verify("# Title\n\nA [P1].", _passages(1))
    assert out is not None
    assert out.text == "# Title\n\nA [1]."


def test_verify_counts_labels_inside_code() -> None:
    out = verify("Use `[P1]` here.", _passages(1))
    assert out is not None
    assert out.text == "Use `[1]` here."
