"""AI adapters: answer model, query rewriter, guardrail.

All request parameters are server-owned. Offline defaults need no AWS. Errors
carry no provider text; nothing here logs question or answer text.
"""

import html
import logging
import re
from collections.abc import Generator, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.config import Settings

Message = TypedDict("Message", {"role": Literal["user", "assistant"], "text": str})

# The answer system prompt: backend/prompts/answer.txt (this file is
# backend/src/phoebe/chat/models.py). The converse backend sends it with every
# request; infra/ai bakes the same file into the harnesses.
ANSWER_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "answer.txt"

# Machine sentinel emitted by the model; detected by the verifier and stream.
NO_ANSWER = "NO_ANSWER"
REWRITE_SYSTEM = (
    "Rewrite the user's final question as one standalone search query for an "
    "employee handbook search. Use earlier turns only to resolve references. "
    "Output the query only, no quotes, no explanation."
)
_QUERY_MAX_CHARS = 500


class ModelUnavailable(Exception):
    """A model call failed; carries no provider or user text."""


_log = logging.getLogger("phoebe.chat")


def _error_kind(exc: BaseException) -> str:
    """An AWS error code or exception type name: never the error message,
    which may echo user or provider text."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code")
        if isinstance(code, str) and code:
            return code
    return type(exc).__name__


def _unavailable(what: str, kind: str) -> ModelUnavailable:
    _log.warning("%s kind=%s", what, kind)
    return ModelUnavailable(what)


class AnswerModel(Protocol):
    def stream(self, messages: Sequence[Message]) -> Iterator[str]: ...


def _client(service: str, region: str) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        service,
        region_name=region,
        config=Config(
            connect_timeout=5,
            read_timeout=90,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


_STREAM_ERRORS = (
    "runtimeClientError",
    "validationException",
    "internalServerException",
)


class HarnessAnswerModel:
    def __init__(
        self,
        harness_arn: str,
        region: str,
        *,
        client: Any = None,
        max_tokens: int,
        timeout_seconds: int = 60,
    ) -> None:
        self._arn = harness_arn
        self._region = region
        self._client = client
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds

    def stream(self, messages: Sequence[Message]) -> Generator[str]:
        try:
            if self._client is None:
                self._client = _client("bedrock-agentcore", self._region)
            response = self._client.invoke_harness(
                harnessArn=self._arn,
                runtimeSessionId=str(uuid4()),
                messages=[
                    {"role": m["role"], "content": [{"text": m["text"]}]}
                    for m in messages
                ],
                maxIterations=1,
                maxTokens=self._max_tokens,
                timeoutSeconds=self._timeout,
                # A nonmatching allowlist keeps built-in tools unexposed.
                allowedTools=["phoebe_no_tools"],
            )
            events = response["stream"]
        except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
            raise _unavailable("model request failed", _error_kind(exc)) from None
        completed = False
        try:
            for event in events:
                errors = [key for key in _STREAM_ERRORS if key in event]
                if errors:
                    raise _unavailable("model stream error", errors[0]) from None
                start = event.get("contentBlockStart")
                if start and start.get("start", {}).get("toolUse"):
                    raise ModelUnavailable("tool use not allowed") from None
                block = event.get("contentBlockDelta")
                if block:
                    d = block.get("delta", {})
                    if "toolUse" in d:
                        raise ModelUnavailable("tool use not allowed") from None
                    text = d.get("text", "")
                    if text:
                        yield text
                stop = event.get("messageStop")
                if stop:
                    reason = stop.get("stopReason")
                    if reason != "end_turn":
                        raise _unavailable(
                            "incomplete answer", str(reason)[:40]
                        ) from None
                    completed = True
        except (BotoCoreError, ClientError) as exc:
            raise _unavailable("model stream failed", _error_kind(exc)) from None
        finally:
            events.close()
        if not completed:
            raise _unavailable("stream ended early", "no_message_stop")


# Converse (Bedrock directly): error events the stream can carry instead of
# raising, and the sampling setting the harness used (infra/ai/main.tf).
_CONVERSE_STREAM_ERRORS = (
    "internalServerException",
    "modelStreamErrorException",
    "validationException",
    "throttlingException",
    "serviceUnavailableException",
)
TEMPERATURE = 0.1


class ModelUnsupported(ModelUnavailable):
    """The model rejects the request shape (for example a field it does not
    accept). The eval reports such a model as unsupported."""


class ConverseAnswerModel:
    """Haiku 4.5 (or an eval candidate) through Bedrock ConverseStream.

    Sends what the harness sent: the system prompt, the app's messages, the
    temperature and max_tokens. No tools: the request has no tool config, and a
    tool-use block in the stream is refused. The prompt is read once here, so a
    missing prompt file fails at startup, not on the first chat.
    """

    def __init__(
        self,
        model_id: str,
        region: str,
        *,
        max_tokens: int,
        temperature: float | None = TEMPERATURE,
        client: Any = None,
    ) -> None:
        self._model_id = model_id
        self._region = region
        self._max_tokens = max_tokens
        # None: send no temperature field (some models reject any value).
        self._temperature = temperature
        self._client = client
        self._system = ANSWER_PROMPT_PATH.read_text()
        self.usage: dict[str, int] = {"inputTokens": 0, "outputTokens": 0}

    def stream(self, messages: Sequence[Message]) -> Generator[str]:
        try:
            if self._client is None:
                self._client = _client("bedrock-runtime", self._region)
            inference: dict[str, Any] = {"maxTokens": self._max_tokens}
            if self._temperature is not None:
                inference = {"temperature": self._temperature, **inference}
            response = self._client.converse_stream(
                modelId=self._model_id,
                system=[{"text": self._system}],
                messages=[
                    {"role": m["role"], "content": [{"text": m["text"]}]}
                    for m in messages
                ],
                inferenceConfig=inference,
            )
            events = response["stream"]
        except ClientError as exc:
            if _error_kind(exc) == "ValidationException":
                raise ModelUnsupported("request shape rejected") from None
            raise _unavailable("model request failed", _error_kind(exc)) from None
        except (BotoCoreError, KeyError, TypeError) as exc:
            raise _unavailable("model request failed", _error_kind(exc)) from None
        completed = False
        try:
            for event in events:
                errors = [key for key in _CONVERSE_STREAM_ERRORS if key in event]
                if errors:
                    raise _unavailable("model stream error", errors[0]) from None
                start = event.get("contentBlockStart")
                if start and start.get("start", {}).get("toolUse"):
                    raise ModelUnavailable("tool use not allowed") from None
                delta = event.get("contentBlockDelta", {}).get("delta", {})
                if "toolUse" in delta:
                    raise ModelUnavailable("tool use not allowed") from None
                # Reasoning models stream their thinking separately; only text
                # reaches the answer.
                text = delta.get("text", "")
                if text:
                    yield text
                stop = event.get("messageStop")
                if stop:
                    reason = stop.get("stopReason")
                    if reason != "end_turn":
                        raise _unavailable(
                            "incomplete answer", str(reason)[:40]
                        ) from None
                    completed = True
                usage = event.get("metadata", {}).get("usage")
                if usage:
                    for key in ("inputTokens", "outputTokens"):
                        self.usage[key] += int(usage.get(key, 0))
        except (BotoCoreError, ClientError) as exc:
            raise _unavailable("model stream failed", _error_kind(exc)) from None
        if not completed:
            raise _unavailable("stream ended early", "no_message_stop")


_PASSAGE = re.compile(r"<passage\s+id=\"P1\"[^>]*>(.*?)</passage>", re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


class ExtractiveAnswerModel:
    """Offline default: first sentence of passage P1, cited."""

    def stream(self, messages: Sequence[Message]) -> Generator[str]:
        last_user = next(
            (m["text"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        match = _PASSAGE.search(last_user)
        sentence = html.unescape(match.group(1)).strip() if match else ""
        sentence = _SENTENCE_END.split(sentence, maxsplit=1)[0].strip()
        if not sentence:
            yield NO_ANSWER
            return
        for word in sentence.split():
            yield word + " "
        yield "[P1]"


class Rewriter(Protocol):
    def rewrite(self, history: Sequence[Message], question: str) -> str: ...


class HeuristicRewriter:
    def rewrite(self, history: Sequence[Message], question: str) -> str:
        last = next((m["text"] for m in reversed(history) if m["role"] == "user"), None)
        if last is None:
            return question
        return f"{last} {question}"[:_QUERY_MAX_CHARS]


class BedrockRewriter:
    def __init__(
        self,
        model_id: str,
        region: str,
        *,
        client: Any = None,
        max_tokens: int = 64,
        history_exchanges: int = 3,
        fallback: Rewriter | None = None,
    ) -> None:
        self._model_id = model_id
        self._region = region
        self._client = client
        self._max_tokens = max_tokens
        self._turns = history_exchanges * 2
        self._fallback = fallback or HeuristicRewriter()

    def rewrite(self, history: Sequence[Message], question: str) -> str:
        if not history:
            return question
        try:
            if self._client is None:
                self._client = _client("bedrock-runtime", self._region)
            lines = [f"{m['role']}: {m['text']}" for m in history[-self._turns :]]
            prompt = "\n".join(lines) + f"\nFinal question: {question}"
            resp = self._client.converse(
                modelId=self._model_id,
                system=[{"text": REWRITE_SYSTEM}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": self._max_tokens, "temperature": 0},
            )
            blocks = resp["output"]["message"]["content"]
            out = "".join(b.get("text", "") for b in blocks).strip()[:_QUERY_MAX_CHARS]
        except Exception as exc:  # noqa: BLE001 - any failure uses the heuristic
            _log.info("rewriter fell back kind=%s", _error_kind(exc))
            return self._fallback.rewrite(history, question)
        return out or self._fallback.rewrite(history, question)


class Guardrail(Protocol):
    def check(self, text: str, source: Literal["INPUT", "OUTPUT"]) -> bool: ...


class NoGuardrail:
    def check(self, text: str, source: Literal["INPUT", "OUTPUT"]) -> bool:
        return True


class BedrockGuardrail:
    def __init__(
        self, guardrail_id: str, version: str, region: str, *, client: Any = None
    ) -> None:
        self._id = guardrail_id
        self._version = version
        self._region = region
        self._client = client

    def check(self, text: str, source: Literal["INPUT", "OUTPUT"]) -> bool:
        try:
            if self._client is None:
                self._client = _client("bedrock-runtime", self._region)
            resp = self._client.apply_guardrail(
                guardrailIdentifier=self._id,
                guardrailVersion=self._version,
                source=source,
                content=[{"text": {"text": text}}],
            )
            return resp["action"] != "GUARDRAIL_INTERVENED"
        except Exception as exc:  # noqa: BLE001 - nothing chained: may echo text
            raise _unavailable("guardrail request failed", _error_kind(exc)) from None


def make_models(settings: Settings) -> tuple[AnswerModel, Rewriter, Guardrail]:
    answer: AnswerModel
    if settings.answer_backend == "harness":
        if not settings.harness_arn:
            raise RuntimeError("PHOEBE_HARNESS_ARN is required for the harness backend")
        answer = HarnessAnswerModel(
            settings.harness_arn,
            settings.aws_region,
            max_tokens=settings.answer_max_tokens,
        )
    elif settings.answer_backend == "converse":
        if not (settings.guardrail_id and settings.guardrail_version):
            raise RuntimeError(
                "PHOEBE_GUARDRAIL_ID and PHOEBE_GUARDRAIL_VERSION are required for "
                "the converse backend"
            )
        answer = ConverseAnswerModel(
            settings.answer_model_id,
            settings.aws_region,
            max_tokens=settings.answer_max_tokens,
        )
    else:
        answer = ExtractiveAnswerModel()
    rewriter: Rewriter
    if settings.rewriter_backend == "bedrock":
        rewriter = BedrockRewriter(
            settings.rewrite_model_id,
            settings.aws_region,
            max_tokens=settings.rewrite_max_tokens,
            history_exchanges=settings.history_exchanges,
        )
    else:
        rewriter = HeuristicRewriter()
    guardrail: Guardrail = NoGuardrail()
    if bool(settings.guardrail_id) != bool(settings.guardrail_version):
        raise RuntimeError(
            "PHOEBE_GUARDRAIL_ID and PHOEBE_GUARDRAIL_VERSION must be set together"
        )
    if settings.answer_backend == "harness" and not (
        settings.guardrail_id and settings.guardrail_version
    ):
        raise RuntimeError(
            "PHOEBE_GUARDRAIL_ID and PHOEBE_GUARDRAIL_VERSION are required"
            " for the harness backend"
        )
    if settings.guardrail_id and settings.guardrail_version:
        guardrail = BedrockGuardrail(
            settings.guardrail_id, settings.guardrail_version, settings.aws_region
        )
    return answer, rewriter, guardrail
