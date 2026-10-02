"""Hybrid retrieval: fuse the vector and keyword rankings into one list.

RRF (Reciprocal Rank Fusion, Cormack et al., 2009) uses only *ranks*:

    score(d) = Σ over lists L containing d of 1 / (k + rank_L(d))

so it never compares a cosine similarity (0.7–0.8) with a ts_rank (0.01–0.6)
or a BM25 score (2–17) — numbers on unrelated scales. k (default 60, the
paper's value) controls how much the top ranks dominate: small k → rank 1 is
worth far more than rank 10; large k → ranks count almost equally.

weighted_fusion() is the classic alternative (normalise each list's scores to
0–1, then a weighted sum), kept for the comparison in scripts/bench_hybrid.py.
"""

from dataclasses import dataclass, replace

import psycopg

from app.config import get_settings
from app.retrieve.keyword import KeywordRetriever
from app.retrieve.types import Filters, Hit
from app.retrieve.vector import VectorRetriever

MODES = ("vector", "keyword", "hybrid")


def rrf(ranked_lists: list[list[Hit]], k: int = 60) -> list[Hit]:
    """Fuse ranked lists by reciprocal rank. Ties broken by best single rank, then chunk id."""
    scores: dict[int, float] = {}
    best: dict[int, Hit] = {}
    best_rank: dict[int, int] = {}
    for hits in ranked_lists:
        for h in hits:
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (k + h.rank)
            if h.chunk_id not in best or h.rank < best_rank[h.chunk_id]:
                best[h.chunk_id], best_rank[h.chunk_id] = h, h.rank
    order = sorted(scores, key=lambda cid: (-scores[cid], best_rank[cid], cid))
    return [replace(best[cid], score=scores[cid], rank=i + 1) for i, cid in enumerate(order)]


def weighted_fusion(ranked_lists: list[list[Hit]], weights: list[float]) -> list[Hit]:
    """Min-max normalise each list's scores to [0, 1], then sum with weights.

    A chunk missing from a list contributes 0 from it. If every hit in a list has
    the same score (including a list of one), they all count as 1.0 — the list's
    best. The normalisation is the weak point: the best hit of a list always
    becomes 1.0 and its worst 0.0, however good or bad they were in absolute terms.
    """
    totals: dict[int, float] = {}
    first: dict[int, Hit] = {}
    for hits, w in zip(ranked_lists, weights):
        if not hits:
            continue
        lo, hi = min(h.score for h in hits), max(h.score for h in hits)
        for h in hits:
            norm = (h.score - lo) / (hi - lo) if hi > lo else 1.0
            totals[h.chunk_id] = totals.get(h.chunk_id, 0.0) + w * norm
            first.setdefault(h.chunk_id, h)
    order = sorted(totals, key=lambda cid: (-totals[cid], cid))
    return [replace(first[cid], score=totals[cid], rank=i + 1) for i, cid in enumerate(order)]


@dataclass
class HybridRetriever:
    vector: object            # anything with .search(conn, query, k, filters)
    keyword: object
    rrf_k: int = 60
    depth: int = 50           # how many results to take from each retriever before fusing

    def search(self, conn: psycopg.Connection, query: str, k: int = 10, filters: Filters | None = None) -> list[Hit]:
        lists = [self.vector.search(conn, query, k=self.depth, filters=filters),
                 self.keyword.search(conn, query, k=self.depth, filters=filters)]
        return rrf(lists, k=self.rrf_k)[:k]


def get_retriever(mode: str, chunk_set_id: int, embedder=None, **options):
    """Factory: the configured retrieval mode becomes a retriever object.

    options: ef_search, filter_mode (vector), rank_function (keyword),
    rrf_k, depth (hybrid).
    """
    if mode not in MODES:
        raise ValueError(f"unknown retrieval mode {mode!r}; choose from {MODES}")
    if mode in ("vector", "hybrid") and embedder is None:
        from app.embed.embedder import get_embedder
        embedder = get_embedder()
    vec_opts = {k: options[k] for k in ("ef_search", "filter_mode") if k in options}
    kw_opts = {k: options[k] for k in ("rank_function",) if k in options}
    if mode == "vector":
        return VectorRetriever(embedder, chunk_set_id, **vec_opts)
    if mode == "keyword":
        return KeywordRetriever(chunk_set_id, **kw_opts)
    s = get_settings()
    return HybridRetriever(VectorRetriever(embedder, chunk_set_id, **vec_opts), KeywordRetriever(chunk_set_id, **kw_opts),
                           rrf_k=options.get("rrf_k", s.rrf_k), depth=options.get("depth", s.retrieval_depth))
