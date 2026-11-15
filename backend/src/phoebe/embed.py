"""Deterministic local embedder (hashing trick); no model or network needed."""

import json
import math
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from hashlib import blake2b
from typing import Any, Protocol

EMBED_DIM = 1024
_TOKEN = re.compile(r"\w+")


def vector_literal(vec: Sequence[float]) -> str:
    """pgvector text literal for `vec` (cast with `::vector` in SQL)."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


class Embedder(Protocol):
    id: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbedder:
    id = "hash-v1-1024"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * EMBED_DIM
        for token in _TOKEN.findall(text.lower()):
            h = int.from_bytes(blake2b(token.encode(), digest_size=8).digest(), "big")
            vec[h % EMBED_DIM] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]


class EmbeddingUnavailable(Exception):
    """The embedding service failed; carries no provider or document text."""


_TITAN_MODEL = "amazon.titan-embed-text-v2:0"
_TITAN_MAX_CHARS = 30000


class TitanEmbedder:
    id = "titan-v2-1024"

    def __init__(
        self,
        client: Any = None,
        region: str = "us-east-2",
        max_workers: int = 4,
    ) -> None:
        self._client = client
        self._region = region
        self._max_workers = max_workers

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
                config=Config(
                    connect_timeout=5,
                    read_timeout=30,
                    retries={"total_max_attempts": 3, "mode": "standard"},
                ),
            )
        return self._client

    def _one(self, text: str) -> list[float]:
        body = json.dumps(
            {
                "inputText": text[:_TITAN_MAX_CHARS],
                "dimensions": EMBED_DIM,
                "normalize": True,
            }
        )
        try:
            resp = self._bedrock().invoke_model(
                modelId=_TITAN_MODEL,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            vec = json.loads(resp["body"].read())["embedding"]
        except Exception:  # noqa: BLE001 - any failure is a clean outage
            # Nothing chained: provider messages may echo the input text.
            raise EmbeddingUnavailable("embedding request failed") from None
        if not isinstance(vec, list) or len(vec) != EMBED_DIM:
            raise EmbeddingUnavailable("unexpected embedding dimension")
        return [float(x) for x in vec]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            return list(pool.map(self._one, texts))


class EmbedderSettings(Protocol):
    @property
    def embedder(self) -> str: ...

    @property
    def aws_region(self) -> str: ...


def make_embedder(settings: EmbedderSettings) -> Embedder:
    if settings.embedder == "titan":
        return TitanEmbedder(region=settings.aws_region)
    return HashEmbedder()
