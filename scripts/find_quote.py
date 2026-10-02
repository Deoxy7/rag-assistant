"""Search a filing's canonical text: print every match with its page and character offsets.

    python scripts/find_quote.py AMD_2022_10K "Total net revenue" [--context 200] [--regex]

Used to write golden-set evidence: a quote is copied from this output, so it is
exactly a substring of documents.canonical_text and resolves to offsets.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.store.db import connect  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_key")
    ap.add_argument("pattern")
    ap.add_argument("--context", type=int, default=160)
    ap.add_argument("--regex", action="store_true")
    ap.add_argument("--max", type=int, default=8)
    a = ap.parse_args()
    with connect() as conn:
        row = conn.execute("SELECT id, canonical_text FROM documents WHERE doc_key = %s", (a.doc_key,)).fetchone()
        if not row:
            print(f"unknown doc {a.doc_key}", file=sys.stderr)
            return 1
        doc_id, text = row
        pages = conn.execute("SELECT page_number, char_start, char_end FROM pages WHERE document_id = %s "
                             "ORDER BY page_number", (doc_id,)).fetchall()
    rx = re.compile(a.pattern if a.regex else re.escape(a.pattern), re.I)
    n = 0
    for m in rx.finditer(text):
        page = next((p for p, s, e in pages if s <= m.start() < e), None)
        lo, hi = max(0, m.start() - a.context), min(len(text), m.end() + a.context)
        print(f"--- p{page} chars {m.start()}–{m.end()}\n{text[lo:hi]!r}\n")
        n += 1
        if n >= a.max:
            break
    print(f"{n} match(es) shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
