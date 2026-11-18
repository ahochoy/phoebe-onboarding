"""Eval-only answer model: Bedrock ConverseStream with the production prompt.

Candidates are not behind an AgentCore harness, so this sends what the harness
would: the system prompt baked into the harness (backend/prompts/answer.txt),
the messages the app builds, temperature 0.1 and the app's max_tokens. Close to
production, not byte-identical; a winner is confirmed through a real harness.
"""

from collections.abc import Generator, Sequence
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from phoebe.chat.models import (
    Message,
    ModelUnavailable,
    _client,  # pyright: ignore[reportPrivateUsage]
    _error_kind,  # pyright: ignore[reportPrivateUsage]
    _unavailable,  # pyright: ignore[reportPrivateUsage]
)
from phoebe.chat.prompt import ANSWER_PROMPT_PATH

TEMPERATURE = 0.1  # the harness setting (infra/ai/main.tf)

# Error events ConverseStream can put in the stream instead of raising.
_STREAM_ERRORS = (
    "internalServerException",
    "modelStreamErrorException",
    "validationException",
    "throttlingException",
    "serviceUnavailableException",
)


class ModelUnsupported(ModelUnavailable):
    """The model rejects the request shape (for example a system block or
    streaming). The eval reports the model as unsupported instead of failing."""


class ConverseAnswerModel:
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
            response = self._client.converse_stream(
                modelId=self._model_id,
                system=[{"text": self._system}],
                messages=[
                    {"role": m["role"], "content": [{"text": m["text"]}]}
                    for m in messages
                ],
                inferenceConfig={
                    "maxTokens": self._max_tokens,
                    **(
                        {}
                        if self._temperature is None
                        else {"temperature": self._temperature}
                    ),
                },
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
                errors = [key for key in _STREAM_ERRORS if key in event]
                if errors:
                    raise _unavailable("model stream error", errors[0]) from None
                delta = event.get("contentBlockDelta", {}).get("delta", {})
                # Reasoning models stream their thinking separately; only text
                # reaches the answer, as with the harness.
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
