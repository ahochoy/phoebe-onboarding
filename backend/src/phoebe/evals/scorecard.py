"""Per-model scorecard and the quality-first switching verdict.

The rule (spec, owner's choice): a candidate qualifies to replace Haiku 4.5
only if, on the same run, it passes at least as many cases as `haiku` (the
production harness), has zero forbidden hits (must_not_cite, must_not_contain)
in any case or repeat, and has no more flaky cases than Haiku. Among
qualifiers the cheapest estimated cost per answer wins (known prices first),
and median latency breaks a tie. `haiku-direct` is a control and never wins.
"""

import statistics
from dataclasses import dataclass, field
from typing import Any

from phoebe.evals.candidates import Candidate
from phoebe.evals.cost import answer_cost
from phoebe.evals.grade import FORBIDDEN_KINDS, Failure

BASELINE = "haiku"


@dataclass
class CaseResult:
    model: str
    case_id: str
    category: str
    repeat: int
    failures: list[Failure]
    latency_s: float
    in_tok: int
    out_tok: int
    text: str
    done: dict[str, Any] | None


@dataclass
class ModelSummary:
    model: str
    control: bool
    unsupported: bool
    price_known: bool
    passed: int = 0
    failed: int = 0
    flaky: int = 0
    forbidden: int = 0
    errors: int = 0  # 3115s, failed streams: the run, not the model's answers
    by_category: dict[str, tuple[int, int]] = field(
        default_factory=dict[str, tuple[int, int]]
    )
    refusal_accuracy: float | None = None
    median_s: float | None = None
    p90_s: float | None = None
    cost_per_answer: float | None = None


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))]


def summarize(
    results: list[CaseResult],
    models: list[Candidate],
    unsupported: set[str] | None = None,
) -> list[ModelSummary]:
    unsupported = unsupported or set()
    out: list[ModelSummary] = []
    for m in models:
        mine = [x for x in results if x.model == m.name]
        s = ModelSummary(m.name, m.control, m.name in unsupported, m.price_known)
        cases: dict[str, list[CaseResult]] = {}
        for x in mine:
            cases.setdefault(x.case_id, []).append(x)
        totals: dict[str, list[int]] = {}
        for runs in cases.values():
            ok = [not x.failures for x in runs]
            cat = totals.setdefault(runs[0].category, [0, 0])
            cat[1] += 1
            if all(ok):
                s.passed += 1
                cat[0] += 1
            elif any(ok):
                s.flaky += 1
            else:
                s.failed += 1
        s.by_category = {k: (v[0], v[1]) for k, v in sorted(totals.items())}
        s.forbidden = sum(
            1 for x in mine for f in x.failures if f.kind in FORBIDDEN_KINDS
        )
        s.errors = sum(1 for x in mine for f in x.failures if f.kind == "error")
        if mine:
            right = [
                x
                for x in mine
                if not any(f.kind in {"outcome", "error"} for f in x.failures)
            ]
            s.refusal_accuracy = len(right) / len(mine)
            latencies = [x.latency_s for x in mine]
            s.median_s = statistics.median(latencies)
            s.p90_s = _p90(latencies)
            if m.price_known:
                s.cost_per_answer = answer_cost(
                    m,
                    round(statistics.mean(x.in_tok for x in mine)),
                    round(statistics.mean(x.out_tok for x in mine)),
                )
        out.append(s)
    return out


def verdict(summaries: list[ModelSummary]) -> str:
    base = next((s for s in summaries if s.model == BASELINE), None)
    if base is None or base.unsupported:
        return f"no verdict: the run needs the {BASELINE} baseline (MODEL=all or include {BASELINE})"
    if base.errors:
        # A throttled or paused harness would make every candidate look better.
        return (
            f"no verdict: the {BASELINE} baseline had {base.errors} error(s) "
            "(model unavailable or a failed stream); re-run"
        )
    qualifiers = [
        s
        for s in summaries
        if s.model != BASELINE
        and not s.control
        and not s.unsupported
        and s.passed >= base.passed
        and s.forbidden == 0
        and s.errors == 0
        and s.flaky <= base.flaky
    ]
    if not qualifiers:
        return "keep Haiku 4.5 (no candidate qualifies)"
    inf = float("inf")
    ranked = sorted(
        qualifiers,
        key=lambda s: (
            s.cost_per_answer if s.cost_per_answer is not None else inf,
            s.median_s if s.median_s is not None else inf,
        ),
    )
    best = ranked[0]
    others = [
        f"{s.model}{'' if s.price_known else ' (price unknown)'}" for s in ranked[1:]
    ]
    line = f"switch candidate: {best.model}"
    if not best.price_known:
        line += " (no qualifier has a known price; picked on latency)"
    if others:
        line += f"; also qualifies: {', '.join(others)}"
    return line + ". Confirm through a staging harness before switching."


def _fmt(v: float | None, spec: str) -> str:
    return "-" if v is None else format(v, spec)


def render(summaries: list[ModelSummary], results: list[CaseResult]) -> str:
    header = (
        f"{'model':<14} {'pass':>5} {'fail':>5} {'flaky':>5} {'forbid':>6} "
        f"{'refusal ok':>10} {'p50 s':>6} {'p90 s':>6} {'$/answer':>9}"
    )
    lines = [header]
    for s in summaries:
        if s.unsupported:
            lines.append(f"{s.model:<14} unsupported (rejected the request shape)")
            continue
        cost = _fmt(s.cost_per_answer, ".5f") if s.price_known else "price unknown"
        tag = " (control)" if s.control else ""
        lines.append(
            f"{s.model + tag:<14} {s.passed:>5} {s.failed:>5} {s.flaky:>5} {s.forbidden:>6} "
            f"{_fmt(s.refusal_accuracy, '.0%'):>10} {_fmt(s.median_s, '.1f'):>6} "
            f"{_fmt(s.p90_s, '.1f'):>6} {cost:>9}"
        )
        cats = ", ".join(f"{k} {p}/{t}" for k, (p, t) in s.by_category.items())
        if cats:
            lines.append(f"{'':<14} {cats}")
    failing = [
        f"  {x.case_id} {x.model} {f.kind}: {f.detail}"
        for x in results
        for f in x.failures
    ]
    if failing:
        lines += ["", "failures:", *failing]
    lines += ["", f"verdict: {verdict(summaries)}"]
    return "\n".join(lines)
