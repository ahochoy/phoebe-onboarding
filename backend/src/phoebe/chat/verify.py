"""Citation verifier: the gate between model output and the user.

Rules: every paragraph with text beyond single-line Markdown headings carries a
valid `[P<n>]` label, every label names a real passage, and there is at least
one label. Labels are plain text matches, so `[P1]` inside backticks counts.
Anything else is refused (None). Labels are renumbered by first appearance.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from phoebe.chat.models import NO_ANSWER
from phoebe.retrieve import Passage

_LABEL = re.compile(r"\[P(\d+)\]")
_PARAGRAPHS = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"[ ]{0,3}#{1,6}[ \t]+\S.*")


class Citation(BaseModel):
    n: int
    chunk_id: str
    document_id: str
    document_title: str
    heading_path: str
    start: int
    end: int


@dataclass
class Verified:
    text: str
    citations: list[Citation]


def verify(answer: str, passages: Sequence[Passage]) -> Verified | None:
    stripped = answer.strip()
    if stripped.startswith(NO_ANSWER):
        return None
    labels = [int(m) for m in _LABEL.findall(stripped)]
    if not labels or any(not 1 <= n <= len(passages) for n in labels):
        return None
    for paragraph in _PARAGRAPHS.split(stripped):
        body = "\n".join(
            line
            for line in paragraph.splitlines()
            if line.strip() and not _HEADING.fullmatch(line.rstrip())
        )
        if body and not _LABEL.search(body):
            return None
    order: dict[int, int] = {}
    for n in labels:
        order.setdefault(n, len(order) + 1)
    text = _LABEL.sub(lambda m: f"[{order[int(m.group(1))]}]", stripped)
    citations = []
    for original, display in order.items():
        p = passages[original - 1]
        citations.append(
            Citation(
                n=display,
                chunk_id=p.chunk_id,
                document_id=p.document_id,
                document_title=p.document_title,
                heading_path=p.heading_path,
                start=p.start,
                end=p.end,
            )
        )
    return Verified(text=text, citations=citations)
