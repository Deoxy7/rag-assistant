"""Second-stage ranking: a cross-encoder reads (question, chunk) pairs and re-sorts.

Vector search is a *bi-encoder*: question and chunk are embedded separately
and compared by one dot product, so chunk vectors can be precomputed. A
*cross-encoder* reads question and chunk together through every transformer
layer and outputs one relevance score. That's more accurate (each question
word can attend to each chunk word) but nothing can be precomputed: cost is
one model pass per (question, chunk) pair, so it only runs on the top N of
the first stage.
"""

from dataclasses import dataclass, replace
from functools import lru_cache

import psycopg
import torch
from sentence_transformers import CrossEncoder

from app.config import get_settings
from app.retrieve.types import Filters, Hit


class Reranker:
    """A pinned cross-encoder. score(query, texts) → one float per text, higher = more relevant."""

    def __init__(self, model: str, revision: str, cache_dir, device: str, batch_size: int, max_length: int):
        if device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device, self.batch_size = device, batch_size
        self.key = f"{model}@{revision[:8]}"
        # max_length: pairs longer than this (question + chunk, in this model's
        # tokens) are truncated from the chunk side. 512 is the model's limit.
        self.model = CrossEncoder(model, revision=revision, cache_folder=str(cache_dir), device=device,
                                  max_length=max_length)
        self.pairs_scored = 0

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        self.pairs_scored += len(texts)
        out = self.model.predict([(query, t) for t in texts], batch_size=self.batch_size,
                                 show_progress_bar=False, convert_to_numpy=True)
        return [float(x) for x in out]


def rerank(scorer, query: str, hits: list[Hit]) -> list[Hit]:
    """Re-sort hits by the scorer; ties keep the first-stage order (stable sort)."""
    scores = scorer.score(query, [h.text for h in hits])
    order = sorted(range(len(hits)), key=lambda i: -scores[i])
    return [replace(hits[i], score=scores[i], rank=pos + 1) for pos, i in enumerate(order)]


@dataclass
class RerankingRetriever:
    """Wraps any first-stage retriever: fetch the top n, rerank, return the top k."""

    base: object          # anything with .search(conn, query, k, filters)
    scorer: object        # anything with .score(query, texts)
    n: int = 20

    def search(self, conn: psycopg.Connection, query: str, k: int = 10, filters: Filters | None = None) -> list[Hit]:
        candidates = self.base.search(conn, query, k=max(self.n, k), filters=filters)
        return rerank(self.scorer, query, candidates)[:k]


@lru_cache(maxsize=4)
def get_reranker(model: str | None = None, revision: str | None = None, device: str | None = None) -> Reranker:
    s = get_settings()
    return Reranker(model or s.rerank_model, revision or s.rerank_model_revision, s.model_cache_dir,
                    device or s.rerank_device, s.rerank_batch_size, s.rerank_max_length)


def retriever_from_settings(chunk_set_id: int, embedder=None):
    """The retriever the app uses: retrieval_mode from settings, wrapped in the reranker if enabled."""
    from app.retrieve.hybrid import get_retriever

    s = get_settings()
    base = get_retriever(s.retrieval_mode, chunk_set_id, embedder=embedder)
    if not s.rerank_enabled:
        return base
    return RerankingRetriever(base, get_reranker(), n=s.rerank_n)
