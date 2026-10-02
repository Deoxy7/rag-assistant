"""Retrieval metrics against evidence spans.

Relevance of a retrieved chunk to one evidence item is graded by how much of
the quote the chunk contains (max over the item's occurrences):

    grade 2  the chunk contains the whole quote
    grade 1  it contains at least half of it (the quote straddles a chunk boundary)
    grade 0  otherwise

A chunk's grade is its best grade over all items. An item is *covered* by a
ranked list at k if some chunk in the top k has grade ≥ 1 for it.

For a question with items I and a ranked list r₁…r_n:

    hit@k        1 if any of the top k has grade ≥ 1, else 0
    recall@k     |items covered in the top k| / |I|
    precision@k  |top-k chunks with grade ≥ 1| / k
    RR           1 / rank of the first chunk with grade ≥ 1 (0 if none in the list)
    nDCG@k       DCG@k / IDCG@k,  DCG@k = Σ_{i≤k} (2^{g_i} − 1) / log2(i + 1)
                 IDCG@k = the same sum over the best possible ordering of all
                 relevant chunks in the chunk set (not just the retrieved ones).
"""

import math
from dataclasses import dataclass

GRADE_FULL, GRADE_PARTIAL = 2, 1


@dataclass(frozen=True)
class ChunkRef:
    chunk_id: int
    doc_key: str
    char_start: int
    char_end: int


def span_grade(chunk: ChunkRef, span) -> int:
    if chunk.doc_key != span.doc_key:
        return 0
    overlap = min(chunk.char_end, span.char_end) - max(chunk.char_start, span.char_start)
    if overlap <= 0:
        return 0
    length = span.char_end - span.char_start
    if overlap >= length:
        return GRADE_FULL
    return GRADE_PARTIAL if overlap * 2 >= length else 0


def item_grade(chunk: ChunkRef, item) -> int:
    return max((span_grade(chunk, s) for s in item), default=0)


def chunk_grade(chunk: ChunkRef, items) -> int:
    return max((item_grade(chunk, it) for it in items), default=0)


def dcg(grades: list[int]) -> float:
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


@dataclass(frozen=True)
class RetrievalScores:
    hit: float
    recall: float
    precision: float
    rr: float
    ndcg: float
    first_rank: int | None


def score(ranked: list[ChunkRef], items, k: int, ideal_grades: list[int]) -> RetrievalScores:
    """Metrics at k for one answerable question. `ideal_grades`: grades of every relevant chunk in the chunk set."""
    grades = [chunk_grade(c, items) for c in ranked]
    top = ranked[:k]
    covered = sum(any(item_grade(c, it) >= GRADE_PARTIAL for c in top) for it in items)
    first = next((i + 1 for i, g in enumerate(grades) if g >= GRADE_PARTIAL), None)
    idcg = dcg(sorted(ideal_grades, reverse=True)[:k])
    return RetrievalScores(
        hit=float(any(g >= GRADE_PARTIAL for g in grades[:k])),
        recall=covered / len(items),
        precision=sum(g >= GRADE_PARTIAL for g in grades[:k]) / k,
        rr=1.0 / first if first else 0.0,
        ndcg=dcg(grades[:k]) / idcg if idcg > 0 else 0.0,
        first_rank=first)


def context_precision(ranked: list[ChunkRef], items) -> float:
    """Rank-aware share of the retrieved context that is evidence, from the labels:
    average of precision@i over the positions i holding a relevant chunk (grade ≥ 1); 0 if none.
    The label-based twin of the LLM-judged context precision (metrics/judge.py)."""
    hits, total = 0, 0.0
    for i, c in enumerate(ranked, start=1):
        if chunk_grade(c, items) >= GRADE_PARTIAL:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0
