import pytest

from phoebe.evals.candidates import CANDIDATES, resolve
from phoebe.evals.cases import Case
from phoebe.evals.cost import answer_cost, confirm, estimate

ONE_TURN = Case.model_validate(
    {
        "id": "a",
        "category": "fact",
        "turns": [{"question": "q", "expect": {"answered": True}}],
    }
)
TWO_TURNS = Case.model_validate(
    {
        "id": "b",
        "category": "follow_up",
        "turns": [{"question": "q1"}, {"question": "q2", "expect": {"answered": True}}],
    }
)


def test_names_match_the_spec() -> None:
    assert set(CANDIDATES) == {
        "haiku",
        "haiku-direct",
        "kimi-k3.1",
        "glm-5.3",
        "gpt-oss-120b",
    }
    assert CANDIDATES["haiku"].harness and CANDIDATES["haiku"].model_id is None
    assert CANDIDATES["haiku-direct"].control
    assert CANDIDATES["glm-5.3"].model_id == "us.zai.glm-5.3"
    assert CANDIDATES["kimi-k3.1"].model_id == "us.moonshotai.kimi-k3.1"
    assert CANDIDATES["gpt-oss-120b"].model_id == "openai.gpt-oss-120b-1:0"
    for c in CANDIDATES.values():
        assert c.price_source  # a date and source, or "unknown"


def test_resolve_all_puts_haiku_first() -> None:
    names = [c.name for c in resolve("all")]
    assert names[0] == "haiku" and set(names) == set(CANDIDATES)


def test_resolve_comma_list() -> None:
    assert [c.name for c in resolve("haiku,glm-5.3")] == ["haiku", "glm-5.3"]


def test_unknown_model_rejected() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        resolve("gpt-9")


def test_estimate_counts_every_turn_repeat_and_model() -> None:
    est = estimate([ONE_TURN, TWO_TURNS], resolve("haiku,glm-5.3"), repeat=2)
    assert est.calls == 3 * 2 * 2


def test_estimate_includes_fixed_costs() -> None:
    # A model with an unknown price still costs the guardrail passes.
    est = estimate([ONE_TURN], [CANDIDATES["haiku"]], repeat=1)
    assert est.usd_low > 0
    assert est.usd_high >= est.usd_low


def test_estimate_flags_unknown_prices() -> None:
    est = estimate([ONE_TURN], [CANDIDATES["haiku"], CANDIDATES["glm-5.3"]], repeat=1)
    assert est.unknown_prices == ["haiku"]


def test_answer_cost() -> None:
    glm = CANDIDATES["glm-5.3"]
    expected = (1_000_000 * glm.usd_per_mtok_in + 500_000 * glm.usd_per_mtok_out) / 1e6
    assert answer_cost(glm, 1_000_000, 500_000) == pytest.approx(expected)


def test_confirm_yes_skips_prompt() -> None:
    est = estimate([ONE_TURN], resolve("haiku"), repeat=1)

    def boom(_: str) -> str:
        raise AssertionError("asked")

    assert confirm(est, yes=True, stdin_isatty=False, ask=boom)


def test_confirm_asks_on_tty() -> None:
    est = estimate([ONE_TURN], resolve("haiku"), repeat=1)
    assert confirm(est, yes=False, stdin_isatty=True, ask=lambda _: "y")
    assert not confirm(est, yes=False, stdin_isatty=True, ask=lambda _: "n")


def test_confirm_refuses_without_tty_or_yes() -> None:
    est = estimate([ONE_TURN], resolve("haiku"), repeat=1)
    assert not confirm(est, yes=False, stdin_isatty=False, ask=lambda _: "y")


def test_describe_says_at_least_and_gives_a_worst_case() -> None:
    from phoebe.evals.cost import describe

    est = estimate([ONE_TURN], resolve("all"), repeat=1)
    text = describe(est)
    assert "at least $" in text
    assert "worst case" in text and "highest known price" in text
    assert est.usd_worst > est.usd_high
