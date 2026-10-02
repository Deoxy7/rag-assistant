"""Data shapes produced by parsing and consumed by chunking and storage.

The one rule everything else depends on: every offset indexes into
ParsedDocument.text, the document's single canonical extracted text, so that
`doc.text[b.char_start:b.char_end] == b.text` holds for every block (and, from
Phase 3, for every chunk). Citations and PDF highlighting rely on it.
"""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Page:
    page_number: int        # 1-based, as a human reads it
    char_start: int         # first character of this page's text in ParsedDocument.text
    char_end: int           # one past the last character (char_start == char_end for an empty page)
    width: float            # PDF points (1/72 inch)
    height: float
    region: str             # "body" or "after_signatures"


@dataclass(frozen=True)
class Block:
    index: int              # position in reading order across the whole document
    page_number: int
    char_start: int
    char_end: int
    kind: str               # "text", "heading" or "table"
    heading_level: int      # 1 = PART, 2 = ITEM, 3 = other heading, 0 = not a heading
    section: tuple[str, ...]  # headings above this block, outermost first (includes itself if a heading)
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points, origin top-left
    text: str


@dataclass
class ParsedDocument:
    doc_key: str
    source_sha256: str
    parser_version: str
    text: str
    pages: list[Page]
    blocks: list[Block]
    stats: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "ParsedDocument":
        return cls(
            doc_key=data["doc_key"],
            source_sha256=data["source_sha256"],
            parser_version=data["parser_version"],
            text=data["text"],
            pages=[Page(**p) for p in data["pages"]],
            blocks=[Block(**{**b, "section": tuple(b["section"]), "bbox": tuple(b["bbox"])}) for b in data["blocks"]],
            stats=data.get("stats", {}),
        )

    def page_of(self, char_offset: int) -> int:
        """1-based page containing a character offset (binary search over page starts)."""
        lo, hi = 0, len(self.pages) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.pages[mid].char_start <= char_offset:
                lo = mid
            else:
                hi = mid - 1
        return self.pages[lo].page_number
