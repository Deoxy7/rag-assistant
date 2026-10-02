"""Phase 7: rank fusion (RRF, weighted) on hand-made lists, and the retriever factory."""

import pytest

from app.retrieve.hybrid import HybridRetriever, get_retriever, rrf, weighted_fusion
from app.retrieve.keyword import KeywordRetriever
from app.retrieve.types import Filters, Hit
from app.retrieve.vector import VectorRetriever


def hit(chunk_id, rank, score=0.0):
    return Hit(chunk_id, "DOC", "Acme", 2022, 1, 1, 0, 10, ("S",), f"chunk {chunk_id}", score=score, rank=rank)


def ids(hits):
    return [h.chunk_id for h in hits]


# The worked example in docs/11-hybrid-rrf.md §6 (chunk ids stand for A–E):
#   vector:  A(1) B(2) C(3) D(4)        keyword: C(1) E(2) B(3)
#   k = 60:  C = 1/63 + 1/61 = 0.032266   B = 1/62 + 1/63 = 0.032002
#            A = 1/61 = 0.016393   E = 1/62 = 0.016129   D = 1/64 = 0.015625
A, B, C, D, E = 1, 2, 3, 4, 5
VECTOR = [hit(A, 1), hit(B, 2), hit(C, 3), hit(D, 4)]
KEYWORD = [hit(C, 1), hit(E, 2), hit(B, 3)]


def test_rrf_matches_the_hand_computed_example():
    fused = rrf([VECTOR, KEYWORD], k=60)
    assert ids(fused) == [C, B, A, E, D]
    assert [round(h.score, 6) for h in fused] == [0.032266, 0.032002, 0.016393, 0.016129, 0.015625]
    assert [h.rank for h in fused] == [1, 2, 3, 4, 5]


def test_k_changes_the_order_in_the_worked_example():
    # k = 0: A = 1/1 = 1.0 beats B = 1/2 + 1/3 = 0.833 — a single top rank now outweighs agreement.
    assert ids(rrf([VECTOR, KEYWORD], k=0)) == [C, A, B, E, D]


def test_ties_are_broken_by_best_single_rank_then_chunk_id():
    # Both lists put a different chunk first: 1/61 each, same best rank → lower chunk id wins.
    fused = rrf([[hit(9, 1)], [hit(4, 1)]], k=60)
    assert ids(fused) == [4, 9]


def test_rrf_rewards_agreement_over_one_top_rank():
    # X is 1st in one list only; Y is 2nd in both. 1/61 = 0.01639 < 2/62 = 0.03226.
    fused = rrf([[hit(10, 1), hit(20, 2)], [hit(30, 1), hit(20, 2)]], k=60)
    assert fused[0].chunk_id == 20


def test_small_k_lets_a_single_top_rank_win():
    # Same lists with k = 0: X = 1/1 = 1.0 and Y = 1/2 + 1/2 = 1.0 tie; the tie
    # rule (best single rank: X 1, Y 2) puts both single-list winners first.
    fused = rrf([[hit(10, 1), hit(20, 2)], [hit(30, 1), hit(20, 2)]], k=0)
    assert ids(fused) == [10, 30, 20]


def test_rrf_ignores_raw_scores():
    a = rrf([[hit(1, 1, score=0.9), hit(2, 2, score=0.1)]])
    b = rrf([[hit(1, 1, score=1e6), hit(2, 2, score=1e-6)]])
    assert [h.score for h in a] == [h.score for h in b]


def test_rrf_of_one_list_keeps_its_order_and_empty_lists_are_fine():
    assert ids(rrf([VECTOR])) == [A, B, C, D]
    assert ids(rrf([VECTOR, []])) == [A, B, C, D]
    assert rrf([[], []]) == []


def test_weighted_fusion_min_max_normalises_each_list():
    vec = [hit(1, 1, 0.80), hit(2, 2, 0.70), hit(3, 3, 0.60)]     # → 1.0, 0.5, 0.0
    kw = [hit(3, 1, 17.0), hit(4, 2, 2.0)]                          # → 1.0, 0.0
    fused = weighted_fusion([vec, kw], [0.5, 0.5])
    scores = {h.chunk_id: h.score for h in fused}
    assert scores == pytest.approx({1: 0.5, 2: 0.25, 3: 0.5, 4: 0.0})
    assert ids(fused) == [1, 3, 2, 4]    # 1 and 3 tie at 0.5 → chunk id


def test_weighted_fusion_single_hit_list_counts_as_its_best():
    # Regression: (s - lo) / ((hi - lo) or 1) gave a one-hit list 0.0, so a rare
    # figure that keyword search found exactly once contributed nothing.
    fused = weighted_fusion([[hit(7, 1, 0.3)], [hit(8, 1, 0.9), hit(9, 2, 0.1)]], [0.7, 0.3])
    assert {h.chunk_id: h.score for h in fused} == pytest.approx({7: 0.7, 8: 0.3, 9: 0.0})


class FakeRetriever:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def search(self, conn, query, k=10, filters=None):
        self.calls.append((query, k, filters))
        return self.hits[:k]


def test_hybrid_retriever_asks_both_at_depth_and_returns_top_k():
    vec, kw = FakeRetriever(VECTOR), FakeRetriever(KEYWORD)
    f = Filters(companies=("Acme",))
    hits = HybridRetriever(vec, kw, rrf_k=60, depth=50).search(None, "q", k=2, filters=f)
    assert ids(hits) == [C, B]
    assert vec.calls == [("q", 50, f)] and kw.calls == [("q", 50, f)]


def test_get_retriever_builds_each_mode():
    class E:
        key, dims = "fake@0", 4
    assert isinstance(get_retriever("vector", 1, embedder=E()), VectorRetriever)
    assert isinstance(get_retriever("keyword", 1, rank_function="bm25"), KeywordRetriever)
    h = get_retriever("hybrid", 1, embedder=E(), rrf_k=10, depth=20, ef_search=40)
    assert (h.rrf_k, h.depth, h.vector.ef_search) == (10, 20, 40)


def test_get_retriever_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown retrieval mode"):
        get_retriever("semantic", 1)
