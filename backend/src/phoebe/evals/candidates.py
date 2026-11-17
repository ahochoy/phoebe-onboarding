"""The answer models an eval run can use, with their prices.

Prices are USD per million tokens from https://aws.amazon.com/bedrock/pricing/
(US cross-region inference, Standard tier) on the date in `price_source`. A
price that page does not list is 0.0 with `price_source="unknown"`: the
scorecard says so instead of guessing. Update both when prices change.
"""

from dataclasses import dataclass

PRICES_CHECKED = "aws.amazon.com/bedrock/pricing 2026-11-17"


@dataclass(frozen=True)
class Candidate:
    name: str
    model_id: str | None  # None: the production harness (PHOEBE_HARNESS_ARN)
    harness: bool
    control: bool  # reported, never a switching candidate
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    price_source: str

    @property
    def price_known(self) -> bool:
        return self.price_source != "unknown"


CANDIDATES: dict[str, Candidate] = {
    c.name: c
    for c in (
        # Haiku 4.5 is not listed on the pricing page (checked 2026-11-17).
        Candidate(
            "haiku",
            None,
            harness=True,
            control=False,
            usd_per_mtok_in=0.0,
            usd_per_mtok_out=0.0,
            price_source="unknown",
        ),
        Candidate(
            "haiku-direct",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            harness=False,
            control=True,
            usd_per_mtok_in=0.0,
            usd_per_mtok_out=0.0,
            price_source="unknown",
        ),
        # Listed only as "Kimi K3.1 Pro - Highspeed", which may be a different model.
        Candidate(
            "kimi-k3.1",
            "us.moonshotai.kimi-k3.1",
            harness=False,
            control=False,
            usd_per_mtok_in=0.0,
            usd_per_mtok_out=0.0,
            price_source="unknown",
        ),
        Candidate(
            "glm-5.3",
            "us.zai.glm-5.3",
            harness=False,
            control=False,
            usd_per_mtok_in=1.848,
            usd_per_mtok_out=5.808,
            price_source=PRICES_CHECKED,
        ),
        # The page lists only an Asia Pacific (Sydney) price.
        Candidate(
            "gpt-oss-120b",
            "openai.gpt-oss-120b-1:0",
            harness=False,
            control=False,
            usd_per_mtok_in=0.0,
            usd_per_mtok_out=0.0,
            price_source="unknown",
        ),
    )
}


def resolve(selection: str) -> list[Candidate]:
    """`all`, one name, or a comma-separated list; `haiku` always first."""
    names = (
        list(CANDIDATES)
        if selection == "all"
        else [s.strip() for s in selection.split(",") if s.strip()]
    )
    unknown = [n for n in names if n not in CANDIDATES]
    if unknown:
        raise ValueError(
            f"unknown model(s): {', '.join(unknown)}; choose from {', '.join(CANDIDATES)} or all"
        )
    ordered = sorted(dict.fromkeys(names), key=lambda n: n != "haiku")
    return [CANDIDATES[n] for n in ordered]
