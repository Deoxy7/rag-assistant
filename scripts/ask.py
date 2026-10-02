"""Ask one question from the command line: retrieve, generate, print the answer with citations.

    python scripts/ask.py "What was AMD's net revenue in 2022?" [--company AMD --year 2022]
                          [--show-prompt] [--provider fake|openai] [--no-cache]

--show-prompt prints the exact instructions and user message sent to the model.
With --provider fake (or LLM_PROVIDER=fake) no API call is made; the fake
model's answers are extractive quotes, not model quality.
"""

import argparse
import sys

import openai
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import classify  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.generate.answer import answer_question  # noqa: E402
from app.generate.llm import CachedLLM, MissingAPIKey, get_llm  # noqa: E402
from app.retrieve.rerank import retriever_from_settings  # noqa: E402
from app.retrieve.types import Filters  # noqa: E402
from app.store.db import connect  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--company", action="append")
    ap.add_argument("--year", type=int, action="append")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--provider", choices=("fake", "openai"))
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    if args.provider:
        s.llm_provider = args.provider
    try:
        llm = get_llm()
    except MissingAPIKey as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    filters = Filters(tuple(args.company) if args.company else None, tuple(args.year) if args.year else None)
    with connect() as conn:
        client = llm if args.no_cache or not s.llm_cache_enabled else CachedLLM(llm, conn)
        try:
            a = answer_question(conn, args.question, retriever_from_settings(1), client, filters=filters)
        except openai.APIError as e:
            status, code, message = classify(e)
            print(f"error: {code}: {message}", file=sys.stderr)
            return 3
        conn.commit()
    if args.show_prompt:
        instructions, user = a.prompt
        print("=" * 30 + " INSTRUCTIONS " + "=" * 30 + f"\n{instructions}\n")
        print("=" * 30 + " USER MESSAGE " + "=" * 30 + f"\n{user}\n")
        print("=" * 74)
    print(f"\n{a.text}\n")
    if a.report:
        for c in a.report.citations:
            print(f"  [{c.n}] {c.label} · chunk {c.chunk_id} · chars {c.char_start}–{c.char_end}")
        if a.report.invalid_markers:
            print(f"  removed invalid markers: {list(a.report.invalid_markers)}")
        if a.report.uncited_sentences:
            print(f"  uncited sentences: {len(a.report.uncited_sentences)}")
    print(f"\n  {a.provider or '-'} / {a.model or '-'} · sources {len(a.context.sources)} "
          f"({a.context.tokens} tokens, {len(a.context.dropped)} dropped) · in {a.input_tokens} / out {a.output_tokens}"
          f"{' · cached' if a.cached else ''} · " + " · ".join(f"{k} {v:.0f} ms" for k, v in a.timings_ms.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
