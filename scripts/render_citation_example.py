"""Draw a citation on its PDF page: the cited chunk's blocks highlighted on the rendered page.

    python scripts/render_citation_example.py [--question "..."] [--company AMD --year 2022]

Runs the real pipeline (fake LLM unless LLM_PROVIDER=openai and a key are set),
takes the first citation, and writes docs/diagrams/out/13-citation-on-page.png.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402

from app.generate.answer import answer_question  # noqa: E402
from app.generate.llm import FakeLLM, get_llm  # noqa: E402
from app.retrieve.rerank import retriever_from_settings  # noqa: E402
from app.retrieve.types import Filters  # noqa: E402
from app.store import repository as repo  # noqa: E402
from app.store.db import connect  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs/diagrams/out/13-citation-on-page.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="What was AMD's net revenue in 2022?")
    ap.add_argument("--company", default="AMD")
    ap.add_argument("--year", type=int, default=2022)
    args = ap.parse_args()
    try:
        llm = get_llm()
    except Exception:   # no key: the fake model still exercises citation mapping
        llm = FakeLLM()
    manifest = {d["doc_key"]: d for d in json.loads((REPO / "data/manifest.json").read_text())["documents"]}
    with connect() as conn:
        a = answer_question(conn, args.question, retriever_from_settings(1), llm,
                            filters=Filters((args.company,), (args.year,)))
        if a.refused or not a.report.citations:
            print("no citation to draw", file=sys.stderr)
            return 1
        c = a.report.citations[0]
        regions = repo.chunk_regions(conn, c.chunk_id)
    page_no = regions[0][0]
    doc = pymupdf.open(REPO / "data" / manifest[c.doc_key]["path"])
    page = doc[page_no - 1]
    for p, (x0, y0, x1, y1) in regions:
        if p == page_no:
            annot = page.add_rect_annot(pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2))
            annot.set_colors(stroke=(0.49, 0.13, 0.81), fill=(0.95, 0.91, 1.0))
            annot.set_opacity(0.45)
            annot.update()
    page.insert_text((36, page.rect.height - 18),
                     f"[{c.n}] {c.label} (PDF page) · chunk {c.chunk_id} · chars {c.char_start}–{c.char_end}",
                     fontsize=9, color=(0.49, 0.13, 0.81))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=110).save(OUT)
    print(f"answer: {a.text}\ncitation [{c.n}] {c.label}, chunk {c.chunk_id}, chars {c.char_start}–{c.char_end}, "
          f"{len(regions)} block(s) on page {page_no} → {OUT.relative_to(REPO)} ({a.provider})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
