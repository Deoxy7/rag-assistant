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

import time
from dataclasses import dataclass, field

import psycopg

from app.config import get_settings
from app.generate.citations import CitationReport, check_citations, strip_invalid_markers
from app.generate.prompt import INSTRUCTIONS, REFUSAL_TOKEN, PackedContext, build_user_message, pack_context
from app.retrieve.types import Filters, Hit

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

    @property
    def prompt(self) -> tuple[str, str]:
        return INSTRUCTIONS, build_user_message(self.question, self.context)


def is_refusal(text: str) -> bool:
    # Models sometimes wrap the token in punctuation or add a period.
    return text.strip().strip(".`'\" ").upper() == REFUSAL_TOKEN


def finish(question: str, context: PackedContext, raw: str, timings: dict, llm_result=None) -> Answer:
    meta = {}
    if llm_result is not None:
        meta = dict(model=llm_result.model, provider=llm_result.provider, input_tokens=llm_result.input_tokens,
                    output_tokens=llm_result.output_tokens, cached=llm_result.cached,
                    truncated=getattr(llm_result, "truncated", False))
    if is_refusal(raw):
        return Answer(question, REFUSAL_MESSAGE, True, "model", context, None, raw, timings_ms=timings, **meta)
    report = check_citations(raw, context.sources)
    return Answer(question, strip_invalid_markers(raw, context.sources), False, None, context, report, raw,
                  timings_ms=timings, **meta)


def retrieve_and_pack(conn, question: str, retriever, k: int, filters: Filters | None, budget: int,
                      timings: dict) -> PackedContext:
    t0 = time.perf_counter()
    hits: list[Hit] = retriever.search(conn, question, k=k, filters=filters)
    timings["retrieve"] = (time.perf_counter() - t0) * 1000
    return pack_context(hits, budget, get_settings().context_order)


def answer_question(conn: psycopg.Connection, question: str, retriever, llm, filters: Filters | None = None,
                    k: int | None = None, budget: int | None = None) -> Answer:
    s = get_settings()
    timings: dict = {}
    context = retrieve_and_pack(conn, question, retriever, k or s.answer_top_k, filters,
                                budget or s.context_token_budget, timings)
    if not context.sources:
        return Answer(question, REFUSAL_MESSAGE, True, "no_context", context, None, None, timings_ms=timings)
    t0 = time.perf_counter()
    result = llm.generate(INSTRUCTIONS, build_user_message(question, context))
    timings["generate"] = (time.perf_counter() - t0) * 1000
    return finish(question, context, result.text, timings, result)


def stream_answer(conn: psycopg.Connection, question: str, retriever, llm, filters: Filters | None = None,
                  k: int | None = None, budget: int | None = None):
    """Yields ("sources", PackedContext), then ("delta", text)…, then ("answer", Answer).

    Deltas are the model's raw text, so a REFUSAL_TOKEN can stream before the
    final Answer replaces it with the refusal message; Phase 10's API buffers
    until the first characters prove it isn't a refusal.
    """
    s = get_settings()
    timings: dict = {}
    context = retrieve_and_pack(conn, question, retriever, k or s.answer_top_k, filters,
                                budget or s.context_token_budget, timings)
    yield "sources", context
    if not context.sources:
        yield "answer", Answer(question, REFUSAL_MESSAGE, True, "no_context", context, None, None, timings_ms=timings)
        return
    t0 = time.perf_counter()
    first, parts = None, []
    for delta in llm.stream(INSTRUCTIONS, build_user_message(question, context)):
        if first is None:
            first = time.perf_counter()
            timings["first_token"] = (first - t0) * 1000
        parts.append(delta)
        yield "delta", delta
    timings["generate"] = (time.perf_counter() - t0) * 1000
    yield "answer", finish(question, context, "".join(parts), timings, llm.last_result)
