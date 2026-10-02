"""Inspect the corpus before building anything on top of it.

For every PDF in data/manifest.json this reports what later phases depend on:
page count, how much text each page yields, whether any page looks scanned,
which 10-K "Items" (the standard section headings) are present, how many pages
carry tables, where the exhibits start, which lines repeat as page headers or
footers, and how big the corpus is in LLM tokens.

    python scripts/inspect_corpus.py              # print the report, write data/inspection.json
    python scripts/inspect_corpus.py --charts     # also render the charts into docs/diagrams/out/

The functions take a pymupdf.Document so tests can run them on a synthetic PDF.
"""

import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import pdfplumber
import pymupdf

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
OUT = REPO / "docs" / "diagrams" / "out"

# Item headings a 10-K for fiscal 2021/2022 is expected to contain (Regulation S-K).
# 1C (cybersecurity) only exists for fiscal years ending after 15 Dec 2023.
EXPECTED_ITEMS = ["1", "1A", "1B", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "9A", "9B", "9C",
                  "10", "11", "12", "13", "14", "15", "16"]
ITEM_HEADING = re.compile(r"(?im)^\s*item\s+(\d{1,2}[a-c]?)\s*[.:\-—–]")
# The signature page carries a fixed legal sentence. Matching the bare word
# "SIGNATURES" is wrong: it also appears in the table of contents on page 2-3.
# Boeing omits "or 15(d)", so only "Section 13" is required.
SIGNATURE_STATEMENT = re.compile(r"(?i)pursuant to the requirements of section 13")
INCOME_STATEMENT = re.compile(r"(?im)^\s*consolidated statements? of (income|operations|earnings)\b")
NEAR_EMPTY_CHARS = 200        # a page with fewer extractable characters is "near-empty"
SCANNED_IMAGE_COVERAGE = 0.5  # ...and if images also cover half the page, it may be a scan
EDGE_FRACTION = 0.08          # top/bottom 8% of the page height = header/footer band
REPEAT_SHARE = 0.3            # a line in that band on ≥30% of pages is a running header/footer


def page_stats(page: pymupdf.Page) -> dict:
    """Characters, image coverage and scanned-suspicion for one page."""
    text = page.get_text()
    area = page.rect.width * page.rect.height
    covered = sum(pymupdf.Rect(info["bbox"]).get_area() for info in page.get_image_info())
    coverage = min(covered / area, 1.0) if area else 0.0
    chars = len(text.strip())
    return {
        "chars": chars,
        "image_coverage": round(coverage, 3),
        "near_empty": chars < NEAR_EMPTY_CHARS,
        "scanned_suspect": chars < NEAR_EMPTY_CHARS and coverage >= SCANNED_IMAGE_COVERAGE,
    }


def items_found(doc: pymupdf.Document) -> dict[str, list[int]]:
    """Map each Item number to the 1-based pages where a line starts with 'Item N.'."""
    found: dict[str, list[int]] = {}
    for page in doc:
        for match in ITEM_HEADING.finditer(page.get_text()):
            found.setdefault(match.group(1).upper(), []).append(page.number + 1)
    return found


def normalised(text: str) -> str:
    """Collapse all whitespace, including non-breaking spaces, to single spaces."""
    return " ".join(text.split())


def signatures_page(doc: pymupdf.Document) -> int | None:
    """1-based page of the signature statement (first occurrence)."""
    for page in doc:
        if SIGNATURE_STATEMENT.search(normalised(page.get_text())):
            return page.number + 1
    return None


def income_statement_page(doc: pymupdf.Document) -> int | None:
    """1-based page whose line starts with 'Consolidated Statement(s) of Income/Operations/Earnings',
    skipping the table of contents (the first pages list it too)."""
    for page in doc:
        if page.number >= 5 and INCOME_STATEMENT.search(page.get_text()):
            return page.number + 1
    return None


def repeated_edge_lines(doc: pymupdf.Document) -> list[tuple[str, int]]:
    """Lines that recur in the header/footer band on many pages (running headers)."""
    counts: Counter[str] = Counter()
    for page in doc:
        h = page.rect.height
        seen = set()
        for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
            if y1 <= h * EDGE_FRACTION or y0 >= h * (1 - EDGE_FRACTION):
                # Digits vary per page ("Page 12"), so collapse them before counting.
                line = re.sub(r"\d+", "#", " ".join(text.split()))
                if line:
                    seen.add(line)
        counts.update(seen)
    threshold = max(2, int(doc.page_count * REPEAT_SHARE))
    return [(line, n) for line, n in counts.most_common() if n >= threshold]


def table_pages(path: Path) -> list[int]:
    """1-based pages on which pdfplumber's default (ruling-line) strategy finds a table."""
    with pdfplumber.open(path) as pdf:
        return [i + 1 for i, page in enumerate(pdf.pages) if page.find_tables()]


def inspect(path: Path, entry: dict, encoder) -> dict:
    started = time.perf_counter()
    doc = pymupdf.open(path)
    pages = [page_stats(p) for p in doc]
    chars = [p["chars"] for p in pages]
    text = "".join(p.get_text() for p in doc)
    items = items_found(doc)
    sig = signatures_page(doc)
    income = income_statement_page(doc)
    tables = table_pages(path)
    tokens = len(encoder.encode(text, disallowed_special=()))
    report = {
        "doc_key": entry["doc_key"],
        "company": entry["company"],
        "fiscal_year": entry["fiscal_year"],
        "bytes": path.stat().st_size,
        "pdf_version": doc.metadata.get("format", ""),
        "producer": doc.metadata.get("producer", ""),
        "pages": doc.page_count,
        "chars_total": sum(chars),
        "chars_per_page": {"min": min(chars), "median": int(statistics.median(chars)), "max": max(chars)},
        "near_empty_pages": sum(p["near_empty"] for p in pages),
        "scanned_suspect_pages": [i + 1 for i, p in enumerate(pages) if p["scanned_suspect"]],
        "images": sum(len(p.get_images()) for p in doc),
        "outline_entries": len(doc.get_toc()),
        "items_found": sorted(items, key=EXPECTED_ITEMS.index if set(items) <= set(EXPECTED_ITEMS) else str),
        "items_missing": [i for i in EXPECTED_ITEMS if i not in items],
        "signatures_page": sig,
        "pages_after_signatures": doc.page_count - sig if sig else 0,
        "income_statement_page": income,
        "financials_after_signatures": bool(sig and income and income > sig),
        "nbsp_chars": text.count("\xa0"),
        "table_pages": len(tables),
        "repeated_edge_lines": repeated_edge_lines(doc)[:5],
        "llm_tokens_o200k": tokens,
        "chars_per_token": round(len(text) / tokens, 2),
        "inspect_seconds": None,
        "per_page_chars": chars,
    }
    report["inspect_seconds"] = round(time.perf_counter() - started, 1)
    return report


def print_report(reports: list[dict]) -> None:
    head = f"{'document':18s} {'pages':>5s} {'after':>5s} {'chars':>9s} {'med/pg':>6s} {'empty':>5s} {'scan?':>5s} {'tbl pg':>6s} {'items':>5s} {'tokens':>9s} {'ch/tok':>6s} {'nbsp':>6s} {'outline':>7s}"
    print(head)
    print("-" * len(head))
    for r in reports:
        print(f"{r['doc_key']:18s} {r['pages']:5d} {r['pages_after_signatures']:5d} {r['chars_total']:9d} "
              f"{r['chars_per_page']['median']:6d} {r['near_empty_pages']:5d} {len(r['scanned_suspect_pages']):5d} "
              f"{r['table_pages']:6d} {len(r['items_found']):5d} {r['llm_tokens_o200k']:9d} {r['chars_per_token']:6.2f} "
              f"{r['nbsp_chars']:6d} {r['outline_entries']:7d}")
    total = lambda k: sum(r[k] for r in reports)
    print("-" * len(head))
    print(f"{'TOTAL':18s} {total('pages'):5d} {total('pages_after_signatures'):5d} {total('chars_total'):9d} {'':6s} "
          f"{total('near_empty_pages'):5d} {sum(len(r['scanned_suspect_pages']) for r in reports):5d} "
          f"{total('table_pages'):6d} {'':5s} {total('llm_tokens_o200k'):9d}")
    print()
    for r in reports:
        missing = ", ".join(r["items_missing"]) or "none"
        where = "AFTER" if r["financials_after_signatures"] else "before"
        print(f"{r['doc_key']}: producer={r['producer']!r}; items missing: {missing}; "
              f"signatures p.{r['signatures_page']}; income statement p.{r['income_statement_page']} ({where} signatures)")
        for line, n in r["repeated_edge_lines"][:3]:
            print(f"    repeated edge line on {n} pages: {line[:70]!r}")


def render_charts(reports: list[dict]) -> None:
    import matplotlib

    matplotlib.use("Agg")  # no display needed
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Pages per document, body vs exhibits.
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=200)
    names = [r["doc_key"].replace("_10K", "") for r in reports]
    body = [r["pages"] - r["pages_after_signatures"] for r in reports]
    exhibits = [r["pages_after_signatures"] for r in reports]
    ax.barh(names, body, color="#1d4ed8", label="up to and including the signature page")
    ax.barh(names, exhibits, left=body, color="#93c5fd", label="after the signature page (exhibits; Corning: also financial statements)")
    for i, (b, e) in enumerate(zip(body, exhibits)):
        ax.text(b + e + 4, i, str(b + e), va="center", fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("pages")
    ax.set_title("Pages per document")
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "04-pages-per-document.png", facecolor="white")
    plt.close(fig)

    # 2. Histogram of extractable characters per page, all documents pooled.
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=200)
    all_chars = [c for r in reports for c in r["per_page_chars"]]
    ax.hist(all_chars, bins=40, color="#1d4ed8")
    ax.axvline(NEAR_EMPTY_CHARS, color="#dc2626", linestyle="--", linewidth=1)
    ax.text(NEAR_EMPTY_CHARS + 60, ax.get_ylim()[1] * 0.9, f"near-empty threshold ({NEAR_EMPTY_CHARS} chars)", color="#dc2626", fontsize=8)
    ax.set_xlabel("extractable characters on the page")
    ax.set_ylabel("number of pages")
    ax.set_title(f"Characters per page across the corpus ({len(all_chars)} pages)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "04-chars-per-page-histogram.png", facecolor="white")
    plt.close(fig)


def main(argv: list[str]) -> int:
    import tiktoken

    encoder = tiktoken.get_encoding("o200k_base")
    manifest = json.loads((DATA / "manifest.json").read_text())
    reports = [inspect(DATA / e["path"], e, encoder) for e in manifest["documents"]]
    (DATA / "inspection.json").write_text(json.dumps(reports, indent=2) + "\n")
    print_report(reports)
    if "--charts" in argv:
        render_charts(reports)
        print("\ncharts written to docs/diagrams/out/04-*.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
