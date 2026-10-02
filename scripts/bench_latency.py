"""Real per-stage latency through the running API (make serve), then a waterfall chart from request_log.

    python scripts/bench_latency.py [--n 8] [--url http://127.0.0.1:8000]

Streams N FinanceBench questions (not in the eval cache, so the LLM is really
called) through POST /query/stream, records client-side time to the `sources`
event, first `delta` and end, then reads GET /stats and the request_log rows for
the server-side stage breakdown. Writes docs/diagrams/out/17-latency-waterfall.png.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from bench_keyword import load_questions  # noqa: E402

from app.store.db import connect  # noqa: E402

STAGES = [("llm.retry_wait", "LLM: waiting on rate-limit retries"), ("retrieve.vector.embed", "embed query"), ("retrieve.vector", "vector search (incl. embed)"),
          ("retrieve.keyword", "keyword search"), ("retrieve.fuse", "RRF fusion"), ("rerank", "cross-encoder rerank"),
          ("pack", "pack context"), ("first_token", "LLM: time to first token"), ("generate", "LLM: full answer")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--offset", type=int, default=0, help="skip the first questions (already cached by an earlier run)")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    qs = [q for _, q, _ in load_questions()][a.offset: a.offset + a.n]
    rids, client_rows = [], []
    with httpx.Client(base_url=a.url, timeout=180) as c:
        health = c.get("/health").json()
        print(f"server: {health['llm_provider']} / {health['llm_model']} · rerank {health['rerank_enabled']}")
        for q in qs:
            t0, t_src, t_delta, rid, status = time.perf_counter(), None, None, None, None
            with c.stream("POST", "/query/stream", json={"question": q}) as r:
                rid, status = r.headers.get("x-request-id"), r.status_code
                for line in r.iter_lines():
                    if line.startswith("event: sources") and t_src is None:
                        t_src = time.perf_counter()
                    elif line.startswith("event: delta") and t_delta is None:
                        t_delta = time.perf_counter()
            end = time.perf_counter()
            ms = lambda t: round((t - t0) * 1000, 1) if t else None  # noqa: E731
            client_rows.append((ms(t_src), ms(t_delta), ms(end)))
            rids.append(rid)
            print(f"  {rid} status {status} · sources {ms(t_src)} ms · first delta {ms(t_delta)} ms · end {ms(end)} ms")
        stats = c.get("/stats", params={"hours": 1}).json()
    with connect() as conn:
        rows = conn.execute("SELECT timings_ms, input_tokens, output_tokens, list_usd, billed_usd, cached, refused "
                            "FROM request_log WHERE request_id = ANY(%s)", (rids,)).fetchall()
    med = {k: statistics.median([r[0][k] for r in rows if k in r[0]]) for k, _ in STAGES if any(k in r[0] for r in rows)}
    print("\nserver-side stage medians (ms):", json.dumps({k: round(v, 1) for k, v in med.items()}))
    print("client medians (ms): sources", statistics.median(x[0] for x in client_rows if x[0]),
          "· first delta", statistics.median(x[1] for x in client_rows if x[1]) if any(x[1] for x in client_rows) else None,
          "· end", statistics.median(x[2] for x in client_rows))
    print("tokens in/out:", sum(r[1] for r in rows), "/", sum(r[2] for r in rows),
          "· list $%.6f · billed $%.6f · cached %d · refused %d" % (sum(r[3] for r in rows), sum(r[4] for r in rows),
                                                                   sum(r[5] for r in rows), sum(bool(r[6]) for r in rows)))
    print("/stats:", json.dumps({k: stats[k] for k in ("requests", "errors", "cache_hit_rate", "refusal_rate",
                                                       "list_usd_per_1k_requests", "total_ms")}))
    waterfall(med)
    return 0


def waterfall(med: dict) -> None:
    """Sequential stages as bars on a time axis (vector and keyword run one after the other today)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = [("retrieve.vector", "vector search (incl. query embedding)", "#15803d"),
             ("retrieve.keyword", "keyword search", "#1d4ed8"), ("retrieve.fuse", "RRF fusion", "#15803d"),
             ("rerank", "cross-encoder rerank (10 pairs)", "#15803d"), ("pack", "pack context", "#7e22ce"),
             ("first_token", "LLM: time to first token", "#7e22ce"), ("generate_rest", "LLM: rest of the answer", "#c084fc")]
    vals = dict(med)
    vals["generate_rest"] = max(0.0, med.get("generate", 0) - med.get("first_token", 0))
    fig, ax = plt.subplots(figsize=(11, 4.2), dpi=150)
    start, y = 0.0, 0
    for key, label, colour in order:
        w = vals.get(key, 0.0)
        ax.barh(y, w, left=start, color=colour, edgecolor="#111827", lw=0.5)
        ax.text(start + w + 15, y, f"{label}: {w:,.0f} ms", va="center", fontsize=9)
        start += w
        y += 1
    ax.invert_yaxis()
    ax.set_yticks([])
    ax.set_xlabel("milliseconds since the request (medians over the benchmark questions, server side)")
    ax.set_title("Where one /query/stream answer spends its time")
    ax.set_xlim(0, start * 1.45)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(ROOT / "docs/diagrams/out/17-latency-waterfall.png", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
