"""Benchmark vector search on the real corpus (chunk set from settings).

    python scripts/bench_vector.py            # print the tables
    python scripts/bench_vector.py --chart    # also draw docs/diagrams/out/09-recall-vs-ef-search.png

Queries: all 150 FinanceBench open-source questions (realistic financial
phrasing; most are about companies outside our corpus, which is fine for
measuring the *index* against exact search). Reports:

1. HNSW recall@10 vs exact search, and latency, for several ef_search values
2. the filtered-search recall cliff: post-filter vs iterative vs exact — once with
   the planner free to choose (it pre-filters at this size), once with the HNSW
   path forced (enable_sort = off), which is what a large table would get
3. quantisation: halfvec and binary indexes vs full precision, same raw query shape
"""

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embed.embedder import get_embedder  # noqa: E402
from app.retrieve.types import Filters  # noqa: E402
from app.retrieve.vector import VectorRetriever  # noqa: E402
from app.store.db import connect  # noqa: E402
from app.store.repository import vector_literal  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
K = 10


def pct(values, q):
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def timed_search(conn, retriever, vectors, filters=None):
    results, ms = [], []
    for v in vectors:
        t = time.perf_counter()
        hits = retriever.search(conn, "", k=K, filters=filters, query_vector=v)
        ms.append((time.perf_counter() - t) * 1000)
        results.append([h.chunk_id for h in hits])
    return results, ms


def recall(approx, exact):
    per_query = [len(set(a) & set(e)) / len(e) for a, e in zip(approx, exact) if e]
    return sum(per_query) / len(per_query)


def main() -> int:
    questions = [json.loads(l)["question"] for l in open(REPO / "data/financebench/financebench_open_source.jsonl")]
    emb = get_embedder()
    vectors = [emb.embed_query(q) for q in questions]
    chunk_set = 1
    with connect() as conn:
        n = conn.execute("SELECT count(*) FROM embeddings WHERE chunk_set_id = %s", (chunk_set,)).fetchone()[0]
        print(f"{len(questions)} queries, {n} vectors (chunk set {chunk_set}, {emb.key}), k={K}\n")

        exact, exact_ms = timed_search(conn, VectorRetriever(emb, chunk_set, filter_mode="exact"), vectors)
        print(f"{'method':24s} {'recall@10':>9s} {'p50 ms':>7s} {'p95 ms':>7s}")
        print(f"{'exact scan':24s} {1.0:9.3f} {statistics.median(exact_ms):7.2f} {pct(exact_ms, .95):7.2f}")
        curve = []
        for ef in (10, 20, 40, 80, 160, 320):
            res, ms = timed_search(conn, VectorRetriever(emb, chunk_set, ef_search=ef, filter_mode="post"), vectors)
            curve.append((ef, recall(res, exact), statistics.median(ms)))
            print(f"{'hnsw ef_search=' + str(ef):24s} {recall(res, exact):9.3f} {statistics.median(ms):7.2f} {pct(ms, .95):7.2f}")

        print("\nfiltered search: company=Corning, fiscal_year=2021 (smallest company-year)")
        f = Filters(companies=("Corning",), fiscal_years=(2021,))
        share = conn.execute("""SELECT count(*) FILTER (WHERE d.company='Corning' AND d.fiscal_year=2021)::float / count(*)
                                FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.chunk_set_id=%s""", (chunk_set,)).fetchone()[0]
        print(f"rows passing the filter: {share:.1%} of the chunk set")
        f_exact, f_exact_ms = timed_search(conn, VectorRetriever(emb, chunk_set, filter_mode="exact"), vectors, f)
        print(f"{'mode':24s} {'avg rows':>8s} {'<10 rows':>8s} {'recall@10':>9s} {'p50 ms':>7s} {'p95 ms':>7s}")
        for label, r, ms in [("exact (pre-filter scan)", f_exact, f_exact_ms)] + [
                (f"{mode} ef_search=40", *timed_search(conn, VectorRetriever(emb, chunk_set, filter_mode=mode), vectors, f))
                for mode in ("post", "iterative")]:
            short = sum(len(x) < K for x in r)
            print(f"{label:24s} {statistics.mean(len(x) for x in r):8.1f} {short:8d} {recall(r, f_exact):9.3f} "
                  f"{statistics.median(ms):7.2f} {pct(ms, .95):7.2f}")

        print("\nsame filter, HNSW path forced (SET LOCAL enable_sort = off removes the exact plan's Sort)")
        print(f"{'mode':24s} {'avg rows':>8s} {'<10 rows':>8s} {'0 rows':>6s} {'recall@10':>9s}")
        # A separate connection with auto-prepare off: psycopg server-side-prepares a
        # query after 5 executions, Postgres caches its plan, and planner settings
        # such as enable_sort no longer change a cached plan (T-026).
        forced_conn = connect()
        forced_conn.prepare_threshold = None
        for mode in ("post", "iterative"):
            r = VectorRetriever(emb, chunk_set, filter_mode=mode)
            got = []
            for v in vectors:
                with forced_conn.transaction():
                    forced_conn.execute("SET LOCAL enable_sort = off")
                    forced_conn.execute("SET LOCAL hnsw.ef_search = 40")
                    forced_conn.execute("SET LOCAL hnsw.iterative_scan = " +
                                        ("relaxed_order" if mode == "iterative" else "off"))
                    rows = forced_conn.execute(r.query_sql(f, exact=False), {"q": vector_literal(v), "k": K,
                                               "companies": ["Corning"], "years": [2021]}).fetchall()
                got.append([row[0] for row in rows])
            print(f"{mode + ' ef_search=40':24s} {statistics.mean(len(x) for x in got):8.1f} {sum(len(x) < K for x in got):8d} "
                  f"{sum(len(x) == 0 for x in got):6d} {recall(got, f_exact):9.3f}")
        forced_conn.close()

        print("\nquantisation at ef_search=40 (index built for this run, then dropped; raw query on embeddings, no joins)")
        model = emb.key
        quant = {
            "vector (32-bit)": (None, "embedding::vector(384) <=> %(q)s::vector(384)", None),
            "halfvec (16-bit)": ("(embedding::halfvec(384)) halfvec_cosine_ops",
                                 "embedding::halfvec(384) <=> %(q)s::halfvec(384)", None),
            "binary (1-bit) + rerank": ("(binary_quantize(embedding::vector(384))::bit(384)) bit_hamming_ops",
                                        "binary_quantize(embedding::vector(384))::bit(384) <~> binary_quantize(%(q)s::vector(384))", 40),
        }
        print(f"{'index':24s} {'size MB':>8s} {'build s':>7s} {'recall@10':>9s} {'p50 ms':>7s}")
        for label, (expr, order, rerank_from) in quant.items():
            conn.execute("DROP INDEX IF EXISTS bench_quant")
            if expr is None:  # the production index, already built
                build = float("nan")
                size = conn.execute("SELECT pg_relation_size(c.oid) FROM pg_class c "
                                    "WHERE c.relname LIKE 'embeddings_hnsw_set1_%'").fetchone()[0] / 1e6
            else:
                t = time.perf_counter()
                conn.execute(f"CREATE INDEX bench_quant ON embeddings USING hnsw ({expr}) "
                             f"WHERE chunk_set_id = {chunk_set} AND model = '{model}'")
                conn.commit()
                build = time.perf_counter() - t
                size = conn.execute("SELECT pg_relation_size('bench_quant')").fetchone()[0] / 1e6
            res, ms = [], []
            for v in vectors:
                lit = vector_literal(v)
                t = time.perf_counter()
                limit = rerank_from or K
                with conn.transaction():
                    # Same ef_search for every index type (and no setting inherited from
                    # earlier searches on this connection — the T-025 leak).
                    conn.execute("SET LOCAL hnsw.ef_search = 40")
                    conn.execute("SET LOCAL hnsw.iterative_scan = off")
                    rows = conn.execute(f"""SELECT chunk_id, embedding::vector(384) <=> %(q)s::vector(384) AS d FROM embeddings
                                            WHERE chunk_set_id = {chunk_set} AND model = '{model}'
                                            ORDER BY {order} LIMIT {limit}""", {"q": lit}).fetchall()
                # Binary: the coarse 1-bit search proposes 40 candidates; re-rank them by exact distance.
                rows = sorted(rows, key=lambda r: r[1])[:K]
                ms.append((time.perf_counter() - t) * 1000)
                res.append([r[0] for r in rows])
            build_txt = "—" if build != build else f"{build:.2f}"  # NaN for the existing index
            print(f"{label:24s} {size:8.2f} {build_txt:>7s} {recall(res, exact):9.3f} {statistics.median(ms):7.2f}")
            conn.execute("DROP INDEX IF EXISTS bench_quant")
            conn.commit()
    if "--chart" in sys.argv:
        draw_chart(curve, statistics.median(exact_ms))
    return 0


def draw_chart(curve, exact_ms):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    efs, recalls, ms = zip(*curve)
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=200)
    ax.plot(efs, recalls, marker="o", color="#15803d", label="recall@10 vs exact (left axis)")
    for ef, r in zip(efs, recalls):
        ax.annotate(f"{r:.3f}", (ef, r), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#15803d")
    ax.set_xscale("log", base=2)
    ax.set_xticks(efs, [str(e) for e in efs])
    ax.set_xlabel("hnsw.ef_search (candidate list size)")
    ax.set_ylabel("recall@10 vs exact search", color="#15803d")
    ax.set_ylim(0.7, 1.03)
    ax2 = ax.twinx()
    ax2.plot(efs, ms, marker="s", color="#4b5563", label="median latency (right axis)")
    ax2.axhline(exact_ms, color="#4b5563", linestyle="--", linewidth=1)
    ax2.annotate(f"exact scan {exact_ms:.1f} ms", (efs[0], exact_ms), textcoords="offset points", xytext=(4, -12), fontsize=8, color="#4b5563")
    ax2.set_ylabel("median latency, ms (7,411 vectors, 150 queries)", color="#4b5563")
    ax2.set_ylim(0, exact_ms * 1.25)
    lines = ax.get_lines()[:1] + ax2.get_lines()[:1]
    ax.legend(lines, [l.get_label() for l in lines], loc="lower right", frameon=False, fontsize=8)
    ax.set_title("HNSW: recall and latency as ef_search grows")
    fig.tight_layout()
    fig.savefig(REPO / "docs/diagrams/out/09-recall-vs-ef-search.png", facecolor="white")


if __name__ == "__main__":
    sys.exit(main())
