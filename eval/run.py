"""Run the golden set against one configuration and write timestamped results (never overwriting).

    python -m eval.run --name baseline                       # retrieval metrics only (no LLM)
    python -m eval.run --name e2e --generate --judge         # + answers (LLM_PROVIDER) + judge metrics
    python -m eval.run --name vec-only --mode vector --no-rerank

Configuration flags mirror Settings (retrieval mode, rerank on/off and N, k,
chunking config). Output: eval/results/<UTC time>_<name>.json (config, summary,
per-question rows) and .csv (per-question rows). Files are opened with mode
"x", so an existing result can never be overwritten.

Deterministic: questions in file order, HNSW search is deterministic for a
fixed index and ef_search, the reranker is deterministic, and LLM calls go
through the response cache. Same config + same code + same index → same file
contents except timings.
"""

import argparse
import csv
import dataclasses
import datetime as dt
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.embed.embedder import get_embedder, model_key
from app.generate.answer import answer_question
from app.generate.llm import CachedLLM, ChatClient, FakeLLM, get_llm
from app.retrieve.hybrid import get_retriever
from app.retrieve.rerank import RerankingRetriever, get_reranker
from app.store import repository as repo
from app.store.db import connect
from eval import golden
from eval.metrics import abstention as ab
from eval.metrics import judge as jd
from eval.metrics import retrieval as rm
from eval.metrics.stats import bootstrap_ci, mean

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
KS = (1, 3, 5, 10)


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    # "dirty" = uncommitted changes in anything that can change a result (code, labels, pins),
    # not docs: a doc edit in progress shouldn't mark a run as unreproducible.
    paths = ["app", "eval", "scripts", "requirements.txt", "docker-compose.yml", "pytest.ini"]
    return {"commit": run("rev-parse", "HEAD"),
            "dirty": bool(run("status", "--porcelain", "--untracked-files=no", "--", *paths))}


def build_retriever(args, chunk_set_id: int):
    s = get_settings()
    base = get_retriever(args.mode, chunk_set_id, embedder=get_embedder() if args.mode != "keyword" else None,
                         rrf_k=args.rrf_k, depth=args.depth)
    if args.rerank:
        return RerankingRetriever(base, get_reranker(), n=args.rerank_n)
    return base


def ideal_grades(conn, chunk_set_id: int, q: golden.Question) -> list[int]:
    chunks = {}
    for item in q.items:
        for sp in item:
            for cid, doc, cs, ce in repo.chunks_overlapping(conn, chunk_set_id, sp.doc_key, sp.char_start, sp.char_end):
                chunks[cid] = rm.ChunkRef(cid, doc, cs, ce)
    return [g for g in (rm.chunk_grade(c, q.items) for c in chunks.values()) if g > 0]


def summarise(rows: list[dict], key: str) -> dict:
    xs = [r[key] for r in rows if r.get(key) is not None]
    if not xs:
        return {"mean": None, "ci95": None, "n": 0}
    lo, hi = bootstrap_ci(xs)
    return {"mean": round(mean(xs), 4), "ci95": [round(lo, 4), round(hi, 4)], "n": len(xs)}


def open_exclusive(stem: str, suffix: str):
    """Create a new file; if the name exists, add -2, -3… (never overwrite)."""
    for i in range(1, 1000):
        path = RESULTS / f"{stem}{'' if i == 1 else f'-{i}'}{suffix}"
        try:
            return path, path.open("x", newline="")
        except FileExistsError:
            continue
    raise RuntimeError("could not find a free result file name")


def main(argv=None) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--mode", default=s.retrieval_mode, choices=("vector", "keyword", "hybrid"))
    ap.add_argument("--rerank", action=argparse.BooleanOptionalAction, default=s.rerank_enabled)
    ap.add_argument("--rerank-n", type=int, default=s.rerank_n)
    ap.add_argument("--rrf-k", type=int, default=s.rrf_k)
    ap.add_argument("--depth", type=int, default=s.retrieval_depth)
    ap.add_argument("--k", type=int, default=s.answer_top_k, help="chunks retrieved per question (max of KS used)")
    ap.add_argument("--chunk-strategy", default=s.chunk_strategy)
    ap.add_argument("--chunk-size", type=int, default=s.chunk_size)
    ap.add_argument("--chunk-overlap", type=int, default=s.chunk_overlap)
    ap.add_argument("--generate", action="store_true", help="also generate answers with LLM_PROVIDER")
    ap.add_argument("--judge", action="store_true", help="score answers with the LLM judge (needs --generate)")
    ap.add_argument("--judge-model", default=s.llm_judge_model)
    ap.add_argument("--limit", type=int, help="first N questions only (smoke runs)")
    ap.add_argument("--ids", help="comma-separated question ids only, e.g. G001,G045,G053 (smoke runs)")
    args = ap.parse_args(argv)
    if args.judge and not args.generate:
        ap.error("--judge needs --generate")

    t_start = time.perf_counter()
    with connect() as conn:
        cs = repo.find_chunk_set(conn, args.chunk_strategy, args.chunk_size, args.chunk_overlap,
                                 model_key(s.embedding_model, s.embedding_model_revision))
        if cs is None:
            print(f"error: chunk set {args.chunk_strategy}/{args.chunk_size}/{args.chunk_overlap} not ingested",
                  file=sys.stderr)
            return 2
        questions = golden.load(conn)
        if args.ids:
            wanted = [x.strip() for x in args.ids.split(",") if x.strip()]
            unknown = set(wanted) - {q.id for q in questions}
            if unknown:
                print(f"error: unknown question ids {sorted(unknown)}", file=sys.stderr)
                return 2
            questions = [q for q in questions if q.id in wanted]
        questions = questions[: args.limit]
        retriever = build_retriever(args, cs)
        llm = judge = None
        if args.generate:
            llm = CachedLLM(get_llm(), connect)
        if args.judge:
            judge_client = get_llm("judge")
            if isinstance(judge_client, FakeLLM):
                print("error: --judge needs a real model (LLM_PROVIDER=gemini or openai); the fake model can't grade",
                      file=sys.stderr)
                return 2
            if args.judge_model != judge_client.model:      # --judge-model overrides LLM_JUDGE_MODEL for one run
                judge_client = ChatClient(judge_client.provider, judge_client.client.api_key, args.judge_model,
                                          judge_client.base_url, judge_client.max_output_tokens, judge_client.temperature,
                                          judge_client.reasoning_effort, s.llm_timeout_s, s.llm_max_retries,
                                          s.llm_retry_base_s, s.llm_retry_max_s)
            judge = CachedLLM(judge_client, connect)
        rows = []
        for q in questions:
            t0 = time.perf_counter()
            hits = retriever.search(conn, q.question, k=args.k)
            ms = (time.perf_counter() - t0) * 1000
            refs = [rm.ChunkRef(h.chunk_id, h.doc_key, h.char_start, h.char_end) for h in hits]
            row = {"id": q.id, "type": q.type, "answerable": q.answerable, "question": q.question,
                   "retrieve_ms": round(ms, 1), "top_score": round(hits[0].score, 4) if hits else None,
                   "retrieved": [h.chunk_id for h in hits]}
            if q.answerable:
                ideal = ideal_grades(conn, cs, q)
                for k in KS:
                    sc = rm.score(refs, q.items, k, ideal)
                    row.update({f"hit@{k}": sc.hit, f"recall@{k}": sc.recall, f"precision@{k}": sc.precision,
                                f"ndcg@{k}": round(sc.ndcg, 4)})
                    row["rr"], row["first_rank"] = sc.rr, sc.first_rank
                row["relevant_in_set"] = len(ideal)
            if llm is not None:
                try:
                    a = answer_question(conn, q.question, retriever, llm, k=args.k)
                except Exception as exc:  # noqa: BLE001 — after retries: record it and keep the run going
                    row.update({"error": f"{type(exc).__name__}: {str(exc)[:200]}", "refused": None})
                    rows.append(row)
                    print(f"  {q.id}: generation failed after retries ({type(exc).__name__}); recorded, continuing",
                          file=sys.stderr)
                    continue
                row.update({"refused": a.refused, "answer": a.text, "provider": a.provider, "model": a.model,
                            "input_tokens": a.input_tokens, "output_tokens": a.output_tokens, "cached": a.cached,
                            "invalid_markers": len(a.report.invalid_markers) if a.report else 0,
                            "uncited_sentences": len(a.report.uncited_sentences) if a.report else 0,
                            "cited_evidence": (any(rm.item_grade(rm.ChunkRef(c.chunk_id, c.doc_key, c.char_start,
                                                                               c.char_end), it) > 0
                                                   for c in a.report.citations for it in q.items)
                                               if a.report and q.answerable else None)})
                row["truncated"] = bool(a.truncated)
                if judge is not None:
                    try:
                        js = jd.judge_answer(judge, q.question, a.text, a.refused,
                                             [s_.hit.text for s_ in a.context.sources], q.answer)
                        row.update({f"judge_{k}": v for k, v in dataclasses.asdict(js).items()})
                    except Exception as exc:  # noqa: BLE001
                        row["judge_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            rows.append(row)
        conn.commit()

    answerable = [r for r in rows if r["answerable"]]
    summary = {"questions": len(rows), "answerable": len(answerable), "unanswerable": len(rows) - len(answerable),
               "overall": {m: summarise(answerable, m) for m in
                           [f"{x}@{k}" for x in ("hit", "recall", "precision", "ndcg") for k in KS] + ["rr"]},
               "by_type": {t: {m: summarise([r for r in answerable if r["type"] == t], m)["mean"]
                               for m in ("hit@5", "recall@5", "recall@10", "ndcg@10", "rr")}
                           for t in golden.TYPES if t != "unanswerable"},
               "retrieve_ms_p50": sorted(r["retrieve_ms"] for r in rows)[len(rows) // 2]}
    pos = [r["top_score"] for r in answerable if r["top_score"] is not None]
    neg = [r["top_score"] for r in rows if not r["answerable"] and r["top_score"] is not None]
    if pos and neg:
        sweep = ab.threshold_sweep(pos, neg)
        best = max(sweep, key=lambda x: (x[3], -x[1]))
        # Operating points: the cheapest threshold (fewest false refusals) that catches at least
        # a third / two thirds / all of the unanswerable questions.
        points = {}
        for target in (1 / 3, 2 / 3, 1.0):
            t_, fr, rec, acc = min((x for x in sweep if x[2] >= target - 1e-9), key=lambda x: (x[1], -x[2]))
            points[f"catch>={target:.2f}"] = {"t": t_, "false_refusal_rate": round(fr, 4),
                                              "abstention_recall": round(rec, 4)}
        summary["retrieval_abstention"] = {
            "score": "top reranker score" if args.rerank else f"top {args.mode} score",
            "auroc": round(ab.auroc(pos, neg), 4),
            "best_accuracy_threshold": {"t": best[0], "false_refusal_rate": round(best[1], 4),
                                        "abstention_recall": round(best[2], 4), "accuracy": round(best[3], 4)},
            "operating_points": points}
    if llm is not None:
        done = [r for r in rows if r.get("refused") is not None]
        sc = ab.abstention([r["refused"] for r in done], [r["answerable"] for r in done])
        summary["generation"] = {"provider": next((r["provider"] for r in done), None),
                                 "model": next((r["model"] for r in rows if r.get("model")), None),
                                 "abstention": dataclasses.asdict(sc),
                                 "cited_evidence_rate": summarise([{"x": float(r["cited_evidence"])} for r in answerable
                                                                   if r.get("cited_evidence") is not None], "x"),
                                 "input_tokens": sum(r["input_tokens"] for r in done if not r["cached"]),
                                 "output_tokens": sum(r["output_tokens"] for r in done if not r["cached"]),
                                 "errors": len(rows) - len(done),
                                 "truncated": sum(bool(r.get("truncated")) for r in done)}
        if judge is not None:
            summary["judge"] = {"model": judge.model,
                                **{m: summarise(rows, f"judge_{m}") for m in
                                   ("faithfulness", "answer_relevance", "context_precision", "correctness")},
                                "parse_errors": sum(r.get("judge_parse_errors", 0) for r in rows),
                                "judge_errors": sum("judge_error" in r for r in rows)}

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    config = {k: v for k, v in vars(args).items() if k not in ("limit", "ids")} | {"ids": args.ids,
        "chunk_set_id": cs, "ks": KS, "ef_search": 160, "embedding_model": model_key(s.embedding_model,
                                                                                   s.embedding_model_revision),
        "rerank_model": s.rerank_model if args.rerank else None, "llm_provider": s.llm_provider if args.generate else None,
        "llm_base_url": s.llm_base_url if args.generate else None, "llm_model": s.llm_model if args.generate else None,
        "llm_reasoning_effort": s.llm_reasoning_effort if args.generate else None,
        "judge_model": args.judge_model if args.judge else None, "limit": args.limit}
    meta = {"created_utc": stamp, "golden_file": str(golden.GOLDEN.relative_to(ROOT)),
            "golden_sha256": golden.file_sha256(), "git": git_state(), "python": platform.python_version(),
            "wall_s": round(time.perf_counter() - t_start, 1)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    jpath, jf = open_exclusive(f"{stamp}_{args.name}", ".json")
    with jf:
        json.dump({"meta": meta, "config": config, "summary": summary, "rows": rows}, jf, indent=1, default=str)
    cpath, cf = open_exclusive(f"{stamp}_{args.name}", ".csv")
    with cf:
        cols = sorted({k for r in rows for k in r if k not in ("retrieved", "answer")},
                      key=lambda c: (c not in ("id", "type", "answerable", "question"), c))
        w = csv.DictWriter(cf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    o = summary["overall"]
    print(f"{args.name}: {len(rows)} questions ({len(answerable)} answerable) · mode {args.mode} · "
          f"rerank {args.rerank} · chunk set {cs}")
    print("  " + "  ".join(f"{m} {o[m]['mean']:.3f} [{o[m]['ci95'][0]:.2f}–{o[m]['ci95'][1]:.2f}]"
                           for m in ("hit@5", "recall@5", "recall@10", "ndcg@10", "rr")))
    if "retrieval_abstention" in summary:
        ra = summary["retrieval_abstention"]
        print(f"  retrieval-only abstention: AUROC {ra['auroc']:.3f} · " + " · ".join(
            f"catch {v['abstention_recall']:.2f} costs {v['false_refusal_rate']:.2f} false refusals (t={v['t']:.2f})"
            for v in ra["operating_points"].values()))
    if "generation" in summary:
        g = summary["generation"]
        a_ = g["abstention"]
        print(f"  generation ({g['provider']} / {g['model']}): refused unanswerable {a_['recall']}, "
              f"false refusals {a_['false_refusal_rate']}, cited evidence {g['cited_evidence_rate']['mean']}, "
              f"errors {g['errors']}, truncated {g['truncated']}, tokens in {g['input_tokens']} / out {g['output_tokens']}")
    if "judge" in summary:
        j = summary["judge"]
        print(f"  judge ({j['model']}): " + " · ".join(f"{m} {j[m]['mean']}" for m in
              ("faithfulness", "answer_relevance", "context_precision", "correctness"))
              + f" · parse errors {j['parse_errors']} · judge errors {j['judge_errors']}")
    print(f"  → {jpath.relative_to(ROOT)}\n  → {cpath.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
