"""AI adapters: answer model, query rewriter, guardrail.

All request parameters are server-owned. Offline defaults need no AWS. Errors
carry no provider text; nothing here logs question or answer text.
"""

import html
import re
from collections.abc import Generator, Iterator, Sequence
from typing import Any, Literal, Protocol, TypedDict
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.config import Settings

Message = TypedDict("Message", {"role": Literal["user", "assistant"], "text": str})

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
        except BotoCoreError, ClientError, KeyError, TypeError:
            raise ModelUnavailable("model request failed") from None
        completed = False
        try:
            for event in events:
                if any(key in event for key in _STREAM_ERRORS):
                    raise ModelUnavailable("model stream error") from None
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
                    if stop.get("stopReason") != "end_turn":
                        raise ModelUnavailable("incomplete answer") from None
                    completed = True
        except BotoCoreError, ClientError:
            raise ModelUnavailable("model stream failed") from None
        finally:
            events.close()
        if not completed:
            raise ModelUnavailable("stream ended early")


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
        except Exception:  # noqa: BLE001 - any failure uses the heuristic
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
        except Exception:  # noqa: BLE001 - nothing chained: may echo text
            raise ModelUnavailable("guardrail request failed") from None


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
