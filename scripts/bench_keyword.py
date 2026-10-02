"""Compare keyword ranking functions with vector search on FinanceBench's labelled questions.

    python scripts/bench_keyword.py

Ground truth: the 28 FinanceBench open-source questions about our 10 filings,
each with evidence pages (zero-indexed in FinanceBench; +1 here). Note: the
evidence key in the real file is `doc_name`, not `evidence_doc_name` as the README says. A retrieved
chunk is a hit if it comes from the evidence document and its page range covers
an evidence page. Reported: page-hit@5 and @10 (share of questions with at
least one hit in the top k) and median latency. 28 questions is a small
sample: one question = 3.6 percentage points.
"""

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.embed.embedder import get_embedder  # noqa: E402
from app.retrieve.keyword import KeywordRetriever  # noqa: E402
from app.retrieve.vector import VectorRetriever  # noqa: E402
from app.store.db import connect  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def load_questions():
    keys = {d["doc_key"] for d in json.loads((REPO / "data/manifest.json").read_text())["documents"]}
    out = []
    for line in open(REPO / "data/financebench/financebench_open_source.jsonl"):
        q = json.loads(line)
        if q["doc_name"] in keys:
            pages = {(e["doc_name"], e["evidence_page_num"] + 1) for e in q["evidence"]}
            out.append((q["financebench_id"], q["question"], pages))
    return out


def hit(hits, pages, k):
    return any((h.doc_key, p) in pages for h in hits[:k] for p in range(h.page_number, h.page_end + 1))


def main() -> int:
    questions = load_questions()
    emb = get_embedder()
    methods = {
        "vector (bge-small)": VectorRetriever(emb, 1),
        "keyword ts_rank": KeywordRetriever(1, rank_function="ts_rank"),
        "keyword ts_rank_cd": KeywordRetriever(1, rank_function="ts_rank_cd"),
        "keyword bm25": KeywordRetriever(1, rank_function="bm25"),
    }
    print(f"{len(questions)} FinanceBench questions on our filings, chunk set 1 (structure/256)\n")
    print(f"{'method':22s} {'hit@5':>6s} {'hit@10':>6s} {'p50 ms':>7s}")
    per_method = {}
    with connect() as conn:
        for name, r in methods.items():
            h5 = h10 = 0
            ms = []
            wins = []
            for qid, text, pages in questions:
                t = time.perf_counter()
                hits = r.search(conn, text, k=10)
                ms.append((time.perf_counter() - t) * 1000)
                h5 += hit(hits, pages, 5)
                h10 += hit(hits, pages, 10)
                wins.append(hit(hits, pages, 10))
            per_method[name] = wins
            n = len(questions)
            print(f"{name:22s} {h5 / n:6.3f} {h10 / n:6.3f} {statistics.median(ms):7.1f}")
    v, b = per_method["vector (bge-small)"], per_method["keyword bm25"]
    print(f"\nhit@10 overlap, vector vs bm25: both {sum(x and y for x, y in zip(v, b))}, "
          f"vector only {sum(x and not y for x, y in zip(v, b))}, bm25 only {sum(y and not x for x, y in zip(v, b))}, "
          f"neither {sum(not x and not y for x, y in zip(v, b))}")
    for (qid, text, _), x, y in zip(questions, v, b):
        if x != y:
            print(f"  {'vector' if x else 'bm25  '} only: {text[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
