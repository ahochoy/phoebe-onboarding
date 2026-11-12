from unittest.mock import Mock
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from phoebe.chat.models import (
    NO_ANSWER,
    REWRITE_SYSTEM,
    BedrockGuardrail,
    BedrockRewriter,
    ExtractiveAnswerModel,
    HarnessAnswerModel,
    HeuristicRewriter,
    Message,
    ModelUnavailable,
    NoGuardrail,
    make_models,
)
from phoebe.config import Settings


class Stream:
    def __init__(self, events: list[dict]) -> None:
        self.events = events
        self.closed = False

    def __iter__(self):
        return iter(self.events)

    def close(self) -> None:
        self.closed = True


def delta(text: str) -> dict:
    return {"contentBlockDelta": {"delta": {"text": text}}}


STOP = {"messageStop": {"stopReason": "end_turn"}}
MSGS: list[Message] = [{"role": "user", "text": "hello"}]


def harness(events: list[dict]) -> tuple[HarnessAnswerModel, Stream, Mock]:
    stream = Stream(events)
    client = Mock()
    client.invoke_harness.return_value = {"stream": stream}
    return (
        HarnessAnswerModel("arn:x", "us-east-2", client=client, max_tokens=700),
        stream,
        client,
    )


def test_harness_request_is_server_owned() -> None:
    model, stream, client = harness([delta("a"), STOP])
    list(
        model.stream(
            [{"role": "user", "text": "q"}, {"role": "assistant", "text": "r"}]
        )
    )
    kwargs = client.invoke_harness.call_args.kwargs
    UUID(kwargs.pop("runtimeSessionId"))
    assert kwargs == {
        "harnessArn": "arn:x",
        "messages": [
            {"role": "user", "content": [{"text": "q"}]},
            {"role": "assistant", "content": [{"text": "r"}]},
        ],
        "maxIterations": 1,
        "maxTokens": 700,
        "timeoutSeconds": 60,
        "allowedTools": ["phoebe_no_tools"],
    }
    assert stream.closed


def test_harness_yields_deltas_in_order() -> None:
    model, _, _ = harness([delta("one "), delta("two"), STOP])
    assert list(model.stream(MSGS)) == ["one ", "two"]


@pytest.mark.parametrize(
    "events",
    [
        [{"contentBlockStart": {"start": {"toolUse": {"name": "shell"}}}}],
        [{"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}],
        [{"runtimeClientError": {}}],
        [{"validationException": {}}],
        [{"internalServerException": {}}],
        [delta("x"), {"messageStop": {"stopReason": "max_tokens"}}],
        [delta("x")],
    ],
)
def test_harness_bad_streams_raise(events: list[dict]) -> None:
    model, stream, _ = harness(events)
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))
    assert stream.closed


def test_harness_tool_use_raises() -> None:
    model, _, _ = harness(
        [{"contentBlockStart": {"start": {"toolUse": {"name": "t"}}}}]
    )
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))


def test_harness_error_event_raises() -> None:
    model, _, _ = harness([{"runtimeClientError": {}}])
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))


def test_harness_max_tokens_stop_raises() -> None:
    model, _, _ = harness([{"messageStop": {"stopReason": "max_tokens"}}])
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))


def test_harness_missing_message_stop_raises() -> None:
    model, _, _ = harness([delta("x")])
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))


def test_harness_aws_error_is_clean() -> None:
    client = Mock()
    client.invoke_harness.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "private details"}},
        "InvokeHarness",
    )
    model = HarnessAnswerModel("arn:x", "us-east-2", client=client, max_tokens=10)
    with pytest.raises(ModelUnavailable) as info:
        list(model.stream(MSGS))
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    assert "private details" not in str(info.value)


def test_harness_malformed_response_raises() -> None:
    client = Mock()
    client.invoke_harness.return_value = {}
    model = HarnessAnswerModel("arn:x", "us-east-2", client=client, max_tokens=10)
    with pytest.raises(ModelUnavailable) as info:
        list(model.stream(MSGS))
    assert info.value.__suppress_context__


def test_harness_closes_stream_on_generator_close() -> None:
    model, stream, _ = harness([delta("a"), delta("b"), STOP])
    gen = model.stream(MSGS)
    assert next(gen) == "a"
    assert not stream.closed
    gen.close()
    assert stream.closed


def test_extractive_cites_p1() -> None:
    passage = '<passage id="P1" title="T">Wear a badge. Then relax.</passage>'
    msgs: list[Message] = [{"role": "user", "text": f"{passage}\nQuestion?"}]
    out = "".join(ExtractiveAnswerModel().stream(msgs))
    assert out == "Wear a badge. [P1]"


def test_extractive_unescapes_entities() -> None:
    passage = (
        '<passage id="P1">Fish &amp; chips &lt;ok&gt; &quot;yes&quot;. More.</passage>'
    )
    out = "".join(ExtractiveAnswerModel().stream([{"role": "user", "text": passage}]))
    assert out == 'Fish & chips <ok> "yes". [P1]'


def test_extractive_without_passage() -> None:
    out = "".join(ExtractiveAnswerModel().stream(MSGS))
    assert out == "NO_ANSWER"
    assert NO_ANSWER == "NO_ANSWER"


def test_heuristic_rewriter() -> None:
    r = HeuristicRewriter()
    assert r.rewrite([], "q2") == "q2"
    hist: list[Message] = [
        {"role": "user", "text": "first"},
        {"role": "assistant", "text": "a"},
    ]
    assert r.rewrite(hist, "q2") == "first q2"
    assert len(r.rewrite([{"role": "user", "text": "x" * 900}], "q")) == 500


def test_rewriter_bedrock_request_shape() -> None:
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "  vacation policy \n"}]}}
    }
    rw = BedrockRewriter("us.amazon.nova-micro-v1:0", "us-east-2", client=client)
    hist: list[Message] = [
        {"role": "user", "text": "pto?"},
        {"role": "assistant", "text": "15 days"},
    ]
    assert rw.rewrite(hist, "and sick?") == "vacation policy"
    kwargs = client.converse.call_args.kwargs
    assert kwargs["modelId"] == "us.amazon.nova-micro-v1:0"
    assert kwargs["system"] == [{"text": REWRITE_SYSTEM}]
    assert kwargs["inferenceConfig"] == {"maxTokens": 64, "temperature": 0}
    assert len(kwargs["messages"]) == 1 and kwargs["messages"][0]["role"] == "user"
    text = kwargs["messages"][0]["content"][0]["text"]
    assert "pto?" in text and "15 days" in text and "and sick?" in text


def test_rewriter_falls_back_on_error() -> None:
    client = Mock()
    client.converse.side_effect = RuntimeError("boom")
    rw = BedrockRewriter("m", "us-east-2", client=client)
    assert rw.rewrite([{"role": "user", "text": "a"}], "b") == "a b"
    client.converse.side_effect = None
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "  "}]}}
    }
    assert rw.rewrite([], "plain") == "plain"


def test_guardrail_intervened_false() -> None:
    client = Mock()
    client.apply_guardrail.return_value = {"action": "GUARDRAIL_INTERVENED"}
    g = BedrockGuardrail("gid", "1", "us-east-2", client=client)
    assert g.check("bad", "INPUT") is False
    assert client.apply_guardrail.call_args.kwargs == {
        "guardrailIdentifier": "gid",
        "guardrailVersion": "1",
        "source": "INPUT",
        "content": [{"text": {"text": "bad"}}],
    }
    client.apply_guardrail.return_value = {"action": "NONE"}
    assert g.check("ok", "OUTPUT") is True


def test_guardrail_error_raises_model_unavailable() -> None:
    client = Mock()
    client.apply_guardrail.side_effect = RuntimeError("x")
    with pytest.raises(ModelUnavailable):
        BedrockGuardrail("g", "1", "us-east-2", client=client).check("t", "INPUT")


def test_no_guardrail_allows() -> None:
    assert NoGuardrail().check("anything", "OUTPUT") is True


def settings(**kw: object) -> Settings:
    return Settings(database_url="postgresql://x", password_hash="h", **kw)  # pyright: ignore[reportArgumentType]


def test_make_models_defaults_offline() -> None:
    a, r, g = make_models(settings())
    assert isinstance(a, ExtractiveAnswerModel)
    assert isinstance(r, HeuristicRewriter)
    assert isinstance(g, NoGuardrail)


def test_make_models_requires_arn_for_harness() -> None:
    with pytest.raises(RuntimeError):
        make_models(settings(answer_backend="harness"))


def test_make_models_wires_aws_backends() -> None:
    a, r, g = make_models(
        settings(
            answer_backend="harness",
            harness_arn="arn:x",
            rewriter_backend="bedrock",
            guardrail_id="gid",
            guardrail_version="1",
        )
    )
    assert isinstance(a, HarnessAnswerModel)
    assert isinstance(r, BedrockRewriter)
    assert isinstance(g, BedrockGuardrail)


@pytest.mark.parametrize("kw", [{"guardrail_id": "gid"}, {"guardrail_version": "1"}])
def test_make_models_half_configured_guardrail_raises(kw: dict) -> None:
    with pytest.raises(RuntimeError):
        make_models(settings(**kw))
