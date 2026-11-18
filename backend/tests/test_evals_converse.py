from typing import Any

import pytest
from botocore.exceptions import ClientError

from phoebe.chat.models import ModelUnavailable
from phoebe.chat.prompt import ANSWER_PROMPT_PATH
from phoebe.evals.converse import ConverseAnswerModel, ModelUnsupported

OK_EVENTS: list[dict[str, Any]] = [
    {"messageStart": {"role": "assistant"}},
    {"contentBlockDelta": {"delta": {"text": "You get 20 "}}},
    {"contentBlockDelta": {"delta": {"reasoningContent": {"text": "hidden"}}}},
    {"contentBlockDelta": {"delta": {"text": "days [P1]."}}},
    {"messageStop": {"stopReason": "end_turn"}},
    {"metadata": {"usage": {"inputTokens": 900, "outputTokens": 12}}},
]


class Stub:
    def __init__(
        self, events: list[dict[str, Any]] | None = None, exc: Exception | None = None
    ):
        self.events = OK_EVENTS if events is None else events
        self.exc = exc
        self.kwargs: dict[str, Any] = {}

    def converse_stream(self, **kwargs: Any) -> dict[str, Any]:
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return {"stream": iter(self.events)}


def model(stub: Stub) -> ConverseAnswerModel:
    return ConverseAnswerModel(
        "us.example.model", "us-east-2", max_tokens=700, client=stub
    )


MESSAGES = [
    {"role": "user", "text": "earlier"},
    {"role": "assistant", "text": "answer [P1]"},
    {"role": "user", "text": "<passages>...</passages> question"},
]


def test_request_shape() -> None:
    stub = Stub()
    list(model(stub).stream(MESSAGES))  # type: ignore[arg-type]
    assert stub.kwargs["modelId"] == "us.example.model"
    assert stub.kwargs["system"] == [{"text": ANSWER_PROMPT_PATH.read_text()}]
    assert stub.kwargs["messages"] == [
        {"role": m["role"], "content": [{"text": m["text"]}]} for m in MESSAGES
    ]
    assert stub.kwargs["inferenceConfig"] == {"temperature": 0.1, "maxTokens": 700}


def test_streams_text_deltas() -> None:
    assert "".join(model(Stub()).stream(MESSAGES)) == "You get 20 days [P1]."  # type: ignore[arg-type]


def test_records_usage_from_metadata() -> None:
    m = model(Stub())
    list(m.stream(MESSAGES))  # type: ignore[arg-type]
    assert m.usage == {"inputTokens": 900, "outputTokens": 12}


def test_usage_accumulates_and_defaults_to_zero() -> None:
    m = model(
        Stub(
            events=[
                {"contentBlockDelta": {"delta": {"text": "x"}}},
                {"messageStop": {"stopReason": "end_turn"}},
            ]
        )
    )
    list(m.stream(MESSAGES))  # type: ignore[arg-type]
    assert m.usage == {"inputTokens": 0, "outputTokens": 0}


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "ConverseStream")


def test_validation_error_is_unsupported() -> None:
    with pytest.raises(ModelUnsupported):
        list(model(Stub(exc=_client_error("ValidationException"))).stream(MESSAGES))  # type: ignore[arg-type]


def test_unsupported_is_a_model_unavailable() -> None:
    assert issubclass(ModelUnsupported, ModelUnavailable)


def test_other_errors_are_model_unavailable() -> None:
    with pytest.raises(ModelUnavailable) as info:
        list(model(Stub(exc=_client_error("ThrottlingException"))).stream(MESSAGES))  # type: ignore[arg-type]
    assert not isinstance(info.value, ModelUnsupported)


def test_stream_error_event_is_model_unavailable() -> None:
    events = [{"throttlingException": {"message": "slow down"}}]
    with pytest.raises(ModelUnavailable):
        list(model(Stub(events=events)).stream(MESSAGES))  # type: ignore[arg-type]


def test_incomplete_answer_is_model_unavailable() -> None:
    events = [
        {"contentBlockDelta": {"delta": {"text": "cut"}}},
        {"messageStop": {"stopReason": "max_tokens"}},
    ]
    with pytest.raises(ModelUnavailable):
        list(model(Stub(events=events)).stream(MESSAGES))  # type: ignore[arg-type]


def test_temperature_omitted_when_none() -> None:
    # Some models (Kimi K3.1) reject any temperature field.
    stub = Stub()
    m = ConverseAnswerModel(
        "us.example.model", "us-east-2", max_tokens=700, temperature=None, client=stub
    )
    list(m.stream(MESSAGES))  # type: ignore[arg-type]
    assert stub.kwargs["inferenceConfig"] == {"maxTokens": 700}
