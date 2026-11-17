from phoebe.evals.candidates import CANDIDATES, Candidate
from phoebe.evals.grade import Failure
from phoebe.evals.scorecard import CaseResult, render, summarize, verdict

OUTCOME = Failure("outcome", "refused (1204), expected an answer")
FORBIDDEN = Failure("must_not_cite", "Sales Playbook")


def r(
    model: str,
    case: str,
    *,
    fail: Failure | None = None,
    repeat: int = 0,
    latency: float = 1.0,
    category: str = "fact",
) -> CaseResult:
    return CaseResult(
        model=model,
        case_id=case,
        category=category,
        repeat=repeat,
        failures=[fail] if fail else [],
        latency_s=latency,
        in_tok=2000,
        out_tok=200,
        text="",
        done=None,
    )


def models(*names: str) -> list[Candidate]:
    return [CANDIDATES[n] for n in names]


def by_name(results: list[CaseResult], *names: str):
    return {s.model: s for s in summarize(results, models(*names))}


def test_case_passes_only_if_all_repeats_pass() -> None:
    s = by_name([r("haiku", "a"), r("haiku", "a", repeat=1)], "haiku")["haiku"]
    assert (s.passed, s.failed, s.flaky) == (1, 0, 0)


def test_mixed_repeats_are_flaky_not_failed() -> None:
    res = [
        r("haiku", "a"),
        r("haiku", "a", repeat=1, fail=OUTCOME),
        r("haiku", "b", fail=OUTCOME),
    ]
    s = by_name(res, "haiku")["haiku"]
    assert (s.passed, s.failed, s.flaky) == (0, 1, 1)


def test_counts_forbidden_hits_and_by_category() -> None:
    res = [r("glm-5.3", "a", fail=FORBIDDEN), r("glm-5.3", "b", category="list")]
    s = by_name(res, "glm-5.3")["glm-5.3"]
    assert s.forbidden == 1
    assert s.by_category == {"fact": (0, 1), "list": (1, 1)}


def base(extra: list[CaseResult]) -> list[CaseResult]:
    # Haiku passes a and b, fails c.
    return [r("haiku", "a"), r("haiku", "b"), r("haiku", "c", fail=OUTCOME), *extra]


def test_verdict_keeps_haiku_when_no_candidate_matches_pass_count() -> None:
    res = base(
        [
            r("glm-5.3", "a"),
            r("glm-5.3", "b", fail=OUTCOME),
            r("glm-5.3", "c", fail=OUTCOME),
        ]
    )
    assert verdict(summarize(res, models("haiku", "glm-5.3"))).startswith(
        "keep Haiku 4.5"
    )


def test_verdict_rejects_candidate_with_any_forbidden_hit() -> None:
    res = base(
        [r("glm-5.3", "a"), r("glm-5.3", "b"), r("glm-5.3", "c", fail=FORBIDDEN)]
    )
    assert verdict(summarize(res, models("haiku", "glm-5.3"))).startswith(
        "keep Haiku 4.5"
    )


def test_verdict_rejects_more_flaky_than_haiku() -> None:
    res = base(
        [
            r("glm-5.3", "a"),
            r("glm-5.3", "b"),
            r("glm-5.3", "c"),
            r("glm-5.3", "a", repeat=1, fail=OUTCOME),
        ]
    )
    assert verdict(summarize(res, models("haiku", "glm-5.3"))).startswith(
        "keep Haiku 4.5"
    )


def all_pass(model: str, latency: float = 1.0) -> list[CaseResult]:
    return [r(model, c, latency=latency) for c in ("a", "b", "c")]


def test_verdict_picks_cheapest_qualifier() -> None:
    # glm-5.3 has a known price; kimi-k3.1's is unknown, so glm-5.3 wins on price.
    res = base([*all_pass("glm-5.3", latency=5.0), *all_pass("kimi-k3.1", latency=1.0)])
    v = verdict(summarize(res, models("haiku", "glm-5.3", "kimi-k3.1")))
    assert v.startswith("switch candidate: glm-5.3")
    assert "kimi-k3.1" in v  # also qualifies, price unknown


def test_verdict_tie_breaks_on_latency_when_prices_unknown() -> None:
    res = base(
        [*all_pass("kimi-k3.1", latency=3.0), *all_pass("gpt-oss-120b", latency=1.0)]
    )
    v = verdict(summarize(res, models("haiku", "kimi-k3.1", "gpt-oss-120b")))
    assert v.startswith("switch candidate: gpt-oss-120b")


def test_control_never_wins() -> None:
    res = base(all_pass("haiku-direct"))
    assert verdict(summarize(res, models("haiku", "haiku-direct"))).startswith(
        "keep Haiku 4.5"
    )


def test_unsupported_model_never_wins() -> None:
    s = summarize(
        base(all_pass("glm-5.3")), models("haiku", "glm-5.3"), unsupported={"glm-5.3"}
    )
    assert verdict(s).startswith("keep Haiku 4.5")


def test_verdict_needs_the_haiku_baseline() -> None:
    v = verdict(summarize(all_pass("glm-5.3"), models("glm-5.3")))
    assert "haiku" in v and "baseline" in v


def test_render_lists_failing_cases_and_verdict() -> None:
    res = base(all_pass("glm-5.3"))
    out = render(summarize(res, models("haiku", "glm-5.3")), res)
    assert "c haiku outcome: refused (1204), expected an answer" in out
    assert "verdict: switch candidate: glm-5.3" in out
    assert "price unknown" in out  # haiku's price is not listed
