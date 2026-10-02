"""Latency through HTTP: the running API (make serve) on the 28 FinanceBench questions.

    python scripts/bench_api.py [--url http://127.0.0.1:8000] [--concurrency 4]

Measures, per request: total time for POST /query, and for POST /query/stream
the time to the `sources` event and to the first `delta`. Then the same JSON
requests with N concurrent clients, to show what the single-model lock costs.
The LLM is whatever the server runs; the provider is printed and must be read
with the numbers (the fake model's generation time is ~0).
"""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_keyword import load_questions  # noqa: E402


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, round(p / 100 * (len(v) - 1)))]


def timed_query(client, q):
    t = time.perf_counter()
    r = client.post("/query", json={"question": q})
    r.raise_for_status()
    return (time.perf_counter() - t) * 1000, r.json()


def timed_stream(client, q):
    t, first_sources, first_delta = time.perf_counter(), None, None
    with client.stream("POST", "/query/stream", json={"question": q}) as r:
        for line in r.iter_lines():
            if line.startswith("event: sources") and first_sources is None:
                first_sources = (time.perf_counter() - t) * 1000
            elif line.startswith("event: delta") and first_delta is None:
                first_delta = (time.perf_counter() - t) * 1000
    return first_sources, first_delta, (time.perf_counter() - t) * 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    qs = [q for _, q, _ in load_questions()]
    with httpx.Client(base_url=args.url, timeout=120) as c:
        health = c.get("/health").json()
        print(f"server: provider {health['llm_provider']} · model {health['llm_model']} · "
              f"mode {health['retrieval_mode']} · rerank {health['rerank_enabled']} · {len(qs)} questions\n")
        timed_query(c, "warm up")
        seq = [timed_query(c, q) for q in qs]
        ms = [m for m, _ in seq]
        server_ret = [b["timings_ms"]["retrieve"] for _, b in seq]
        cached = sum(b["usage"]["cached"] for _, b in seq)
        print(f"POST /query sequential     p50 {statistics.median(ms):6.1f} ms  p95 {pct(ms, 95):6.1f}  "
              f"(server-side retrieve p50 {statistics.median(server_ret):.1f} ms; cached LLM {cached}/{len(qs)})")
        st = [timed_stream(c, q) for q in qs]
        src = [s for s, _, _ in st]
        dlt = [d for _, d, _ in st if d is not None]
        print(f"POST /query/stream         first `sources` p50 {statistics.median(src):6.1f} ms · "
              f"first `delta` p50 {statistics.median(dlt) if dlt else float('nan'):6.1f} ms "
              f"({len(dlt)}/{len(qs)} streamed text; the rest refused)")
    with httpx.Client(base_url=args.url, timeout=120) as c:
        t = time.perf_counter()
        with ThreadPoolExecutor(args.concurrency) as pool:
            conc = list(pool.map(lambda q: timed_query(c, q)[0], qs))
        wall = time.perf_counter() - t
    print(f"POST /query ×{args.concurrency} concurrent    p50 {statistics.median(conc):6.1f} ms  p95 {pct(conc, 95):6.1f}  "
          f"· throughput {len(qs) / wall:.1f} req/s (sequential: {1000 / statistics.mean(ms):.1f} req/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
