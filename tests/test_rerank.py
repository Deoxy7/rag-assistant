"""Phase 8: reranking — the re-sort logic with a fake scorer, and the real pinned cross-encoder."""

import pytest

from app.retrieve.hybrid import HybridRetriever
from app.retrieve.rerank import RerankingRetriever, get_reranker, rerank, retriever_from_settings
from app.retrieve.types import Hit


def hit(chunk_id, rank, text):
    return Hit(chunk_id, "DOC", "Acme", 2022, 1, 1, 0, len(text), ("S",), text, score=1.0 / rank, rank=rank)


class LengthScorer:
    """Fake cross-encoder: longer text = more relevant. Records what it was asked."""

    def __init__(self):
        self.calls = []

    def score(self, query, texts):
        self.calls.append((query, list(texts)))
        return [float(len(t)) for t in texts]


HITS = [hit(1, 1, "aa"), hit(2, 2, "aaaa"), hit(3, 3, "a"), hit(4, 4, "aaa")]


def test_rerank_resorts_by_scorer_and_renumbers():
    out = rerank(LengthScorer(), "q", HITS)
    assert [h.chunk_id for h in out] == [2, 4, 1, 3]
    assert [h.rank for h in out] == [1, 2, 3, 4]
    assert [h.score for h in out] == [4.0, 3.0, 2.0, 1.0]
    assert out[0].page_number == HITS[1].page_number      # citation fields survive


def test_rerank_ties_keep_first_stage_order():
    class Flat:
        def score(self, q, texts):
            return [0.0] * len(texts)
    assert [h.chunk_id for h in rerank(Flat(), "q", HITS)] == [1, 2, 3, 4]


def test_rerank_of_nothing_is_nothing():
    assert rerank(LengthScorer(), "q", []) == []


class FakeBase:
    def __init__(self):
        self.calls = []

    def search(self, conn, query, k=10, filters=None):
        self.calls.append(k)
        return HITS[:k]


def test_reranking_retriever_fetches_n_and_returns_k():
    base, scorer = FakeBase(), LengthScorer()
    out = RerankingRetriever(base, scorer, n=3).search(None, "q", k=2)
    assert base.calls == [3]                                # asked the first stage for N
    assert scorer.calls == [("q", ["aa", "aaaa", "a"])]     # scored only those N
    assert [h.chunk_id for h in out] == [2, 1]              # best 2 of the 3


def test_reranking_retriever_never_fetches_fewer_than_k():
    base = FakeBase()
    RerankingRetriever(base, LengthScorer(), n=2).search(None, "q", k=4)
    assert base.calls == [4]


class FakeEmbedder:
    key, dims = "fake@0", 4


def test_settings_switch_turns_reranking_on_and_off(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "rerank_enabled", False)
    assert isinstance(retriever_from_settings(1, embedder=FakeEmbedder()), HybridRetriever)
    monkeypatch.setattr(s, "rerank_enabled", True)
    monkeypatch.setattr(s, "rerank_n", 7)
    r = retriever_from_settings(1, embedder=FakeEmbedder())
    assert isinstance(r, RerankingRetriever) and isinstance(r.base, HybridRetriever) and r.n == 7


@pytest.fixture(scope="module")
def cross_encoder():
    return get_reranker()


def test_real_cross_encoder_prefers_the_answering_passage(cross_encoder):
    q = "What was AMD's net revenue in 2021?"
    s = cross_encoder.score(q, ["AMD net revenue for 2021 was $16.4 billion, an increase of 68%.",
                                "The cafeteria serves lunch at noon.",
                                "Corning net sales were $14.1 billion in 2021."])
    assert s[0] > s[2] > s[1]


def test_real_cross_encoder_is_deterministic_and_batch_independent(cross_encoder):
    q = "goodwill impairment"
    texts = [f"Note {i}: goodwill impairment testing of reporting unit {i}." for i in range(6)]
    together = cross_encoder.score(q, texts)
    alone = [cross_encoder.score(q, [t])[0] for t in texts]
    assert max(abs(a - b) for a, b in zip(together, alone)) < 1e-3
