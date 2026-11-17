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


def test_verify_rejects_uncited_text_after_heading() -> None:
    assert verify("# H\nuncited claim\n\nB [P1].", _passages(1)) is None


def test_verify_accepts_heading_with_cited_line() -> None:
    out = verify("# H\nclaim [P1].", _passages(1))
    assert out is not None
    assert out.text == "# H\nclaim [1]."


def test_verify_accepts_heading_only_paragraph() -> None:
    out = verify("## Only heading\n\nA [P1].", _passages(1))
    assert out is not None


def test_verify_requires_label_for_hash_without_space() -> None:
    assert verify("#not-a-heading claim\n\nA [P1].", _passages(1)) is None


def test_verify_rejects_empty_answer() -> None:
    assert verify("", _passages(1)) is None
    assert verify("  \n\n ", _passages(1)) is None


def test_verify_zero_padded_label_is_normalised() -> None:
    # [P01] parses as passage 1 and is renumbered like [P1].
    out = verify("A [P01].", _passages(1))
    assert out is not None
    assert out.text == "A [1]."


def test_verify_heading_requires_ascii_space_after_hashes() -> None:
    assert verify("# uncited\n\nA [P1].", _passages(1)) is None
    assert verify("#　uncited\n\nA [P1].", _passages(1)) is None
    assert verify("# 　uncited\n\nA [P1].", _passages(1)) is None


def test_verify_heading_allows_at_most_three_leading_spaces() -> None:
    assert verify("    # uncited\n\nA [P1].", _passages(1)) is None
    assert verify("   # Heading\n\nA [P1].", _passages(1)) is not None


LEAD_IN = (
    "Based on the Holiday Calendar, here are the holidays in November and December:"
)


def test_verify_accepts_uncited_lead_in_before_cited_paragraph() -> None:
    answer = f"{LEAD_IN}\n\n**November 2026:** Thanksgiving Day (November 26). [P2]"
    out = verify(answer, _passages(2))
    assert isinstance(out, Verified)
    assert out.text.startswith(LEAD_IN)
    assert [c.chunk_id for c in out.citations] == ["c2"]


def test_verify_rejects_lead_in_with_nothing_after_it() -> None:
    assert verify(f"A [P1].\n\n{LEAD_IN}", _passages(2)) is None
    assert verify(LEAD_IN, _passages(2)) is None


def test_verify_lead_in_only_at_the_start() -> None:
    answer = f"A [P1].\n\n{LEAD_IN}\n\nB [P2]."
    assert verify(answer, _passages(2)) is None


def test_verify_rejects_uncited_paragraph_without_colon() -> None:
    answer = "Here are the holidays.\n\nThanksgiving Day. [P1]"
    assert verify(answer, _passages(1)) is None


def test_verify_lead_in_must_be_one_short_line() -> None:
    two_lines = "Thanksgiving is a holiday.\nHere are the rest:\n\nB [P1]."
    assert verify(two_lines, _passages(1)) is None
    long_line = "x" * 200 + ":\n\nB [P1]."
    assert verify(long_line, _passages(1)) is None


def test_verify_lead_in_still_needs_a_cited_follow_up() -> None:
    answer = f"{LEAD_IN}\n\nThanksgiving Day.\n\nB [P1]."
    assert verify(answer, _passages(1)) is None
