"""Cross-encoder reranking over the hybrid (RRF) top-N: quality and latency vs N.

    python scripts/bench_rerank.py [--models minilm,bge-base] [--ns 10,20,50,100] [--device cpu]
                                   [--first hybrid|vector] [--oracle-filter]

Same two query sets as bench_hybrid.py (28 FinanceBench questions; 50 rare
exact figures). First stage: hybrid RRF k=60 at depth 50 per retriever (up to
100 fused candidates), computed once per query. Each reranker then re-sorts the
first N fused candidates. Latency = reranker time only (first stage excluded),
measured per query, warm, on the configured device.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embed.embedder import get_embedder  # noqa: E402
from app.retrieve.hybrid import rrf  # noqa: E402
from app.retrieve.keyword import KeywordRetriever  # noqa: E402
from app.retrieve.rerank import get_reranker, rerank  # noqa: E402
from app.retrieve.types import Filters  # noqa: E402
from app.retrieve.vector import VectorRetriever  # noqa: E402
from app.store.db import connect  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_hybrid import figure_queries  # noqa: E402
from bench_keyword import hit as page_hit, load_questions  # noqa: E402

MODELS = {
    "minilm": ("cross-encoder/ms-marco-MiniLM-L6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a"),
    "bge-base": ("BAAI/bge-reranker-base", "2cfc18c9415c912f9d8155881c133215df768a70"),
}


def pct(values, p):
    v = sorted(values)
    return v[min(len(v) - 1, round(p / 100 * (len(v) - 1)))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="minilm,bge-base")
    ap.add_argument("--ns", default="10,20,50,100")
    ap.add_argument("--device", default=None, help="override RERANK_DEVICE, e.g. cpu")
    ap.add_argument("--first", default="hybrid", choices=("hybrid", "vector"), help="first-stage retriever")
    ap.add_argument("--oracle-filter", action="store_true",
                    help="FinanceBench only: filter to the evidence document's company and year (an upper bound "
                         "for 'the user picked the filing'; figure queries stay unfiltered)")
    args = ap.parse_args()
    ns = [int(x) for x in args.ns.split(",")]

    emb = get_embedder()
    vec, kw = VectorRetriever(emb, 1), KeywordRetriever(1)
    with connect() as conn:
        fb = [(q, pages) for _, q, pages in load_questions()]
        meta = {d["doc_key"]: d for d in json.loads((Path(__file__).resolve().parents[1] / "data/manifest.json")
                                                    .read_text())["documents"]}

        def oracle(pages):
            if not args.oracle_filter:
                return None
            docs = [meta[doc] for doc, _ in pages]
            return Filters(companies=tuple({d["company"] for d in docs}), fiscal_years=tuple({d["fiscal_year"] for d in docs}))
        figs = figure_queries(conn)
        if args.first == "hybrid":
            def stage1(q, f=None):
                return rrf([vec.search(conn, q, k=50, filters=f), kw.search(conn, q, k=50, filters=f)], k=60)
        else:
            def stage1(q, f=None):
                return vec.search(conn, q, k=100, filters=f)
        first = {"fb": [(q, stage1(q, oracle(t)), t) for q, t in fb], "fig": [(f, stage1(f), ids) for f, ids in figs]}

    def hit(kind, hits, truth, k):
        return page_hit(hits, truth, k) if kind == "fb" else any(h.chunk_id in truth for h in hits[:k])

    def rates(ranked):
        return {(kind, k): sum(hit(kind, r, t, k) for r, t in ranked[kind]) / len(ranked[kind])
                for kind, ks in (("fb", (1, 5, 10)), ("fig", (1, 5))) for k in ks}

    stage = "hybrid RRF k=60, depth 50" if args.first == "hybrid" else "vector only, top 100"
    stage += " · FinanceBench filtered to the evidence filing (oracle)" if args.oracle_filter else ""
    print(f"FinanceBench {len(fb)} q · exact figures {len(figs)} q · first stage {stage}\n")
    header = f"{'ranking':30s} {'FB@1':>6s} {'FB@5':>6s} {'FB@10':>6s} {'fig@1':>6s} {'fig@5':>6s} {'p50 ms':>7s} {'p95 ms':>7s}"
    print(header)
    base = rates({kind: [(h, t) for _, h, t in rows] for kind, rows in first.items()})
    print(f"{'no rerank (' + args.first + ')':30s} {base[('fb', 1)]:6.3f} {base[('fb', 5)]:6.3f} {base[('fb', 10)]:6.3f} "
          f"{base[('fig', 1)]:6.3f} {base[('fig', 5)]:6.3f} {'—':>7s} {'—':>7s}")
    for name in args.models.split(","):
        model, rev = MODELS[name]
        rr = get_reranker(model, rev, device=args.device)
        rr.score("warm up", ["warm up"] * 8)
        for n in ns:
            ranked, ms = {}, []
            for kind, rows in first.items():
                ranked[kind] = []
                for q, hits, truth in rows:
                    t0 = time.perf_counter()
                    out = rerank(rr, q, hits[:n])
                    ms.append((time.perf_counter() - t0) * 1000)
                    ranked[kind].append((out, truth))
            r = rates(ranked)
            print(f"{name + ' N=' + str(n):30s} {r[('fb', 1)]:6.3f} {r[('fb', 5)]:6.3f} {r[('fb', 10)]:6.3f} "
                  f"{r[('fig', 1)]:6.3f} {r[('fig', 5)]:6.3f} {statistics.median(ms):7.1f} {pct(ms, 95):7.1f}")
        print(f"  {name}: device {rr.device}")

    print("\nrecall ceiling — share of queries whose evidence is anywhere in the first-stage top N:")
    for n in ns:
        fbc = sum(page_hit(h, t, n) for _, h, t in first["fb"]) / len(fb)
        figc = sum(any(x.chunk_id in t for x in h[:n]) for _, h, t in first["fig"]) / len(figs)
        print(f"  N={n:<4d} FinanceBench {fbc:.3f}   figures {figc:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
