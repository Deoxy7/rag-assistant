"""Uncertainty for small samples: percentile bootstrap and the paired sign test."""

import math
import random


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_ci(xs: list[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 7) -> tuple[float, float]:
    """95% percentile bootstrap CI of the mean: resample the questions with replacement."""
    if not xs:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(mean([xs[rng.randrange(len(xs))] for _ in xs]) for _ in range(n_boot))
    return means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1]


def sign_test(a: list[float], b: list[float]) -> tuple[int, int, float]:
    """Paired, two-sided: (#a better, #b better, p). Ties are dropped."""
    wins = sum(x > y for x, y in zip(a, b))
    losses = sum(x < y for x, y in zip(a, b))
    n = wins + losses
    if n == 0:
        return 0, 0, 1.0
    k = max(wins, losses)
    p = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return wins, losses, min(1.0, 2 * p)
