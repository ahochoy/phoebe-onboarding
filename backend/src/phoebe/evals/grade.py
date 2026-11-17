"""Deterministic grading of one chat turn against its expectations."""

from dataclasses import dataclass
from typing import Any, Literal

from phoebe.chat.refusals import CODES
from phoebe.evals.cases import Expect

MODEL_UNAVAILABLE = CODES["model_unavailable"]

Kind = Literal[
    "outcome",
    "code",
    "must_cite",
    "must_not_cite",
    "must_contain",
    "must_not_contain",
    "error",
]

# Hits that disqualify a candidate outright (the switching rule).
FORBIDDEN_KINDS: frozenset[str] = frozenset({"must_not_cite", "must_not_contain"})


@dataclass(frozen=True)
class Failure:
    kind: Kind
    detail: str


def grade(
    expect: Expect, done: dict[str, Any] | None, error: str | None = None
) -> list[Failure]:
    """Every expectation the turn missed; an empty list is a pass.

    `done` is the chat stream's `done` payload. Without one the turn is an
    `error` (the stream failed, or answered with an error event or status).
    """
    if done is None:
        return [Failure("error", error or "no done event")]
    refused = bool(done.get("refused"))
    reason = done.get("reason")
    # The app turns every answer-model failure (throttling, no access, a cut-off
    # stream) into a 3115 refusal: that is a broken run, not a wrong answer.
    if refused and reason == MODEL_UNAVAILABLE:
        return [Failure("error", f"{MODEL_UNAVAILABLE} model unavailable")]
    failures: list[Failure] = []
    if expect.answered and refused:
        failures.append(Failure("outcome", f"refused ({reason}), expected an answer"))
    elif not expect.answered and not refused:
        failures.append(Failure("outcome", "answered, expected a refusal"))
    elif not expect.answered and reason not in expect.codes():
        failures.append(
            Failure("code", f"refused {reason}, expected {sorted(expect.codes())}")
        )

    cited = {c.get("document_title") for c in done.get("citations") or []}
    offered = cited | {c.get("title") for c in done.get("closest") or []}
    if expect.must_cite and not cited & set(expect.must_cite):
        failures.append(Failure("must_cite", f"cited {sorted(t for t in cited if t)}"))
    failures.extend(
        Failure("must_not_cite", title)
        for title in expect.must_not_cite
        if title in offered
    )

    text = str(done.get("text") or "").casefold()
    failures.extend(
        Failure("must_contain", s)
        for s in expect.must_contain
        if s.casefold() not in text
    )
    failures.extend(
        Failure("must_not_contain", s)
        for s in expect.must_not_contain
        if s.casefold() in text
    )
    return failures
