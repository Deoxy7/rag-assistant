"""Read eval/results/ for the UI's results viewer: run list, headline metrics, per-question rows.

Results are files written once by eval/run.py, eval/ablate.py and
eval/injection.py, never edited, so the viewer reads them straight from disk.
There is no API endpoint for them: they are artefacts of offline runs, not
of the serving system.
"""

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"
STAMP = re.compile(r"^(\d{8}T\d{6}Z)_(.+)$")

ROW_COLUMNS = ("id", "type", "question", "hit@5", "recall@10", "rr", "refused", "judge_correctness",
               "judge_faithfulness", "answer")


@dataclass(frozen=True)
class Run:
    path: Path
    stamp: str      # 20261002T205049Z
    name: str       # gen-v2-rag
    kind: str       # "eval" | "injection"

    @property
    def label(self) -> str:
        return f"{self.name}  ·  {self.stamp[:4]}-{self.stamp[4:6]}-{self.stamp[6:8]} {self.stamp[9:11]}:{self.stamp[11:13]}Z"


def list_runs(results: Path = RESULTS, include_batches: bool = False) -> list[Run]:
    """Newest first. Ablation cells (abl-*) and partial batches are hidden unless asked for."""
    runs = []
    for p in results.glob("*.json"):
        m = STAMP.match(p.stem)
        if not m:
            continue                      # e.g. ablation-v1-financebench-cache.json
        stamp, name = m.groups()
        if not include_batches and (name.startswith("abl-") or "-batch" in name):
            continue
        runs.append(Run(p, stamp, name, "injection" if name.startswith("injection") else "eval"))
    return sorted(runs, key=lambda r: (r.stamp, r.name), reverse=True)


def default_index(runs: list[Run]) -> int:
    """The newest full eval with retrieval (not the injection suite, not the closed-book baseline)."""
    for i, r in enumerate(runs):
        if r.kind == "eval" and not load(r).get("config", {}).get("closed_book"):
            return i
    return 0


def load(run: Run) -> dict:
    return json.loads(run.path.read_text())


def _mean(x) -> float | None:
    return x.get("mean") if isinstance(x, dict) else x


def headline(data: dict) -> dict[str, float | str | None]:
    """The numbers a reader looks for first, flattened; None where a run didn't measure them."""
    s, c = data.get("summary", {}), data.get("config", {})
    gen, judge = s.get("generation") or {}, s.get("judge") or {}
    abst = gen.get("abstention") or {}
    out = {
        "config": "no retrieval" if c.get("closed_book") else
                  f"{c.get('chunk_strategy')}{c.get('chunk_size')}-{c.get('mode')}" + ("-rr" if c.get("rerank") else ""),
        "closed book": bool(c.get("closed_book")),
        "questions": s.get("questions"),
        "hit@5": _mean((s.get("overall") or {}).get("hit@5")),
        "recall@10": _mean((s.get("overall") or {}).get("recall@10")),
        "MRR": _mean((s.get("overall") or {}).get("rr")),
        "generator": gen.get("model"),
        "judge": judge.get("model"),
        "correctness": _mean(judge.get("correctness")),
        "faithfulness": _mean(judge.get("faithfulness")),
        "unanswerable refused": abst.get("recall"),
        "false refusals": abst.get("false_refusal_rate"),
    }
    return out


def question_rows(data: dict) -> list[dict]:
    return [{k: r.get(k) for k in ROW_COLUMNS} for r in data.get("rows", [])]


def injection_table(data: dict) -> list[dict]:
    """One row per attack: successes per configuration, out of the questions it was tried on."""
    by = {}
    for r in data.get("rows", []):
        row = by.setdefault(r["attack"], {"attack": r["attack"], "tried": 0, "v1": 0, "v2": 0, "v2+out": 0, "full": 0})
        row["tried"] += 1
        for cfg in ("v1", "v2", "v2+out", "full"):
            row[cfg] += bool(r[cfg]["success"])
    names = {a["id"]: a["name"] for a in data.get("attacks", [])}
    return [{"attack": f"{k} {names.get(k, '')}".strip(), **{x: v for x, v in row.items() if x != "attack"}}
            for k, row in sorted(by.items())]


def latest_ablation(results: Path = RESULTS) -> tuple[Path, list[dict]] | None:
    files = sorted(results.glob("*_ablation-*.csv"))
    if not files:
        return None
    with files[-1].open() as f:
        return files[-1], list(csv.DictReader(f))
