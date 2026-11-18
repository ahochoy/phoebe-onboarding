"""Answer system prompt location and passage fencing for model messages."""

import html
from collections.abc import Sequence

from phoebe.chat.models import ANSWER_PROMPT_PATH, Message
from phoebe.retrieve import Passage

__all__ = ["ANSWER_PROMPT_PATH", "build_messages"]


def _esc(value: str) -> str:
    return html.escape(value, quote=True).replace("&#x27;", "'")


def build_messages(
    history: Sequence[Message], passages: Sequence[Passage], question: str
) -> list[Message]:
    """History, then one user message: fenced passages and the question.

    Titles, sections, text and the question are entity-escaped so neither a
    document nor the visitor can close the fence or forge a passage.
    """
    parts = ["<passages>"]
    for i, p in enumerate(passages, start=1):
        parts.append(
            f'<passage id="P{i}" title="{_esc(p.document_title)}" '
            f'section="{_esc(p.heading_path)}">{_esc(p.text)}</passage>'
        )
    parts.append("</passages>")
    parts.append(f"Question: {_esc(question)}")
    return [*history, {"role": "user", "text": "\n".join(parts)}]
