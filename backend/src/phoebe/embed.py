"""Deterministic local embedder (hashing trick); no model or network needed."""

import math
import re
from collections.abc import Sequence
from hashlib import blake2b
from typing import Protocol

EMBED_DIM = 1024
_TOKEN = re.compile(r"\w+")


def vector_literal(vec: Sequence[float]) -> str:
    """pgvector text literal for `vec` (cast with `::vector` in SQL)."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbedder:
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
