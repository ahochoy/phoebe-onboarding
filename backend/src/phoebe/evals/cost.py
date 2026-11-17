"""Cost of a run: an estimate before it starts, and the confirmation gate."""

from collections.abc import Callable
from dataclasses import dataclass, field

from phoebe.evals.candidates import CANDIDATES, Candidate
from phoebe.evals.cases import Case

# Rough sizes of one chat turn's answer call: the system prompt plus up to
# eight fenced passages and the question in, a short cited answer out.
IN_TOKENS = (2_000, 3_500)
OUT_TOKENS = (100, 500)

# Fixed per-turn costs whatever the answer model. Guardrails: one content
# policy, $0.15 per 1,000 text units (a unit is up to 1,000 characters),
# checked on the question and on the answer: about 1 to 3 units per turn
# (aws.amazon.com/bedrock/pricing 2026-11-17). Titan embeddings and the Nova
# Micro rewriter are not listed there; they are a few hundredths of a cent per
# turn and are left out of the estimate.
GUARDRAIL_USD_PER_UNIT = 0.15 / 1_000
GUARDRAIL_UNITS = (1, 3)


@dataclass
class Estimate:
    calls: int
    usd_low: float  # known prices only: a floor, not a range
    usd_high: float
    # Every model priced at the highest known price, with long answers: an
    # assumption, stated as such, never a price for a model.
    usd_worst: float = 0.0
    unknown_prices: list[str] = field(default_factory=list[str])


def answer_cost(c: Candidate, in_tok: int, out_tok: int) -> float:
    return (in_tok * c.usd_per_mtok_in + out_tok * c.usd_per_mtok_out) / 1_000_000


def estimate(cases: list[Case], models: list[Candidate], repeat: int) -> Estimate:
    turns = sum(len(c.turns) for c in cases) * repeat
    low = high = 0.0
    for m in models:
        low += turns * (
            answer_cost(m, IN_TOKENS[0], OUT_TOKENS[0])
            + GUARDRAIL_UNITS[0] * GUARDRAIL_USD_PER_UNIT
        )
        high += turns * (
            answer_cost(m, IN_TOKENS[1], OUT_TOKENS[1])
            + GUARDRAIL_UNITS[1] * GUARDRAIL_USD_PER_UNIT
        )
    known = [m for m in CANDIDATES.values() if m.price_known]
    top_in = max((m.usd_per_mtok_in for m in known), default=0.0)
    top_out = max((m.usd_per_mtok_out for m in known), default=0.0)
    per_turn_worst = (
        IN_TOKENS[1] * top_in + OUT_TOKENS[1] * top_out
    ) / 1_000_000 + GUARDRAIL_UNITS[1] * GUARDRAIL_USD_PER_UNIT
    return Estimate(
        calls=turns * len(models),
        usd_low=low,
        usd_high=high,
        usd_worst=turns * len(models) * per_turn_worst,
        unknown_prices=[m.name for m in models if not m.price_known],
    )


def describe(est: Estimate) -> str:
    line = f"{est.calls} chat calls, at least ${est.usd_low:.2f}"
    if est.unknown_prices:
        line += (
            f" (no listed price for {', '.join(est.unknown_prices)}); worst case about "
            f"${est.usd_worst:.2f} if every model cost the highest known price"
        )
    else:
        line += f", up to about ${est.usd_high:.2f}"
    return (
        line
        + ". Each model also re-embeds the seed documents (Titan, price unlisted)."
        + " This spends from the shared account spend limit."
    )


def confirm(
    est: Estimate,
    *,
    yes: bool,
    stdin_isatty: bool,
    ask: Callable[[str], str] = input,
) -> bool:
    """Go only on YES=1 or a `y` typed at a terminal; never by default."""
    print(describe(est))
    if yes:
        return True
    if not stdin_isatty:
        print("refusing: no terminal to confirm on; set YES=1 to run")
        return False
    return ask("Run it? [y/N] ").strip().lower() in {"y", "yes"}
