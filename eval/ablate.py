"""Phase 12 ablations: run the retrieval grid through eval.run, then tabulate, test and chart it.

    python -m eval.ablate --tag v1            # run what's missing, then write the table + charts
    python -m eval.ablate --tag v1 --report   # only rebuild the table/charts from existing runs

Grid (retrieval only, no LLM): chunk strategy {fixed, recursive, structure} × size {128, 256, 510}
(overlap = size // 8) × mode {vector, keyword, hybrid} × rerank {on, off} = 54 configurations,
plus single-factor extras on the baseline (BM25 ranking, rerank depth 20).

Resumable: each configuration is one eval.run result named abl-<tag>-<config>; a configuration
whose result already exists for the current golden set is reused, not re-run, so the grid can be
completed across several invocations.

Per configuration the table reports golden-set hit@1/@5, recall@10, MRR, nDCG@10, precision@5,
by-type numbers, retrieval latency, a paired sign test against the baseline on per-question hit@5,
and FinanceBench page-hit@10 (28 external questions) as a check on golden-set overfitting.
"""

import argparse
import csv
import datetime as dt
import glob
import json
import statistics
import sys
from pathlib import Path

from app.store.db import connect
from eval import golden, run
from eval.metrics.stats import sign_test

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
CHARTS = ROOT / "docs" / "diagrams" / "out"
STRATEGIES, SIZES, MODES = ("fixed", "recursive", "structure"), (128, 256, 510), ("vector", "keyword", "hybrid")
BASELINE = "structure256-hybrid-rr"


def grid() -> list[tuple[str, list[str]]]:
    out = []
    for st in STRATEGIES:
        for size in SIZES:
            for mode in MODES:
                for rr in (True, False):
                    name = f"{st}{size}-{mode}-{'rr' if rr else 'norr'}"
                    args = ["--chunk-strategy", st, "--chunk-size", str(size), "--chunk-overlap", str(size // 8),
                            "--mode", mode, "--rerank" if rr else "--no-rerank"]
                    out.append((name, args))
    base = ["--chunk-strategy", "structure", "--chunk-size", "256", "--chunk-overlap", "32"]
    out += [("structure256-hybrid-rr-bm25", base + ["--mode", "hybrid", "--rerank", "--rank-function", "bm25"]),
            ("structure256-keyword-norr-bm25", base + ["--mode", "keyword", "--no-rerank", "--rank-function", "bm25"]),
            ("structure256-hybrid-rr-n20", base + ["--mode", "hybrid", "--rerank", "--rerank-n", "20"])]
    return out


def existing(tag: str, name: str, sha: str) -> Path | None:
    for path in sorted(glob.glob(str(RESULTS / f"*_abl-{tag}-{name}.json")), reverse=True):
        meta = json.loads(Path(path).read_text())["meta"]
        if meta["golden_sha256"] == sha:
            return Path(path)
    return None


def financebench_hit10(args: list[str]) -> float:
    """Page-hit@10 on the 28 FinanceBench questions for one configuration (same retriever as the eval)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from bench_keyword import hit as page_hit, load_questions
    ns = run_args(args)
    with connect() as conn:
        from app.embed.embedder import model_key
        from app.config import get_settings
        from app.store import repository as repo
        s = get_settings()
        cs = repo.find_chunk_set(conn, ns.chunk_strategy, ns.chunk_size, ns.chunk_overlap,
                                 model_key(s.embedding_model, s.embedding_model_revision))
        retriever = run.build_retriever(ns, cs)
        qs = load_questions()
        return sum(page_hit(retriever.search(conn, q, k=10), pages, 10) for _, q, pages in qs) / len(qs)


def run_args(args: list[str]):
    """The argparse namespace eval.run would build for these flags (to reuse build_retriever)."""
    import argparse as ap_
    s = run.get_settings()
    p = ap_.ArgumentParser()
    p.add_argument("--chunk-strategy"); p.add_argument("--chunk-size", type=int); p.add_argument("--chunk-overlap", type=int)
    p.add_argument("--mode"); p.add_argument("--rerank", action=ap_.BooleanOptionalAction, default=True)
    p.add_argument("--rerank-n", type=int, default=s.rerank_n); p.add_argument("--rank-function", default="ts_rank")
    ns = p.parse_args(args)
    ns.rrf_k, ns.depth = s.rrf_k, s.retrieval_depth
    return ns


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--report", action="store_true", help="don't run anything; rebuild table and charts")
    ap.add_argument("--max-runs", type=int, default=1000, help="stop after this many new runs (to fit a time box)")
    a = ap.parse_args(argv)
    sha = golden.file_sha256()
    configs = grid()
    new = 0
    if not a.report:
        for name, args in configs:
            if existing(a.tag, name, sha):
                continue
            if new >= a.max_runs:
                print(f"stopping after {new} new runs (--max-runs); re-run to continue")
                break
            code, path = run.run(["--name", f"abl-{a.tag}-{name}", *args])
            if code != 0:
                print(f"run {name} failed with code {code}", file=sys.stderr)
                return code
            new += 1
    missing = [n for n, _ in configs if not existing(a.tag, n, sha)]
    if missing:
        print(f"{len(missing)} configurations still missing (e.g. {missing[:3]}); table not written yet")
        return 0

    # --- tabulate ------------------------------------------------------------------------------
    results = {n: json.loads(existing(a.tag, n, sha).read_text()) for n, _ in configs}
    base_rows = {r["id"]: r for r in results[BASELINE]["rows"] if r["answerable"]}
    fb_cache_path = RESULTS / f"ablation-{a.tag}-financebench-cache.json"
    fb = json.loads(fb_cache_path.read_text()) if fb_cache_path.exists() else {}
    for n, args in configs:
        if n not in fb:
            fb[n] = round(financebench_hit10(args), 4)
            fb_cache_path.write_text(json.dumps(fb, indent=1))
    table = []
    for n, args in configs:
        d = results[n]
        s, o = d["summary"], d["summary"]["overall"]
        rows = {r["id"]: r for r in d["rows"] if r["answerable"]}
        ids = sorted(base_rows)
        w, l, p = sign_test([rows[i]["hit@5"] for i in ids], [base_rows[i]["hit@5"] for i in ids])
        c = d["config"]
        table.append({
            "config": n, "strategy": c["chunk_strategy"], "size": c["chunk_size"], "mode": c["mode"],
            "rerank": c["rerank"], "rank_function": c.get("rank_function", "ts_rank"), "rerank_n": c["rerank_n"],
            "hit@1": o["hit@1"]["mean"], "hit@5": o["hit@5"]["mean"], "hit@5_ci": o["hit@5"]["ci95"],
            "recall@10": o["recall@10"]["mean"], "mrr": o["rr"]["mean"], "ndcg@10": o["ndcg@10"]["mean"],
            "precision@5": o["precision@5"]["mean"],
            "multi_hop_recall@5": s["by_type"]["multi_hop"]["recall@5"], "table_hit@5": s["by_type"]["table"]["hit@5"],
            "exact_hit@5": s["by_type"]["exact_token"]["hit@5"], "factual_hit@5": s["by_type"]["factual"]["hit@5"],
            "abstention_auroc": s.get("retrieval_abstention", {}).get("auroc"),
            "retrieve_ms_p50": s["retrieve_ms_p50"], "fb_hit@10": fb[n],
            "vs_base_wins": w, "vs_base_losses": l, "vs_base_p": round(p, 4),
            "result_file": existing(a.tag, n, sha).name})
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cpath = RESULTS / f"{stamp}_ablation-{a.tag}.csv"
    with cpath.open("x", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(table[0]))
        wtr.writeheader()
        for r in table:
            wtr.writerow({**r, "hit@5_ci": f"{r['hit@5_ci'][0]}–{r['hit@5_ci'][1]}"})
    mpath = RESULTS / f"{stamp}_ablation-{a.tag}.md"
    mpath.open("x").write(markdown(table, sha))
    charts(table, a.tag)
    print(f"→ {cpath.relative_to(ROOT)}\n→ {mpath.relative_to(ROOT)}")
    return 0


METRICS = [("hit@5", "golden hit@5"), ("recall@10", "golden recall@10"), ("mrr", "golden MRR"),
           ("ndcg@10", "golden nDCG@10"), ("multi_hop_recall@5", "multi-hop recall@5"), ("table_hit@5", "table hit@5"),
           ("exact_hit@5", "exact-token hit@5"), ("fb_hit@10", "FinanceBench hit@10"),
           ("retrieve_ms_p50", "retrieval p50 ms (lower is better)")]


def markdown(table: list[dict], sha: str) -> str:
    lines = [f"# Ablation results (golden set sha256 {sha[:12]}…; 52 answerable questions)", "",
             "Sign test: paired on per-question hit@5 vs the baseline (structure256-hybrid-rr); "
             "W/L = questions where the config hits and the baseline doesn't / vice versa.", "",
             "| config | hit@1 | hit@5 [95% CI] | recall@10 | MRR | nDCG@10 | multi-hop R@5 | table hit@5 | "
             "exact hit@5 | FB hit@10 | p50 ms | W/L vs base (p) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(table, key=lambda r: (-r["hit@5"], -r["mrr"])):
        lines.append(f"| {r['config']} | {r['hit@1']:.3f} | {r['hit@5']:.3f} [{r['hit@5_ci'][0]:.2f}–{r['hit@5_ci'][1]:.2f}] | "
                     f"{r['recall@10']:.3f} | {r['mrr']:.3f} | {r['ndcg@10']:.3f} | {r['multi_hop_recall@5']:.3f} | "
                     f"{r['table_hit@5']:.3f} | {r['exact_hit@5']:.3f} | {r['fb_hit@10']:.3f} | {r['retrieve_ms_p50']:.0f} | "
                     f"{r['vs_base_wins']}/{r['vs_base_losses']} ({r['vs_base_p']:.2f}) |")
    lines += ["", "## Winner per metric", "", "| metric | winner | value | runner-up | value |", "|---|---|---|---|---|"]
    for key, label in METRICS:
        rev = key != "retrieve_ms_p50"
        ranked = sorted(table, key=lambda r: (r[key] if not rev else -r[key], r["config"]))
        lines.append(f"| {label} | {ranked[0]['config']} | {ranked[0][key]:.3f} | {ranked[1]['config']} | {ranked[1][key]:.3f} |")
    return "\n".join(lines) + "\n"


def charts(table: list[dict], tag: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grid_rows = [r for r in table if r["rank_function"] == "ts_rank" and r["rerank_n"] == 10]
    colours = {"vector": "#15803d", "keyword": "#1d4ed8", "hybrid": "#7e22ce"}

    # 1. hit@5 by chunk configuration, one bar per mode, solid = rerank, hatched = no rerank
    fig, ax = plt.subplots(figsize=(13, 5.2), dpi=150)
    labels = [f"{st}\n{sz}" for st in STRATEGIES for sz in SIZES]
    width = 0.13
    for j, mode in enumerate(MODES):
        for k_, rr in enumerate((True, False)):
            vals = [next(r["hit@5"] for r in grid_rows if r["strategy"] == st and r["size"] == sz and r["mode"] == mode
                         and r["rerank"] == rr) for st in STRATEGIES for sz in SIZES]
            xs = [i + (j * 2 + k_ - 2.5) * width for i in range(len(labels))]
            ax.bar(xs, vals, width, color=colours[mode] if rr else "white", edgecolor=colours[mode],
                   hatch=None if rr else "///", label=f"{mode} {'+ rerank' if rr else 'no rerank'}")
    base = next(r for r in table if r["config"] == BASELINE)
    ax.axhline(base["hit@5"], color="#dc2626", lw=1, ls="--")
    ax.text(len(labels) - 0.5, base["hit@5"] + 0.01, f"baseline {base['hit@5']:.3f}", color="#dc2626", ha="right", fontsize=9)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_ylabel("golden-set hit@5 (52 answerable questions)")
    ax.set_ylim(0, 1)
    ax.set_title("Retrieval ablation: hit@5 by chunking (strategy, size in tokens), retrieval mode and reranking")
    ax.legend(ncol=3, fontsize=8, loc="upper left")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(CHARTS / "16-ablation-hit5.png", facecolor="white")
    plt.close(fig)

    # 2. golden hit@5 vs FinanceBench hit@10 for every grid config (overfitting check)
    fig, ax = plt.subplots(figsize=(7.5, 5.2), dpi=150)
    for mode in MODES:
        for rr in (True, False):
            pts = [r for r in grid_rows if r["mode"] == mode and r["rerank"] == rr]
            ax.scatter([r["hit@5"] for r in pts], [r["fb_hit@10"] for r in pts], s=36,
                       color=colours[mode] if rr else "white", edgecolors=colours[mode], label=f"{mode} {'+ rr' if rr else ''}")
    ax.scatter([base["hit@5"]], [base["fb_hit@10"]], s=140, facecolors="none", edgecolors="#dc2626", lw=1.5, label="baseline")
    ax.set_xlabel("golden-set hit@5")
    ax.set_ylabel("FinanceBench page-hit@10 (28 external questions)")
    ax.set_title("Does a better golden-set score carry over to FinanceBench?")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(CHARTS / "16-ablation-golden-vs-financebench.png", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
