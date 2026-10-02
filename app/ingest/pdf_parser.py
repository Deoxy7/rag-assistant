"""PDF → ParsedDocument: structured blocks with page numbers and character offsets.

Pipeline for one PDF (each step is a function below):

1. extract_page_blocks   PyMuPDF text blocks with bounding boxes and font info
2. find_edge_keys        lines that repeat in the top/bottom band = running headers/footers
3. find_tables           pdfplumber tables (ruled tables, every page)
4. order_blocks          reading order, two-column aware
5. classify_heading      PART / ITEM / other headings → section path
6. assemble              one canonical text, every block's char_start/char_end into it

The canonical text is Unicode-normalised (NFKC) *before* any offset is computed,
because normalising later would shift every stored offset.
"""

import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pymupdf

from app.ingest.models import Block, Page, ParsedDocument

PARSER_VERSION = "2.3"
BLOCK_SEPARATOR = "\n\n"

EDGE_FRACTION = 0.08   # top/bottom 8% of the page = header/footer band
REPEAT_SHARE = 0.1     # a band line on ≥10% of pages (and ≥5 pages) is a running header/footer
MIN_REPEAT_PAGES = 5
PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,4}$", re.IGNORECASE)
TABLE_PAD = 2.0        # points of slack when testing "is this block inside a table?"

PART_HEADING = re.compile(r"^part\s+(i{1,3}|iv)\b", re.IGNORECASE)
ITEM_HEADING = re.compile(r"^item\s+(\d{1,2}[a-c]?)\s*[.:\-—–]", re.IGNORECASE)
SIGNATURE_STATEMENT = re.compile(r"pursuant to the requirements of section 13", re.IGNORECASE)


@dataclass
class RawBlock:
    page_number: int
    bbox: tuple[float, float, float, float]
    text: str
    bold: bool            # every character is in a bold font
    max_size: float       # largest font size in the block
    kind: str = "text"


def normalise(text: str) -> str:
    """NFKC (folds non-breaking spaces, ligatures, full-width forms), then one space between words."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def edge_key(text: str) -> str:
    """Digits collapsed so 'Page 12' and 'Page 13' count as the same running footer,
    and a leading/trailing page number dropped: Verizon prints '5 Verizon 2022 Annual
    Report…' on odd pages and '…Form 10-K 6' on even ones — one footer, two layouts."""
    key = re.sub(r"\d+", "#", normalise(text))
    return re.sub(r"^#\s+|\s+#$", "", key)


def line_is_bold(spans: list[dict]) -> bool:
    return all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)


def extract_page_blocks(page: pymupdf.Page) -> list[RawBlock]:
    """Text blocks, split into paragraphs at line level.

    PyMuPDF's own blocks are not always paragraphs: Corning's 2021 PDF puts a
    whole section — running header, Item headings and body — in one block,
    separated only by lines that contain nothing but a non-breaking space. So a
    block is split wherever a blank line appears, boldness changes, or a line
    starts a PART/ITEM heading.
    """
    data = page.get_text("dict", flags=pymupdf.TEXT_DEHYPHENATE | pymupdf.TEXT_MEDIABOX_CLIP)
    blocks: list[RawBlock] = []

    def flush(lines: list[tuple[tuple, str, list[dict]]]) -> None:
        if not lines:
            return
        # Lines of one paragraph were broken by layout, so join them with spaces.
        text = normalise(" ".join(text for _, text, _ in lines))
        if not text:
            return
        spans = [s for _, _, line_spans in lines for s in line_spans]
        bbox = (min(b[0] for b, _, _ in lines), min(b[1] for b, _, _ in lines),
                max(b[2] for b, _, _ in lines), max(b[3] for b, _, _ in lines))
        blocks.append(RawBlock(page.number + 1, tuple(round(v, 2) for v in bbox), text,
                               line_is_bold(spans), max(s["size"] for s in spans)))

    for b in data["blocks"]:
        if b["type"] != 0:  # 0 = text, 1 = image
            continue
        current: list[tuple[tuple, str, list[dict]]] = []
        for line in b["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            text = "".join(s["text"] for s in line["spans"])
            if not spans:            # blank (or non-breaking-space-only) line = paragraph break
                flush(current)
                current = []
                continue
            starts_heading = bool(ITEM_HEADING.match(normalise(text)) or PART_HEADING.match(normalise(text)))
            style_changed = bool(current) and line_is_bold(spans) != line_is_bold([s for _, _, ss in current for s in ss])
            if current and (starts_heading or style_changed):
                flush(current)
                current = []
            current.append((tuple(line["bbox"]), text, spans))
        flush(current)
    return blocks


def in_edge_band(block: RawBlock, height: float) -> bool:
    x0, y0, x1, y1 = block.bbox
    return y1 <= height * EDGE_FRACTION or y0 >= height * (1 - EDGE_FRACTION)


def find_edge_keys(pages: list[list[RawBlock]], heights: list[float]) -> set[str]:
    counts: Counter[str] = Counter()
    for blocks, height in zip(pages, heights):
        counts.update({edge_key(b.text) for b in blocks if in_edge_band(b, height)})
    # An absolute floor, not only a share of all pages: PepsiCo's header appears on
    # its 129 body pages, but 30% of its 503 pages (exhibits included) would be 150.
    threshold = max(MIN_REPEAT_PAGES, int(len(pages) * REPEAT_SHARE))
    return {key for key, n in counts.items() if n >= threshold}


def clean_table(rows: list[list[str | None]]) -> str:
    """Rows → 'cell | cell' lines. Empty cells are dropped and a lone '$' cell is
    merged into the amount after it, because pdfplumber splits '$ 16,434' in two."""
    lines = []
    for row in rows:
        cells = [normalise(c) for c in row if c is not None and normalise(c)]
        merged: list[str] = []
        for cell in cells:
            if merged and merged[-1] in {"$", "€", "£"}:
                merged[-1] = f"{merged[-1]} {cell}"
            else:
                merged.append(cell)
        if merged:
            lines.append(" | ".join(merged))
    return "\n".join(lines)


def find_tables(pymupdf_page: pymupdf.Page, plumber_page) -> list[RawBlock]:
    # Every page is checked. Skipping pages that draw no lines was tried and
    # measured: 118/118 AMD pages and 213/215 Boeing pages draw something, so it
    # saved ~2% of parse time for identical output — not worth the extra rule.
    tables = []
    for table in plumber_page.find_tables():
        text = clean_table(table.extract())
        if text:
            tables.append(RawBlock(pymupdf_page.number + 1, tuple(round(v, 2) for v in table.bbox), text,
                                   bold=False, max_size=0.0, kind="table"))
    return tables


def inside(block: RawBlock, table: RawBlock) -> bool:
    """A text block belongs to a table if its centre lies within the table's box."""
    x0, y0, x1, y1 = block.bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    tx0, ty0, tx1, ty1 = table.bbox
    return tx0 - TABLE_PAD <= cx <= tx1 + TABLE_PAD and ty0 - TABLE_PAD <= cy <= ty1 + TABLE_PAD


def is_prose(block: RawBlock) -> bool:
    letters = sum(ch.isalpha() for ch in block.text)
    return len(block.text) >= 80 and letters / len(block.text) >= 0.6


def find_gutter(blocks: list[RawBlock], width: float) -> float | None:
    """x position of a column gutter: no block crosses it and both sides hold
    at least three prose blocks. Narrow numeric blocks (unruled tables) don't count."""
    for x in [width * f / 100 for f in range(35, 66)]:
        if any(b.bbox[0] < x < b.bbox[2] for b in blocks):
            continue
        left = [b for b in blocks if b.bbox[2] <= x and is_prose(b)]
        right = [b for b in blocks if b.bbox[0] >= x and is_prose(b)]
        if len(left) >= 3 and len(right) >= 3:
            return x
    return None


def order_blocks(blocks: list[RawBlock], width: float) -> tuple[list[RawBlock], bool]:
    """Reading order. Single column: top to bottom, then left to right. Two columns:
    the whole left column, then the whole right column. Returns (blocks, two_columns)."""
    gutter = find_gutter(blocks, width)
    if gutter is None:
        return sorted(blocks, key=lambda b: (round(b.bbox[1]), b.bbox[0])), False
    left = sorted((b for b in blocks if b.bbox[2] <= gutter), key=lambda b: b.bbox[1])
    right = sorted((b for b in blocks if b.bbox[0] >= gutter), key=lambda b: b.bbox[1])
    return left + right, True


def classify_heading(block: RawBlock, body_size: float) -> int:
    """0 = not a heading; 1 = PART; 2 = ITEM; 3 = other heading.

    10-K headings are usually bold at body size (font size alone doesn't work),
    so: short, and bold or clearly larger than body text. Level 3 also excludes
    digits, which keeps bold table captions like 'Year Ended December 25, 2021' out.
    """
    if block.kind != "text" or len(block.text) > 150:
        return 0
    styled = block.bold or block.max_size >= body_size * 1.2
    if PART_HEADING.match(block.text) and len(block.text) <= 40:
        return 1
    if ITEM_HEADING.match(block.text) and styled:
        return 2
    letters = sum(ch.isalpha() for ch in block.text)
    if (styled and len(block.text.split()) >= 2 and not re.search(r"\d", block.text)
            and letters / len(block.text) >= 0.7 and not block.text.endswith((".", ",", ";"))
            and not block.text.startswith("(")):
        return 3
    return 0


def body_font_size(pages: list[list[RawBlock]]) -> float:
    sizes = Counter()
    for blocks in pages:
        for b in blocks:
            sizes[round(b.max_size, 1)] += len(b.text)
    return sizes.most_common(1)[0][0] if sizes else 10.0


def signature_page(doc: pymupdf.Document) -> int | None:
    for page in doc:
        if SIGNATURE_STATEMENT.search(normalise(page.get_text())):
            return page.number + 1
    return None


def parse_pdf(path: Path, doc_key: str, source_sha256: str) -> ParsedDocument:
    started = time.perf_counter()
    doc = pymupdf.open(path)
    raw_pages = [extract_page_blocks(page) for page in doc]
    heights = [page.rect.height for page in doc]
    edge_keys = find_edge_keys(raw_pages, heights)
    body_size = body_font_size(raw_pages)
    sig = signature_page(doc)

    stats = Counter()
    ordered_pages: list[list[RawBlock]] = []
    with pdfplumber.open(path) as plumber:
        for page, blocks, plumber_page in zip(doc, raw_pages, plumber.pages):
            kept = []
            for b in blocks:
                if in_edge_band(b, page.rect.height) and edge_key(b.text) in edge_keys:
                    stats["edge_blocks_removed"] += 1
                else:
                    kept.append(b)
            tables = find_tables(page, plumber_page)
            if tables:
                before = len(kept)
                kept = [b for b in kept if not any(inside(b, t) for t in tables)]
                stats["blocks_replaced_by_tables"] += before - len(kept)
                stats["tables"] += len(tables)
                stats["table_pages"] += 1
            ordered, two_columns = order_blocks(kept + tables, page.rect.width)
            # A bare number closing the page is a page number even outside the edge
            # band (Corning 2021 prints it right under the last paragraph).
            if ordered and ordered[-1].kind == "text" and PAGE_NUMBER.match(ordered[-1].text):
                ordered = ordered[:-1]
                stats["page_number_blocks_removed"] += 1
            stats["two_column_pages"] += two_columns
            ordered_pages.append(ordered)

    parts: list[str] = []
    pages: list[Page] = []
    blocks: list[Block] = []
    section: list[tuple[int, str]] = []  # (level, heading text) stack
    offset = 0
    for page, ordered in zip(doc, ordered_pages):
        page_number = page.number + 1
        page_start = None  # offset of this page's first block, set when it is appended
        for raw in ordered:
            level = classify_heading(raw, body_size)
            kind = "heading" if level else raw.kind
            if level:
                section = [s for s in section if s[0] < level] + [(level, raw.text)]
                stats["headings"] += 1
            if parts:
                parts.append(BLOCK_SEPARATOR)
                offset += len(BLOCK_SEPARATOR)
            start = offset
            if page_start is None:
                page_start = start
            parts.append(raw.text)
            offset += len(raw.text)
            blocks.append(Block(len(blocks), page_number, start, offset, kind, level,
                                tuple(text for _, text in section), raw.bbox, raw.text))
        pages.append(Page(page_number, offset if page_start is None else page_start, offset,
                          round(page.rect.width, 2), round(page.rect.height, 2),
                          "after_signatures" if sig and page_number > sig else "body"))

    stats.update({"pages": doc.page_count, "blocks": len(blocks), "chars": offset,
                  "body_font_size": body_size, "signature_page": sig or 0,
                  "parse_seconds": round(time.perf_counter() - started, 1)})
    return ParsedDocument(doc_key, source_sha256, PARSER_VERSION, "".join(parts), pages, blocks, dict(stats))
