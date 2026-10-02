"""Vector vs keyword vs hybrid (RRF and weighted fusion) on two kinds of questions.

    python scripts/bench_hybrid.py

1. FinanceBench: the 28 labelled questions on our filings (paraphrased natural
   language). Hit = a top-k chunk from the evidence document covering an
   evidence page.
2. Exact figures: 50 numbers written with thousands separators (e.g. "16,434")
   that occur in at most two chunks of the chunk set, sampled with a fixed seed.
   The query is the figure; hit = a top-k chunk containing it. Labels are
   mechanical, so they're exact — but the queries are artificial.

Each retriever runs once per question (depth 50); fusion variants are computed
from those same lists, so differences come only from the fusion rule.
"""

import random
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embed.embedder import get_embedder  # noqa: E402
from app.retrieve.hybrid import HybridRetriever, rrf, weighted_fusion  # noqa: E402
from app.retrieve.keyword import KeywordRetriever  # noqa: E402
from app.retrieve.vector import VectorRetriever  # noqa: E402
from app.store.db import connect  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_keyword import hit as page_hit, load_questions  # noqa: E402

DEPTH = 50
FIGURE = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")


def figure_queries(conn, n=50, seed=13):
    counts: dict[str, set[int]] = {}
    for cid, text in conn.execute("SELECT id, text FROM chunks WHERE chunk_set_id = 1"):
        for f in set(FIGURE.findall(text)):
            counts.setdefault(f, set()).add(cid)
    rare = sorted(f for f, ids in counts.items() if len(ids) <= 2 and len(f) >= 5)
    random.Random(seed).shuffle(rare)
    return [(f, counts[f]) for f in rare[:n]]


def main() -> int:
    emb = get_embedder()
    vec, kw = VectorRetriever(emb, 1), KeywordRetriever(1)
    with connect() as conn:
        fb = load_questions()
        figs = figure_queries(conn)
        lists = {"fb": [(vec.search(conn, q, k=DEPTH), kw.search(conn, q, k=DEPTH), pages) for _, q, pages in fb],
                 "fig": [(vec.search(conn, f, k=DEPTH), kw.search(conn, f, k=DEPTH), ids) for f, ids in figs]}

    def hit(kind, hits, truth, k):
        if kind == "fb":
            return page_hit(hits, truth, k)
        return any(h.chunk_id in truth for h in hits[:k])

    methods = {"vector only": lambda v, w: v, "keyword only": lambda v, w: w}
    for k_ in (1, 10, 60, 100):
        methods[f"hybrid RRF k={k_}"] = lambda v, w, k_=k_: rrf([v, w], k=k_)
    for a in (0.3, 0.5, 0.7):
        methods[f"weighted α_vec={a}"] = lambda v, w, a=a: weighted_fusion([v, w], [a, 1 - a])

    print(f"FinanceBench: {len(fb)} questions · exact figures: {len(figs)} queries · depth {DEPTH} per retriever\n")
    print(f"{'method':22s} {'FB hit@5':>8s} {'FB hit@10':>9s} {'FB hit@20':>9s} {'fig hit@1':>9s} {'fig hit@5':>9s} {'fig hit@20':>10s}")
    for name, fuse in methods.items():
        r = {}
        for kind, ks in (("fb", (5, 10, 20)), ("fig", (1, 5, 20))):
            rows = lists[kind]
            for k in ks:
                r[(kind, k)] = sum(hit(kind, fuse(v, w), t, k) for v, w, t in rows) / len(rows)
        print(f"{name:22s} {r[('fb', 5)]:8.3f} {r[('fb', 10)]:9.3f} {r[('fb', 20)]:9.3f} {r[('fig', 1)]:9.3f} "
              f"{r[('fig', 5)]:9.3f} {r[('fig', 20)]:10.3f}")

    # Latency of a full search call per mode (k=10; hybrid fetches depth 50 from each).
    print("\nlatency on the FinanceBench questions, k=10 (warm, sequential, one connection)")
    hyb = HybridRetriever(vec, kw, rrf_k=60, depth=DEPTH)
    with connect() as conn:
        for name, r in (("vector", vec), ("keyword", kw), ("hybrid RRF k=60", hyb)):
            ms = []
            for _, q, _ in fb:
                t = time.perf_counter()
                r.search(conn, q, k=10)
                ms.append((time.perf_counter() - t) * 1000)
            ms.sort()
            print(f"  {name:18s} p50 {statistics.median(ms):6.1f} ms   max {ms[-1]:6.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
