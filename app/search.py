"""Hybrid search core.

Keyword side: BM25 over character bigrams. Bigrams need no tokenizer and
work well for Japanese (the same technique pg_bigm uses), so this runs
anywhere with zero dependencies. Vector side (optional) merges by
Reciprocal Rank Fusion when embeddings are present.

The IDF-weighted coverage score also powers the refusal decision:
out-of-domain questions (「今日の天気は？」) match almost no informative
bigrams, so coverage stays low and the engine declines to answer instead
of hallucinating.
"""

import math
import re
import unicodedata

_WS = re.compile(r"\s+")

# Conversational endings/fillers add noisy bigrams to queries (できますか
# matches every FAQ entry). Stripped from queries only — never from documents.
_QUERY_NOISE = re.compile(
    r"(できますか|できる|ですか|ますか|でしょうか|ください|くださいますか|"
    r"教えて|どうすれば|どうやって|とは|について|何ですか|いいですか)"
)


def normalize(text: str) -> str:
    return _WS.sub("", unicodedata.normalize("NFKC", text).lower())


def terms(text: str) -> list[str]:
    text = normalize(text)
    if not text:
        return []
    if len(text) <= 2:
        return [text]
    return [text[i : i + 2] for i in range(len(text) - 1)]


class SearchIndex:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.doc_terms: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for ch in chunks:
            counts: dict[str, int] = {}
            for t in terms(ch["content"]):
                counts[t] = counts.get(t, 0) + 1
            self.doc_terms.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        n = max(len(chunks), 1)
        self.idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}
        self.unseen_idf = math.log(n + 1.0)
        total_len = sum(sum(c.values()) for c in self.doc_terms)
        self.avgdl = (total_len / n) if chunks else 1.0

    def search(self, query: str, k: int = 8) -> tuple[list[tuple[dict, float]], float]:
        """Return ([(chunk, score)], coverage_of_top_hit)."""
        cleaned = _QUERY_NOISE.sub("", normalize(query)) or normalize(query)
        qterms = set(terms(cleaned))
        if not qterms or not self.chunks:
            return [], 0.0
        k1, b = 1.5, 0.75
        scored: list[tuple[float, float, int]] = []
        for i, counts in enumerate(self.doc_terms):
            dl = sum(counts.values()) or 1
            score = 0.0
            matched_idf = 0.0
            for t in qterms:
                tf = counts.get(t, 0)
                if not tf:
                    continue
                idf = self.idf.get(t, 0.0)
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self.avgdl))
                matched_idf += idf
            if score > 0:
                scored.append((score, matched_idf, i))
        scored.sort(key=lambda r: -r[0])
        if not scored:
            return [], 0.0
        denom = sum(self.idf.get(t, self.unseen_idf) for t in qterms) or 1.0
        coverage = scored[0][1] / denom
        hits = [(self.chunks[i], score) for score, _, i in scored[:k]]
        return hits, coverage


def rrf_merge(
    keyword_hits: list[tuple[dict, float]],
    vector_hits: list[tuple[dict, float]],
    k: int = 8,
    c: int = 60,
) -> list[tuple[dict, float]]:
    """Reciprocal Rank Fusion of two ranked lists (chunks keyed by id)."""
    scores: dict[int, float] = {}
    by_id: dict[int, dict] = {}
    for rank, (chunk, _) in enumerate(keyword_hits):
        scores[chunk["id"]] = scores.get(chunk["id"], 0.0) + 1.0 / (c + rank + 1)
        by_id[chunk["id"]] = chunk
    for rank, (chunk, _) in enumerate(vector_hits):
        scores[chunk["id"]] = scores.get(chunk["id"], 0.0) + 1.0 / (c + rank + 1)
        by_id[chunk["id"]] = chunk
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
    return [(by_id[cid], s) for cid, s in ranked]
