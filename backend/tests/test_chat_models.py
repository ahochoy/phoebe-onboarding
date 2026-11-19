from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from phoebe.chat.models import (
    NO_ANSWER,
    REWRITE_SYSTEM,
    BedrockGuardrail,
    BedrockRewriter,
    ConverseAnswerModel,
    ExtractiveAnswerModel,
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


def converse_client(client: Mock):
    from phoebe.chat.models import ConverseAnswerModel

    return ConverseAnswerModel("m", "us-east-2", max_tokens=10, client=client)


@pytest.mark.parametrize(
    "events",
    [
        [{"contentBlockStart": {"start": {"toolUse": {"name": "shell"}}}}],
        [{"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}],
        [{"modelStreamErrorException": {}}],
        [{"validationException": {}}],
        [{"internalServerException": {}}],
        [delta("x"), {"messageStop": {"stopReason": "max_tokens"}}],
        [delta("x")],
    ],
)
def test_converse_bad_streams_raise(events: list[dict]) -> None:
    model, stream = converse_with_stream(events)
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))
    assert stream.closed


def test_converse_aws_error_is_clean_and_logs_code_not_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "private details"}},
        "ConverseStream",
    )
    client = Mock()
    client.converse_stream.side_effect = error
    model = converse_client(client)
    with pytest.raises(ModelUnavailable) as info:
        list(model.stream(MSGS))
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__
    assert "private details" not in str(info.value)
    assert "AccessDeniedException" in caplog.text
    assert "private details" not in caplog.text


@pytest.mark.parametrize(
    ("events", "logged"),
    [
        ([{"validationException": {"message": "secret"}}], "validationException"),
        ([{"messageStop": {"stopReason": "max_tokens"}}], "max_tokens"),
    ],
)
def test_converse_stream_failures_log_their_kind(
    caplog: pytest.LogCaptureFixture, events: list[dict], logged: str
) -> None:
    model, _ = converse_with_stream(events)
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))
    assert logged in caplog.text
    assert "secret" not in caplog.text


def test_converse_malformed_response_raises() -> None:
    client = Mock()
    client.converse_stream.return_value = {}
    model = converse_client(client)
    with pytest.raises(ModelUnavailable) as info:
        list(model.stream(MSGS))
    assert info.value.__suppress_context__


def test_guardrail_error_logs_code(caplog: pytest.LogCaptureFixture) -> None:
    client = Mock()
    client.apply_guardrail.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "user text"}},
        "ApplyGuardrail",
    )
    with pytest.raises(ModelUnavailable):
        BedrockGuardrail("g", "1", "us-east-2", client=client).check("t", "INPUT")
    assert "ThrottlingException" in caplog.text
    assert "user text" not in caplog.text


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


def test_make_models_wires_aws_backends() -> None:
    a, r, g = make_models(
        settings(
            answer_backend="converse",
            rewriter_backend="bedrock",
            guardrail_id="gid",
            guardrail_version="1",
        )
    )
    assert isinstance(a, ConverseAnswerModel)
    assert isinstance(r, BedrockRewriter)
    assert isinstance(g, BedrockGuardrail)


@pytest.mark.parametrize("kw", [{"guardrail_id": "gid"}, {"guardrail_version": "1"}])
def test_make_models_half_configured_guardrail_raises(kw: dict) -> None:
    with pytest.raises(RuntimeError):
        make_models(settings(**kw))


# ---- converse: Haiku through Bedrock directly ------------------------------


def converse(events: list[dict]):
    from phoebe.chat.models import ConverseAnswerModel

    client = Mock()
    client.converse_stream.return_value = {"stream": iter(events)}
    model = ConverseAnswerModel(
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us-east-2",
        max_tokens=700,
        client=client,
    )
    return model, client


def test_converse_request_is_server_owned() -> None:
    from phoebe.chat.prompt import ANSWER_PROMPT_PATH

    model, client = converse([delta("a"), STOP])
    list(
        model.stream(
            [{"role": "user", "text": "q"}, {"role": "assistant", "text": "r"}]
        )
    )
    kwargs = client.converse_stream.call_args.kwargs
    assert kwargs == {
        "modelId": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "system": [{"text": ANSWER_PROMPT_PATH.read_text()}],
        "messages": [
            {"role": "user", "content": [{"text": "q"}]},
            {"role": "assistant", "content": [{"text": "r"}]},
        ],
        "inferenceConfig": {"temperature": 0.1, "maxTokens": 700},
    }
    assert "toolConfig" not in kwargs


@pytest.mark.parametrize(
    "event",
    [
        {"contentBlockStart": {"start": {"toolUse": {"name": "x", "toolUseId": "1"}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}},
    ],
)
def test_converse_tool_use_raises(event: dict) -> None:
    model, _ = converse([event, delta("leak"), STOP])
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))


def test_converse_reads_prompt_at_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from phoebe.chat import models

    monkeypatch.setattr(models, "ANSWER_PROMPT_PATH", tmp_path / "missing.txt")
    with pytest.raises(FileNotFoundError):
        models.ConverseAnswerModel("m", "us-east-2", max_tokens=700, client=Mock())


def test_make_models_converse() -> None:
    from phoebe.chat.models import ConverseAnswerModel

    a, _, _ = make_models(
        settings(answer_backend="converse", guardrail_id="gid", guardrail_version="1")
    )
    assert isinstance(a, ConverseAnswerModel)
    assert a._model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"  # pyright: ignore[reportPrivateUsage]
    assert a._max_tokens == 700  # pyright: ignore[reportPrivateUsage]


def test_converse_requires_guardrail_settings() -> None:
    with pytest.raises(RuntimeError, match="GUARDRAIL"):
        make_models(settings(answer_backend="converse"))


def test_eval_uses_the_production_converse_model() -> None:
    from phoebe.chat import models
    from phoebe.evals import converse as eval_converse

    assert eval_converse.ConverseAnswerModel is models.ConverseAnswerModel
    assert eval_converse.ModelUnsupported is models.ModelUnsupported


def converse_with_stream(events: list[dict], **kw):
    from phoebe.chat.models import ConverseAnswerModel

    stream = Stream(events)
    client = Mock()
    client.converse_stream.return_value = {"stream": stream}
    model = ConverseAnswerModel("m", "us-east-2", max_tokens=700, client=client, **kw)
    return model, stream


def test_converse_closes_the_stream_when_done() -> None:
    model, stream = converse_with_stream([delta("a"), STOP])
    list(model.stream(MSGS))
    assert stream.closed


def test_converse_closes_the_stream_on_tool_use() -> None:
    tool = {
        "contentBlockStart": {"start": {"toolUse": {"name": "x", "toolUseId": "1"}}}
    }
    model, stream = converse_with_stream([tool, delta("x"), STOP])
    with pytest.raises(ModelUnavailable):
        list(model.stream(MSGS))
    assert stream.closed


def test_converse_closes_the_stream_when_the_caller_stops_early() -> None:
    # The service closes the generator when an answer runs past its cap or the
    # visitor disconnects: the Bedrock stream must stop generating (and billing).
    model, stream = converse_with_stream([delta("a"), delta("b"), STOP])
    gen = model.stream(MSGS)
    next(gen)
    gen.close()
    assert stream.closed


def test_converse_enforces_a_total_deadline() -> None:
    # A stalled stream must end as
    # model_unavailable, not as a Lambda timeout mid-SSE.
    ticks = iter([0.0, 10.0, 61.0, 62.0, 63.0])
    model, stream = converse_with_stream(
        [delta("a"), delta("b"), delta("c"), STOP],
        timeout_seconds=60,
        clock=lambda: next(ticks),
    )
    out: list[str] = []
    with pytest.raises(ModelUnavailable):
        out.extend(model.stream(MSGS))  # appends each chunk before the raise
    assert out == ["a"]
    assert stream.closed
