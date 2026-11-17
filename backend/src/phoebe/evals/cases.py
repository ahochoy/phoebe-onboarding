"""The eval question set: schema and loader for backend/evals/questions.yaml."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from phoebe.chat.refusals import CODES

# backend/evals/questions.yaml; this file is backend/src/phoebe/evals/cases.py.
QUESTIONS_PATH = Path(__file__).resolve().parents[3] / "evals" / "questions.yaml"

REFUSAL_CODES = frozenset(CODES.values())

Category = Literal[
    "fact", "list", "follow_up", "multi_doc", "other_team", "injection", "off_topic"
]


class Expect(BaseModel):
    """What a correct turn looks like. Titles are document titles."""

    model_config = ConfigDict(extra="forbid")

    answered: bool
    # A refusal's public code, or several acceptable ones (any of).
    code: str | list[str] | None = None
    must_cite: list[str] = []  # any one of these titles is cited
    must_not_cite: list[str] = []  # never cited, nor offered as closest
    must_contain: list[str] = []  # case-insensitive substrings of the answer
    must_not_contain: list[str] = []

    def codes(self) -> set[str]:
        if self.code is None:
            return set()
        return {self.code} if isinstance(self.code, str) else set(self.code)

    @model_validator(mode="after")
    def _code_matches_outcome(self) -> Self:
        if self.answered and self.code is not None:
            raise ValueError("an answered turn has no refusal code")
        if not self.answered and not self.codes():
            raise ValueError("a refused turn needs its refusal code")
        unknown = self.codes() - REFUSAL_CODES
        if unknown:
            raise ValueError(f"unknown refusal code(s): {sorted(unknown)}")
        return self


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    expect: Expect | None = None


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: Category
    turns: list[Turn]

    @model_validator(mode="after")
    def _last_turn_graded(self) -> Self:
        if not self.turns or self.turns[-1].expect is None:
            raise ValueError(f"case {self.id}: the last turn needs `expect`")
        return self


def load_cases(path: Path = QUESTIONS_PATH, only: set[str] | None = None) -> list[Case]:
    """Every case in the file; `only` keeps cases whose id or category is listed."""
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise TypeError(f"{path}: expected a list of cases")
    cases = [Case.model_validate(item) for item in raw]  # pyright: ignore[reportUnknownVariableType]
    seen: set[str] = set()
    for c in cases:
        if c.id in seen:
            raise ValueError(f"duplicate case id: {c.id}")
        seen.add(c.id)
    if only:
        cases = [c for c in cases if c.id in only or c.category in only]
    return cases
