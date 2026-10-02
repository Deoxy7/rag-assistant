"""End-to-end answers on the FinanceBench questions: context size, citations, refusals, latency, cost.

    python scripts/bench_answer.py [--provider fake|openai] [--oracle-filter] [--no-cache]

Pipeline = the app's defaults (retriever_from_settings + answer_question).
Every line of output names the provider. With the fake model the citation and
refusal numbers describe the *pipeline* (packing, parsing, mapping), not answer
quality; answer quality is measured in Phase 11 with the real model.

"cited evidence" = at least one cited source lies on a FinanceBench evidence page.
Cost uses the API's reported token counts and the configured per-token prices.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.generate.answer import answer_question  # noqa: E402
from app.generate.llm import CachedLLM, MissingAPIKey, get_llm  # noqa: E402
from app.retrieve.rerank import retriever_from_settings  # noqa: E402
from app.retrieve.types import Filters  # noqa: E402
from app.store.db import connect  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_keyword import load_questions  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=("fake", "openai"))
    ap.add_argument("--oracle-filter", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    if args.provider:
        s.llm_provider = args.provider
    try:
        llm = get_llm()
    except MissingAPIKey as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    meta = {d["doc_key"]: d for d in json.loads((REPO / "data/manifest.json").read_text())["documents"]}
    rows = []
    with connect() as conn:
        retriever = retriever_from_settings(1)
        client = llm if args.no_cache else CachedLLM(llm, conn)
        for qid, q, pages in load_questions():
            f = None
            if args.oracle_filter:
                docs = [meta[d] for d, _ in pages]
                f = Filters(tuple({d["company"] for d in docs}), tuple({d["fiscal_year"] for d in docs}))
            a = answer_question(conn, q, retriever, client, filters=f)
            conn.commit()
            cited_ev = bool(a.report) and any((c.doc_key, p) in pages for c in a.report.citations
                                              for p in range(c.page_number, c.page_end + 1))
            rows.append((a, cited_ev))
    n = len(rows)
    ans = [a for a, _ in rows if not a.refused]
    toks = [a.context.tokens for a, _ in rows]
    print(f"provider {s.llm_provider} · model {rows[0][0].model or s.llm_model} · {n} FinanceBench questions"
          f"{' · oracle filing filter' if args.oracle_filter else ''} · k {s.answer_top_k} · budget {s.context_token_budget}\n")
    print(f"sources packed per question     mean {statistics.mean(len(a.context.sources) for a, _ in rows):.1f}"
          f"  min {min(len(a.context.sources) for a, _ in rows)}  · dropped (over budget) {sum(len(a.context.dropped) for a, _ in rows)}")
    print(f"context tokens (o200k)          p50 {statistics.median(toks):.0f}  max {max(toks)}")
    print(f"prompt input tokens             p50 {statistics.median(a.input_tokens for a, _ in rows if a.input_tokens):.0f}")
    print(f"refused                          {n - len(ans)} of {n}  (model {sum(a.refusal_reason == 'model' for a, _ in rows)}, "
          f"no context {sum(a.refusal_reason == 'no_context' for a, _ in rows)})")
    if ans:
        print(f"answers citing ≥1 source         {sum(bool(a.report.citations) for a in ans)} of {len(ans)}")
        print(f"invalid markers                  {sum(len(a.report.invalid_markers) for a in ans)}")
        print(f"answers with uncited claims      {sum(bool(a.report.uncited_sentences) for a in ans)} of {len(ans)}")
        print(f"answers citing an evidence page  {sum(c for a, c in rows if not a.refused)} of {len(ans)}")
    gen = [a.timings_ms["generate"] for a, _ in rows if "generate" in a.timings_ms]
    ret = [a.timings_ms["retrieve"] for a, _ in rows]
    print(f"latency p50: retrieve {statistics.median(ret):.0f} ms · generate {statistics.median(gen):.0f} ms"
          f" · cached responses {sum(a.cached for a, _ in rows)} of {len(gen)}")
    tin = sum(a.input_tokens for a, _ in rows if not a.cached)
    tout = sum(a.output_tokens for a, _ in rows if not a.cached)
    cost = tin / 1e6 * s.llm_price_input_per_m + tout / 1e6 * s.llm_price_output_per_m
    label = "(fake model: no money spent; shown at the configured prices)" if s.llm_provider == "fake" else ""
    print(f"tokens billed this run           in {tin}  out {tout}  ≈ ${cost:.4f} {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
