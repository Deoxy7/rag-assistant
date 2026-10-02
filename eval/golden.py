"""Load the golden set and resolve its evidence quotes to character spans.

File format (eval/golden/golden_v1.jsonl), one question per line:

    {"id": "G023", "type": "table", "question": "...", "answer": "...",
     "evidence": [ [ {"doc": "AMD_2022_10K", "quote": "Total net revenue | $ 23,601 | $ 16,434"},
                     {"doc": "AMD_2022_10K", "quote": "Net revenue | $ 23,601 | $ 16,434"} ] ],
     "note": "..."}

`evidence` is a list of *items* the answer needs (multi-hop questions have
several). Each item is a list of *alternatives*: any one of them is enough.
Each alternative is an exact substring of documents.canonical_text; every
occurrence of it in that document counts (a figure printed in both MD&A and
the financial statements is evidence in both places). Unanswerable questions
have `evidence: []` and `answer: null`.

Quotes are the source of truth, not offsets: re-parsing a PDF shifts offsets,
and resolving at load time re-checks every label against the stored text.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

GOLDEN = Path(__file__).resolve().parent / "golden" / "golden_v1.jsonl"
TYPES = ("factual", "table", "exact_token", "multi_hop", "unanswerable")


@dataclass(frozen=True)
class Span:
    doc_key: str
    char_start: int
    char_end: int
    page_number: int


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    question: str
    answer: str | None
    items: tuple[tuple[Span, ...], ...]   # evidence items → every resolved occurrence of every alternative
    note: str | None = None

    @property
    def answerable(self) -> bool:
        return bool(self.items)


class LabelError(ValueError):
    pass


def file_sha256(path: Path = GOLDEN) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def occurrences(text: str, quote: str) -> list[int]:
    out, i = [], text.find(quote)
    while i != -1:
        out.append(i)
        i = text.find(quote, i + 1)
    return out


def load(conn: psycopg.Connection, path: Path = GOLDEN) -> list[Question]:
    """Parse and resolve; raises LabelError on any quote that isn't in its document."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    docs: dict[str, tuple[str, list[tuple[int, int, int]]]] = {}

    def doc(key: str):
        if key not in docs:
            r = conn.execute("SELECT id, canonical_text FROM documents WHERE doc_key = %s", (key,)).fetchone()
            if r is None:
                raise LabelError(f"unknown document {key}")
            pages = conn.execute("SELECT page_number, char_start, char_end FROM pages WHERE document_id = %s "
                                 "ORDER BY page_number", (r[0],)).fetchall()
            docs[key] = (r[1], pages)
        return docs[key]

    questions, seen = [], set()
    for row in rows:
        if row["id"] in seen:
            raise LabelError(f"duplicate id {row['id']}")
        seen.add(row["id"])
        if row["type"] not in TYPES:
            raise LabelError(f"{row['id']}: unknown type {row['type']}")
        items = []
        for item in row["evidence"]:
            spans = []
            for alt in item:
                text, pages = doc(alt["doc"])
                starts = occurrences(text, alt["quote"])
                if not starts:
                    raise LabelError(f"{row['id']}: quote not found in {alt['doc']}: {alt['quote'][:60]!r}")
                for s in starts:
                    page = next(p for p, ps, pe in pages if ps <= s < pe)
                    spans.append(Span(alt["doc"], s, s + len(alt["quote"]), page))
            items.append(tuple(spans))
        if (row["type"] == "unanswerable") != (not items):
            raise LabelError(f"{row['id']}: unanswerable questions (and only those) must have no evidence")
        questions.append(Question(row["id"], row["type"], row["question"], row.get("answer"), tuple(items),
                                  row.get("note")))
    return questions
