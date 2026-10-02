"""Abstention: does the system refuse exactly when the corpus can't answer?

Treat "refuse" as the positive class. Over answerable (A) and unanswerable (U)
questions:

    abstention precision  = refused ∧ U  /  refused            (refusals that were right)
    abstention recall     = refused ∧ U  /  U                  (unanswerables caught)
    false-refusal rate    = refused ∧ A  /  A                  (answerable questions refused)
    false-answer rate     = answered ∧ U /  U  = 1 − recall    (confident answers to the unanswerable)

A retrieval-only policy ("refuse when the best reranker score < t") can be
scored without any LLM: sweep t, and summarise the separation with AUROC, the
probability that a random answerable question scores above a random
unanswerable one (ties count ½).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AbstentionScores:
    n_answerable: int
    n_unanswerable: int
    precision: float | None
    recall: float | None
    false_refusal_rate: float | None
    false_answer_rate: float | None


def abstention(refused: list[bool], answerable: list[bool]) -> AbstentionScores:
    a = [r for r, ok in zip(refused, answerable) if ok]
    u = [r for r, ok in zip(refused, answerable) if not ok]
    n_ref = sum(refused)
    tp = sum(u)
    div = lambda x, y: x / y if y else None  # noqa: E731
    return AbstentionScores(len(a), len(u), div(tp, n_ref), div(tp, len(u)), div(sum(a), len(a)),
                            div(len(u) - tp, len(u)))


def auroc(pos_scores: list[float], neg_scores: list[float]) -> float:
    """P(score of a random positive > score of a random negative); ties count ½. O(P·N), fine for tens."""
    if not pos_scores or not neg_scores:
        raise ValueError("need both classes")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos_scores for n in neg_scores)
    return wins / (len(pos_scores) * len(neg_scores))


def threshold_sweep(answerable_scores: list[float], unanswerable_scores: list[float]):
    """For each candidate threshold t (refuse if score < t): (t, false_refusal_rate, abstention_recall, accuracy)."""
    cands = sorted(set(answerable_scores) | set(unanswerable_scores)) + [float("inf")]
    n = len(answerable_scores) + len(unanswerable_scores)
    out = []
    for t in cands:
        fr = sum(s < t for s in answerable_scores) / len(answerable_scores)
        rec = sum(s < t for s in unanswerable_scores) / len(unanswerable_scores)
        acc = (sum(s >= t for s in answerable_scores) + sum(s < t for s in unanswerable_scores)) / n
        out.append((t, fr, rec, acc))
    return out
