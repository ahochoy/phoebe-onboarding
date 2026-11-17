import re
from typing import get_args

from phoebe.chat.refusals import (
    CODES,
    NOT_FOUND_TEXT,
    Reason,
    RefusalCode,
    refusal_text,
)


def test_every_reason_has_a_unique_four_digit_code() -> None:
    assert set(CODES) == set(get_args(Reason))
    assert sorted(CODES.values()) == sorted(get_args(RefusalCode))
    assert len(set(CODES.values())) == len(CODES)
    assert all(re.fullmatch(r"[1-9]\d{3}", code) for code in CODES.values())


def test_leading_digit_groups_codes() -> None:
    assert CODES["no_support"][0] == "1"
    assert CODES["verification_failed"][0] == "1"
    assert CODES["blocked"][0] == "2"
    assert CODES["model_unavailable"][0] == "3"


def test_not_found_text_is_only_for_no_support_and_has_no_code() -> None:
    assert refusal_text("no_support") == NOT_FOUND_TEXT
    others = [r for r in get_args(Reason) if r != "no_support"]
    assert all(NOT_FOUND_TEXT not in refusal_text(r) for r in others)


def test_other_reasons_end_with_their_code() -> None:
    assert refusal_text("verification_failed") == (
        "I wrote an answer, but I couldn't verify everything with your documents."
        " Can you try asking another question? (1204)"
    )
    assert refusal_text("blocked").endswith(" (2307)")
    assert refusal_text("model_unavailable").endswith(" (3115)")


def test_texts_never_leak_internal_reason_names() -> None:
    for reason in get_args(Reason):
        text = refusal_text(reason)
        assert all(name not in text for name in get_args(Reason))
