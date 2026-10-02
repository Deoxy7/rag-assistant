"""Five-minute terminal demo against a running API: four questions that show what the system does.

    make serve          # in one terminal
    make demo           # in another (RAG_API_URL to point elsewhere)

1. a single fact from one filing (citation to the exact page and span);
2. a table figure across two years (numbers + arithmetic, cited);
3. a question restricted by the company filter;
4. a question the filings can't answer (refusal instead of a guess).

It uses ui/client.py, so it goes through the public HTTP API like any client:
validation, injection guards, output policy and the request log all apply.
"""

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.client import APIError, Client  # noqa: E402

QUESTIONS = [
    ("A single fact, cited to its page", "How many full-time-equivalent employees did Verizon have at the end of 2022?",
     None),
    ("A table figure and the change between years", "What was AMD's net revenue in 2022, and how much did it grow?",
     None),
    ("The company filter", "What were total net sales in 2022?", ["Corning"]),
    ("Not in the filings: the system should refuse", "What was Apple's revenue in fiscal 2022?", None),
]


def main() -> int:
    c = Client()
    try:
        h = c.health()
    except Exception as exc:
        print(f"API not reachable at {c.base_url}: {exc}\nStart it with `make serve`.", file=sys.stderr)
        return 1
    docs = c.documents()
    print(f"API {c.base_url}: {h['status']} · {len(docs)} filings · {sum(d['chunks'] for d in docs):,} chunks\n")
    for i, (title, question, companies) in enumerate(QUESTIONS, 1):
        print(f"── {i}. {title} " + "─" * max(0, 70 - len(title)))
        print(f"Q: {question}" + (f"   [filter: {', '.join(companies)}]" if companies else ""))
        answer = None
        try:
            for event, data in c.stream(question, companies):
                if event == "answer":
                    answer = data
        except APIError as exc:
            print(f"   error {exc.code}: {exc.message}\n")
            continue
        print(textwrap.fill(f"A: {answer['answer']}", 100, subsequent_indent="   "))
        for cit in answer["citations"]:
            print(f"   [{cit['n']}] {cit['label']} · chunk {cit['chunk_id']} · chars {cit['char_start']:,}–{cit['char_end']:,}"
                  f" · preview: {c.base_url}/chunks/{cit['chunk_id']}/page.png")
        if answer["refused"]:
            print(f"   refused ({answer['refusal_reason']})")
        t, u = c.timings, answer["usage"]
        print(f"   sources {t.sources_ms:,.0f} ms · first token "
              f"{'—' if t.first_delta_ms is None else f'{t.first_delta_ms:,.0f} ms'} · done {t.done_ms:,.0f} ms · "
              f"{u['input_tokens']:,} in / {u['output_tokens']:,} out · {u['model']}{' (cached)' if u['cached'] else ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
