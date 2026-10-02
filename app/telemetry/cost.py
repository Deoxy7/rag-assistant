"""Token cost accounting: what a call cost (billed) and what it would cost at paid list prices.

Two numbers because they answer different questions. "Billed" is what this
deployment pays (0 on a free tier). "List" is what the same traffic would cost
on the provider's paid tier: the number to plan with when the free tier runs out.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_m: float      # USD per 1M input tokens, paid list price
    output_per_m: float
    free_tier: bool         # True: billed cost is 0 (but rate-limited)


@dataclass(frozen=True)
class Cost:
    input_tokens: int
    output_tokens: int
    list_usd: float
    billed_usd: float


def cost(input_tokens: int, output_tokens: int, price: Price, cached: bool = False) -> Cost:
    """A cache hit made no API call, so it costs nothing on either measure."""
    if cached:
        return Cost(input_tokens, output_tokens, 0.0, 0.0)
    list_usd = input_tokens / 1e6 * price.input_per_m + output_tokens / 1e6 * price.output_per_m
    return Cost(input_tokens, output_tokens, round(list_usd, 8), 0.0 if price.free_tier else round(list_usd, 8))
