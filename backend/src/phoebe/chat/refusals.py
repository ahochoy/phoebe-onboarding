"""Refusal reasons, their public codes and the text visitors see.

Reasons are internal names: they appear in server logs only. Visitors and the
`done` event see the numeric code instead. The leading digit groups codes:
1xxx answer quality, 2xxx safety, 3xxx availability. The numbers themselves
are arbitrary; never reuse a retired one.

| Code | Reason              | Meaning                                         |
|------|---------------------|-------------------------------------------------|
| 1001 | no_support          | Search found nothing relevant, or NO_ANSWER     |
| 1204 | verification_failed | Answer failed the citation check, or too long   |
| 2307 | blocked             | Guardrail blocked the question or the answer    |
| 3115 | model_unavailable   | Embedding, answer or guardrail model failed     |
"""

from typing import Literal

Reason = Literal["no_support", "verification_failed", "blocked", "model_unavailable"]
RefusalCode = Literal["1001", "1204", "2307", "3115"]

CODES: dict[Reason, RefusalCode] = {
    "no_support": "1001",
    "verification_failed": "1204",
    "blocked": "2307",
    "model_unavailable": "3115",
}

NOT_FOUND_TEXT = "I couldn't find that in your onboarding documents."

_MESSAGES: dict[Reason, str] = {
    "no_support": NOT_FOUND_TEXT,
    "verification_failed": (
        "I wrote an answer, but I couldn't verify everything with your documents."
        " Can you try asking another question?"
    ),
    "blocked": "I can't help with that request. Try rephrasing your question.",
    "model_unavailable": (
        "Phoebe's AI model isn't available right now. Try again in a moment."
    ),
}


def refusal_text(reason: Reason) -> str:
    """Visitor-facing text. Every reason but no_support ends with its code."""
    text = _MESSAGES[reason]
    return text if reason == "no_support" else f"{text} ({CODES[reason]})"
