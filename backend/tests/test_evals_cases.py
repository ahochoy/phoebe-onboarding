from pathlib import Path

import pytest
from pydantic import ValidationError

from phoebe.evals.cases import Case, Expect, load_cases

FORBIDDEN = {"Sales Playbook", "East Territory Notes", "Payments Runbook"}


def test_code_required_when_refused() -> None:
    with pytest.raises(ValidationError):
        Expect(answered=False)


def test_code_forbidden_when_answered() -> None:
    with pytest.raises(ValidationError):
        Expect(answered=True, code="1001")


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValidationError):
        Expect(answered=False, code="9999")


def test_code_may_list_alternatives() -> None:
    e = Expect(answered=False, code=["2307", "1001"])
    assert e.codes() == {"2307", "1001"}


def test_last_turn_needs_expect() -> None:
    with pytest.raises(ValidationError):
        Case(id="x", category="fact", turns=[{"question": "q"}])  # type: ignore[list-item]


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "q.yaml"
    p.write_text(body)
    return p


ONE = """
- id: {id}
  category: {cat}
  turns:
    - question: q
      expect: {{answered: true}}
"""


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path, ONE.format(id="a", cat="fact") + ONE.format(id="a", cat="list")
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(p)


def test_only_filters_by_id_or_category(tmp_path: Path) -> None:
    body = ONE.format(id="a", cat="fact") + ONE.format(id="b", cat="list")
    p = _write(tmp_path, body)
    assert [c.id for c in load_cases(p, only={"b"})] == ["b"]
    assert [c.id for c in load_cases(p, only={"fact"})] == ["a"]


def test_question_set_shape() -> None:
    cases = load_cases()
    assert len(cases) >= 28
    counts: dict[str, int] = {}
    for c in cases:
        counts[c.category] = counts.get(c.category, 0) + 1
    minimum = {
        "fact": 8,
        "list": 5,
        "follow_up": 4,
        "multi_doc": 3,
        "other_team": 4,
        "injection": 3,
        "off_topic": 3,
    }
    for cat, n in minimum.items():
        assert counts.get(cat, 0) >= n, cat
    for c in cases:
        if c.category == "other_team":
            last = c.turns[-1].expect
            assert last is not None and not last.answered and last.codes() == {"1001"}
            assert FORBIDDEN <= set(last.must_not_cite)
    hol = next(c for c in cases if c.id == "holidays-nov-dec")
    assert hol.category == "list"
    assert (
        hol.turns[-1].question == "What holidays do we have in November and December?"
    )
    exp = hol.turns[-1].expect
    assert exp is not None and exp.answered
    assert exp.must_cite == ["Holiday Calendar 2026-27"]
