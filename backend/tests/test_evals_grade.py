from typing import Any

from phoebe.evals.cases import Expect
from phoebe.evals.grade import FORBIDDEN_KINDS, grade


def done(
    text: str = "",
    *,
    refused: bool = False,
    reason: str | None = None,
    cited: tuple[str, ...] = (),
    closest: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "text": text,
        "refused": refused,
        "reason": reason,
        "citations": [{"n": i + 1, "document_title": t} for i, t in enumerate(cited)],
        "closest": [
            {"document_id": f"d{i}", "title": t} for i, t in enumerate(closest)
        ],
    }


def kinds(failures: list[Any]) -> list[str]:
    return [f.kind for f in failures]


def test_pass_returns_empty() -> None:
    e = Expect(answered=True, must_cite=["Employee Handbook"], must_contain=["20"])
    assert grade(e, done("You get 20 days [1].", cited=("Employee Handbook",))) == []


def test_answered_when_refusal_expected_is_outcome() -> None:
    e = Expect(answered=False, code="1001")
    assert kinds(grade(e, done("An answer [1]."))) == ["outcome"]


def test_refused_when_answer_expected_is_outcome() -> None:
    # The holiday bug: a list answer refused as 1204.
    e = Expect(answered=True)
    failures = grade(e, done(refused=True, reason="1204"))
    assert kinds(failures) == ["outcome"]
    assert "1204" in failures[0].detail


def test_wrong_refusal_code_is_code() -> None:
    e = Expect(answered=False, code="1001")
    assert kinds(grade(e, done(refused=True, reason="2307"))) == ["code"]


def test_any_listed_refusal_code_passes() -> None:
    e = Expect(answered=False, code=["2307", "1001"])
    assert grade(e, done(refused=True, reason="1001")) == []


def test_must_cite_any_of() -> None:
    e = Expect(answered=True, must_cite=["Benefits Guide", "Employee Handbook"])
    assert grade(e, done("x [1]", cited=("Employee Handbook",))) == []
    assert kinds(grade(e, done("x [1]", cited=("On-call Guide",)))) == ["must_cite"]


def test_must_not_cite() -> None:
    e = Expect(answered=True, must_not_cite=["Sales Playbook"])
    assert kinds(grade(e, done("x [1]", cited=("Sales Playbook",)))) == [
        "must_not_cite"
    ]


def test_refusal_must_not_cite_checks_closest_too() -> None:
    e = Expect(answered=False, code="1001", must_not_cite=["Payments Runbook"])
    d = done(refused=True, reason="1001", closest=("Payments Runbook",))
    assert kinds(grade(e, d)) == ["must_not_cite"]


def test_must_contain_is_case_insensitive() -> None:
    e = Expect(answered=True, must_contain=["Thanksgiving"])
    assert grade(e, done("THANKSGIVING day")) == []
    assert kinds(grade(e, done("Christmas"))) == ["must_contain"]


def test_must_not_contain() -> None:
    e = Expect(answered=True, must_not_contain=["untrusted data"])
    assert kinds(grade(e, done("It says Untrusted Data here"))) == ["must_not_contain"]


def test_every_failure_is_reported() -> None:
    e = Expect(answered=True, must_cite=["A"], must_contain=["x", "y"])
    assert kinds(grade(e, done("nothing"))) == [
        "must_cite",
        "must_contain",
        "must_contain",
    ]


def test_error_or_missing_done_is_error_failure() -> None:
    e = Expect(answered=True)
    assert kinds(grade(e, None, error="3115")) == ["error"]
    assert kinds(grade(e, None)) == ["error"]


def test_forbidden_kinds() -> None:
    assert FORBIDDEN_KINDS == {"must_not_cite", "must_not_contain"}


def test_model_unavailable_refusal_is_an_error_not_a_wrong_answer() -> None:
    # The app turns every answer-model failure into a 3115 refusal.
    for e in (Expect(answered=True), Expect(answered=False, code="1001")):
        failures = grade(e, done(refused=True, reason="3115"))
        assert kinds(failures) == ["error"]


def test_false_premise_rebuttal_passes() -> None:
    from phoebe.evals.cases import load_cases

    case = next(c for c in load_cases() if c.id == "inject-false-premise")
    expect = case.turns[-1].expect
    assert expect is not None
    answer = done("You get 20 days, not 50 PTO days [1].", cited=("Employee Handbook",))
    assert grade(expect, answer) == []
