"""The answer pipeline: retrieve → pack → generate → check citations (or refuse).

Refusal happens in two places:

1. Before calling the model, when retrieval returns nothing that fits the
   context: there is nothing to ground an answer in, so no tokens are spent.
2. When the model replies with REFUSAL_TOKEN, as the instructions tell it to
   when the sources don't contain the answer.

A score threshold (refuse when the best reranker score is low) is a third,
common option; it needs calibration on the golden set's unanswerable questions,
so it waits for Phase 11 (Settings has no threshold until then, on purpose).
"""

import re
import time
from dataclasses import dataclass, field

import psycopg

from app.config import get_settings
from app.generate.citations import MARKER, CitationReport, check_citations, normalize_markers, strip_invalid_markers
from app.generate.guard import StreamingOutputFilter, enforce_output_policy, injection_signals
from app.generate.prompt import REFUSAL_TOKEN, PackedContext, build_user_message, instructions, pack_context
from app.retrieve.types import Filters, Hit
from app.telemetry.cost import Price, cost
from app.telemetry.trace import Trace, activate, stage

REFUSAL_MESSAGE = ("I can't answer that from the indexed filings: the retrieved passages don't contain "
                   "the information needed.")


@dataclass
class Answer:
    question: str
    text: str                       # what the user sees (invalid markers removed; refusal message if refused)
    refused: bool
    refusal_reason: str | None      # "no_context" | "model" | None
    context: PackedContext
    report: CitationReport | None
    raw_model_text: str | None
    model: str | None = None
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False
    truncated: bool = False         # the model hit its output-token cap (finish_reason "length")
    timings_ms: dict = field(default_factory=dict)
    counters: dict = field(default_factory=dict)       # e.g. rerank_pairs, query_embedding_cache_hit
    list_usd: float = 0.0           # this call at the provider's paid list price (0 if cached)
    billed_usd: float = 0.0         # what was actually billed (0 on a free tier, or if cached)

    @property
    def prompt(self) -> tuple[str, str]:
        return instructions(self.context.template), build_user_message(self.question, self.context)


TOKEN_ANYWHERE = re.compile(rf"(?<![A-Za-z0-9_]){REFUSAL_TOKEN}(?![A-Za-z0-9_])", re.I)


def is_refusal(text: str) -> bool:
    """True if the model refused.

    The instruction is "reply with exactly INSUFFICIENT_CONTEXT", but measured on the full eval
    (qwen3.8-27b, 2026-10-03) the model also explained first and appended the token, or wrapped it
    in brackets: 4 of 61 RAG answers and 4 of 61 closed-book answers (T-055). So the token
    anywhere, as a whole word, in a response that cites no source is a refusal. A response with
    real [n] citations and a stray token is treated as an answer (the token is removed for display).
    """
    if not TOKEN_ANYWHERE.search(text):
        return False
    return not MARKER.search(normalize_markers(TOKEN_ANYWHERE.sub("", text)))


def generator_price() -> Price:
    s = get_settings()
    return Price(s.llm_price_input_per_m, s.llm_price_output_per_m, s.llm_free_tier)


def finish(question: str, context: PackedContext, raw: str, timings: dict, llm_result=None,
           counters: dict | None = None) -> Answer:
    meta = {"counters": dict(counters or {})}
    if llm_result is not None:
        # Rate-limit / 5xx waits are part of "generate" and "first_token"; report them separately
        # so model latency and quota throttling aren't confused (Phase 13: free-tier 8k TPM).
        if getattr(llm_result, "retries", 0):
            timings["llm.retry_wait"] = llm_result.retry_wait_ms
            meta["counters"]["llm_retries"] = llm_result.retries
        c = cost(llm_result.input_tokens, llm_result.output_tokens, generator_price(), llm_result.cached)
        meta.update(model=llm_result.model, provider=llm_result.provider, input_tokens=llm_result.input_tokens,
                    output_tokens=llm_result.output_tokens, cached=llm_result.cached,
                    truncated=getattr(llm_result, "truncated", False), list_usd=c.list_usd, billed_usd=c.billed_usd)
    if is_refusal(raw):
        return Answer(question, REFUSAL_MESSAGE, True, "model", context, None, raw, timings_ms=timings, **meta)
    shown = normalize_markers(TOKEN_ANYWHERE.sub("", raw).strip())   # stray token removed; 【1】 → [1]
    if get_settings().output_policy:
        check = enforce_output_policy(shown)              # no links or images (Phase 14)
        shown = check.text
        for name, n in (("output_images_removed", check.images_removed), ("output_links_removed", check.links_removed)):
            if n:
                meta["counters"][name] = n
    report = check_citations(shown, context.sources)
    return Answer(question, strip_invalid_markers(shown, context.sources), False, None, context, report, raw,
                  timings_ms=timings, **meta)


def retrieve_and_pack(conn, question: str, retriever, k: int, filters: Filters | None, budget: int,
                      timings: dict, trace: Trace | None = None) -> PackedContext:
    """Retrieve, screen for injected instructions, and pack, with every stage timed into `trace`
    (retrieve.vector, retrieve.keyword, retrieve.fuse, rerank, pack, …): the retrievers time
    themselves via the active trace."""
    s = get_settings()
    trace = trace or Trace()
    with activate(trace):
        t0 = time.perf_counter()
        hits: list[Hit] = retriever.search(conn, question, k=k, filters=filters)
        timings["retrieve"] = (time.perf_counter() - t0) * 1000
        with stage("pack"):
            hits, quarantined = screen(hits, s.injection_filter)
            context = pack_context(hits, budget, s.context_order, s.prompt_template, quarantined)
    if quarantined:
        trace.count("sources_quarantined", len(quarantined))
    if context.defused:
        trace.count("source_text_defused", context.defused)
    timings.update(trace.timings_ms)
    return context


def screen(hits: list[Hit], mode: str) -> tuple[list[Hit], tuple]:
    """Split hits into (kept, quarantined) by guard.injection_signals.

    "drop" keeps flagged sources out of the prompt; "flag" keeps them in but reports
    them; "off" skips the check. Measured false positives: 0 of 69,176 chunks.
    """
    if mode == "off":
        return hits, ()
    flagged = [(h, tuple(sig)) for h in hits if (sig := injection_signals(h.text))]
    if mode == "flag" or not flagged:
        return hits, tuple(flagged)
    bad = {id(h) for h, _ in flagged}
    return [h for h in hits if id(h) not in bad], tuple(flagged)


def answer_question(conn: psycopg.Connection, question: str, retriever, llm, filters: Filters | None = None,
                    k: int | None = None, budget: int | None = None) -> Answer:
    s = get_settings()
    timings: dict = {}
    tr = Trace()
    context = retrieve_and_pack(conn, question, retriever, k or s.answer_top_k, filters,
                                budget or s.context_token_budget, timings, tr)
    if not context.sources:
        return Answer(question, REFUSAL_MESSAGE, True, "no_context", context, None, None, timings_ms=timings,
                      counters=tr.counters)
    t0 = time.perf_counter()
    result = llm.generate(instructions(context.template), build_user_message(question, context))
    timings["generate"] = (time.perf_counter() - t0) * 1000
    return finish(question, context, result.text, timings, result, tr.counters)


def stream_answer(conn: psycopg.Connection, question: str, retriever, llm, filters: Filters | None = None,
                  k: int | None = None, budget: int | None = None):
    """Yields ("sources", PackedContext), then ("delta", text)…, then ("answer", Answer).

    Deltas are the model's raw text, so a REFUSAL_TOKEN can stream before the
    final Answer replaces it with the refusal message; Phase 10's API buffers
    until the first characters prove it isn't a refusal.
    """
    s = get_settings()
    timings: dict = {}
    tr = Trace()
    context = retrieve_and_pack(conn, question, retriever, k or s.answer_top_k, filters,
                                budget or s.context_token_budget, timings, tr)
    yield "sources", context
    if not context.sources:
        yield "answer", Answer(question, REFUSAL_MESSAGE, True, "no_context", context, None, None, timings_ms=timings,
                               counters=tr.counters)
        return
    t0 = time.perf_counter()
    first, parts = None, []
    # Deltas pass through the output policy too: a markdown image rendered mid-stream would
    # already have fetched its URL before the cleaned final answer arrived.
    guard = StreamingOutputFilter() if s.output_policy else None
    for delta in llm.stream(instructions(context.template), build_user_message(question, context)):
        if first is None:
            first = time.perf_counter()
            timings["first_token"] = (first - t0) * 1000
        parts.append(delta)
        out = guard.feed(delta) if guard else delta
        if out:
            yield "delta", out
    if guard and (rest := guard.flush()):
        yield "delta", rest
    timings["generate"] = (time.perf_counter() - t0) * 1000
    yield "answer", finish(question, context, "".join(parts), timings, llm.last_result, tr.counters)
