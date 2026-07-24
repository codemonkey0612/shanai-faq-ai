"""Optional vector embeddings via any OpenAI-compatible API.

Disabled by default (EMBEDDINGS_ENABLED=0). Keyword search alone performs
well for regulation-style documents; enable this once an API key exists
to improve recall on paraphrased questions. Failures fall back silently
to keyword-only search — vectors are an enhancement, never a dependency.
"""

import json
import math
import struct
import urllib.request

from . import config


def available() -> bool:
    return config.EMBEDDINGS_ENABLED and bool(config.OPENAI_API_KEY)


def embed(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        f"{config.OPENAI_BASE_URL}/embeddings",
        data=json.dumps({"model": config.EMBEDDING_MODEL, "input": texts}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def vector_hits(chunks: list[dict], query_vec: list[float], k: int = 8) -> list[tuple[dict, float]]:
    scored = []
    for ch in chunks:
        if ch.get("embedding"):
            scored.append((ch, cosine(unpack(ch["embedding"]), query_vec)))
    scored.sort(key=lambda t: -t[1])
    return scored[:k]
