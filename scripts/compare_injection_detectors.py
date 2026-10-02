"""Compare the pattern-list injection detector with a trained classifier (Llama Prompt Guard 2, 86M).

Positives: the seven attack passages of eval/injection.py. Negatives: a seeded
random sample of real 10-K chunks from the default chunk set, which contain no
injections (the pattern list fires on 0 of all 69,176 stored chunks). Prompt
Guard runs on Groq and returns a probability that the text is an attack; we
flag at >= 0.5. Over 512 tokens its context fills, so long chunks are scored on
their first 1,500 characters (an honest weakness: an injection placed later in
a chunk would be missed).

    python scripts/compare_injection_detectors.py --n 300
"""

import argparse
import random
import sys
import time

import openai

from app.config import get_settings
from app.embed.embedder import model_key
from app.generate.guard import injection_signals
from app.generate.llm import with_retries
from app.store import repository as repo
from app.store.db import connect
from eval.injection import ATTACKS

MODEL = "meta-llama/llama-prompt-guard-2-86m"
MAX_CHARS = 1500


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="real chunks to sample as negatives")
    ap.add_argument("--seed", type=int, default=14)
    args = ap.parse_args(argv)
    s = get_settings()
    client = openai.OpenAI(api_key=s.groq_api_key.get_secret_value(), base_url=s.llm_base_url, max_retries=0)

    def guard_score(text: str) -> float:
        r = with_retries(lambda: client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": text[:MAX_CHARS]}]), 6, 1.0, 30.0)
        return float(r.choices[0].message.content)

    with connect() as conn:
        cs = repo.find_chunk_set(conn, s.chunk_strategy, s.chunk_size, s.chunk_overlap,
                                 model_key(s.embedding_model, s.embedding_model_revision))
        ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE chunk_set_id = %s ORDER BY id", (cs,))]
        sample = random.Random(args.seed).sample(ids, args.n)
        chunks = conn.execute("SELECT id, text FROM chunks WHERE id = ANY(%s) ORDER BY id", (sample,)).fetchall()
    rows, t0 = [], time.perf_counter()
    for a in ATTACKS:
        text = a.text.format(company="AMD", year=2022)
        rows.append({"kind": "attack", "id": a.id, "patterns": bool(injection_signals(text)), "guard": guard_score(text)})
    for cid, text in chunks:
        rows.append({"kind": "chunk", "id": cid, "patterns": bool(injection_signals(text)), "guard": guard_score(text),
                     "truncated": len(text) > MAX_CHARS})
    for name in ("patterns", "guard"):
        flag = (lambda r: r[name]) if name == "patterns" else (lambda r: r["guard"] >= 0.5)
        tp = sum(flag(r) for r in rows if r["kind"] == "attack")
        fp = sum(flag(r) for r in rows if r["kind"] == "chunk")
        missed = [r["id"] for r in rows if r["kind"] == "attack" and not flag(r)]
        print(f"{name:8s} attacks caught {tp}/{len(ATTACKS)} (missed {missed}) · false positives {fp}/{len(chunks)}")
    print("guard scores on attacks:", {r["id"]: round(r["guard"], 4) for r in rows if r["kind"] == "attack"})
    top = sorted((r for r in rows if r["kind"] == "chunk"), key=lambda r: -r["guard"])[:3]
    print("highest guard scores on real chunks:", [(r["id"], round(r["guard"], 4)) for r in top])
    print(f"{len(rows)} classifier calls in {time.perf_counter() - t0:.0f} s; "
          f"{sum(r.get('truncated', False) for r in rows)} chunks truncated to {MAX_CHARS} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
