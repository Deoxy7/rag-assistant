"""Phase 2: the parser. Synthetic PDFs pin each rule; three real filings pin the
invariants and the specific facts docs/05-pdf-parsing.md quotes.

Real documents (chosen for their quirks):
  AMD_2021_10K      clean EDGAR-style filing, bold Item headings, ruled financial tables
  CORNING_2021_10K  non-breaking spaces everywhere, merged blocks, financials after signatures
  VERIZON_2022_10K  dense pages, running header + page-number footer on every page
"""

from pathlib import Path

import pymupdf
import pytest

from app.ingest import pdf_parser
from app.ingest.models import ParsedDocument
from app.ingest.parse_corpus import load_or_parse, manifest_documents

LOREM = ("Revenue grew because demand for our products increased across every region and "
         "segment during the fiscal year, which management attributes to pricing. ")


def build_pdf(tmp_path: Path, pages: list, name: str = "t.pdf") -> Path:
    """Each item of `pages` is a function(page) that draws on a fresh Letter page."""
    doc = pymupdf.open()
    for draw in pages:
        draw(doc.new_page(width=612, height=792))
    path = tmp_path / name
    doc.save(path)
    return path


def parse(path: Path) -> ParsedDocument:
    return pdf_parser.parse_pdf(path, "TEST", "0" * 64)


def assert_offsets_exact(doc: ParsedDocument) -> None:
    for b in doc.blocks:
        assert doc.text[b.char_start:b.char_end] == b.text, f"block {b.index} offsets wrong"
    starts = [b.char_start for b in doc.blocks]
    assert starts == sorted(starts)
    assert all(a.char_end <= b.char_start for a, b in zip(doc.blocks, doc.blocks[1:])), "blocks overlap"


# --- synthetic rules ----------------------------------------------------------

def test_normalise_folds_non_breaking_spaces_and_ligatures():
    assert pdf_parser.normalise("Table\xa0of\xa0Contents  ﬁnance\n") == "Table of Contents finance"


def test_offsets_index_the_canonical_text(tmp_path):
    def page(p):
        p.insert_textbox(pymupdf.Rect(72, 100, 540, 300), "Item 7. Results\xa0of operations", fontname="hebo", fontsize=11)
        p.insert_textbox(pymupdf.Rect(72, 320, 540, 700), LOREM * 3, fontsize=10)
    doc = parse(build_pdf(tmp_path, [page]))
    assert_offsets_exact(doc)
    assert "\xa0" not in doc.text
    assert doc.pages[0].char_start == 0 and doc.pages[0].char_end == len(doc.text)


def test_running_header_and_footer_are_removed(tmp_path):
    def page_n(n):
        def draw(p):
            p.insert_text((72, 30), "ACME Corp Annual Report")            # header band
            p.insert_text((300, 770), f"{n}")                              # footer band, varying number
            p.insert_textbox(pymupdf.Rect(72, 100, 540, 700), LOREM * 2, fontsize=10)
        return draw
    doc = parse(build_pdf(tmp_path, [page_n(i) for i in range(1, 7)]))
    assert not any("ACME Corp" in b.text for b in doc.blocks)
    assert not any(b.text.isdigit() for b in doc.blocks)
    assert doc.stats["edge_blocks_removed"] == 12


def test_blank_lines_split_a_merged_block(tmp_path):
    # One text box = one PyMuPDF block; a line holding only a non-breaking
    # space must still end the paragraph (the Corning 2021 pattern).
    def page(p):
        p.insert_textbox(pymupdf.Rect(72, 100, 540, 300), "First paragraph here.\n\xa0\nSecond paragraph here.", fontsize=10)
    doc = parse(build_pdf(tmp_path, [page]))
    assert [b.text for b in doc.blocks] == ["First paragraph here.", "Second paragraph here."]


def test_heading_levels_and_section_path(tmp_path):
    def page(p):
        p.insert_textbox(pymupdf.Rect(72, 60, 540, 80), "PART II", fontname="hebo", fontsize=10)
        p.insert_textbox(pymupdf.Rect(72, 90, 540, 110), "Item 7. Management's Discussion and Analysis", fontname="hebo", fontsize=10)
        p.insert_textbox(pymupdf.Rect(72, 120, 540, 140), "Liquidity and Capital Resources", fontname="hebo", fontsize=10)
        p.insert_textbox(pymupdf.Rect(72, 150, 540, 400), LOREM * 2, fontsize=10)
        p.insert_textbox(pymupdf.Rect(72, 410, 540, 430), "(In millions, except per share amounts)", fontname="hebo", fontsize=10)
    doc = parse(build_pdf(tmp_path, [page]))
    levels = {b.text: b.heading_level for b in doc.blocks}
    assert levels["PART II"] == 1
    assert levels["Item 7. Management's Discussion and Analysis"] == 2
    assert levels["Liquidity and Capital Resources"] == 3
    assert levels["(In millions, except per share amounts)"] == 0  # caption, not a heading
    body = next(b for b in doc.blocks if b.text.startswith("Revenue grew"))
    assert body.section == ("PART II", "Item 7. Management's Discussion and Analysis", "Liquidity and Capital Resources")


def test_two_columns_are_read_left_column_first(tmp_path):
    def page(p):
        for i in range(4):
            p.insert_textbox(pymupdf.Rect(40, 80 + i * 150, 290, 220 + i * 150), f"LEFT{i} " + LOREM, fontsize=9)
            p.insert_textbox(pymupdf.Rect(322, 80 + i * 150, 572, 220 + i * 150), f"RIGHT{i} " + LOREM, fontsize=9)
    doc = parse(build_pdf(tmp_path, [page]))
    order = [b.text.split()[0] for b in doc.blocks]
    assert order == ["LEFT0", "LEFT1", "LEFT2", "LEFT3", "RIGHT0", "RIGHT1", "RIGHT2", "RIGHT3"]
    assert doc.stats["two_column_pages"] == 1


def test_ruled_table_becomes_one_table_block(tmp_path):
    def page(p):
        rows = [["Segment", "2022", "2021"], ["Data Center", "$ 6,043", "$ 3,694"], ["Client", "6,201", "6,887"]]
        x, y, w, h = 72, 200, 150, 20
        for r in range(len(rows) + 1):
            p.draw_line((x, y + r * h), (x + 3 * w, y + r * h))
        for c in range(4):
            p.draw_line((x + c * w, y), (x + c * w, y + len(rows) * h))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                p.insert_text((x + c * w + 4, y + r * h + 14), cell, fontsize=9)
    doc = parse(build_pdf(tmp_path, [page]))
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 1
    assert tables[0].text == "Segment | 2022 | 2021\nData Center | $ 6,043 | $ 3,694\nClient | 6,201 | 6,887"
    assert not any(b.kind == "text" and "Data Center" in b.text for b in doc.blocks)


def test_clean_table_merges_lone_currency_cells():
    assert pdf_parser.clean_table([["Net revenue", "$", "16,434", "", None, "$", "9,763"]]) == "Net revenue | $ 16,434 | $ 9,763"


def test_page_of_maps_offsets_to_pages(tmp_path):
    pages = [lambda p, i=i: p.insert_textbox(pymupdf.Rect(72, 100, 540, 700), f"Page body {i}. " + LOREM, fontsize=10) for i in range(3)]
    doc = parse(build_pdf(tmp_path, pages))
    for b in doc.blocks:
        assert doc.page_of(b.char_start) == b.page_number


# --- three real filings -------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    entries = {e["doc_key"]: e for e in manifest_documents()}
    return {key: load_or_parse(entries[key]) for key in ("AMD_2021_10K", "CORNING_2021_10K", "VERIZON_2022_10K")}


@pytest.mark.parametrize("key", ["AMD_2021_10K", "CORNING_2021_10K", "VERIZON_2022_10K"])
def test_real_offsets_are_exact_and_pages_consistent(real, key):
    doc = real[key]
    assert_offsets_exact(doc)
    assert [p.page_number for p in doc.pages] == list(range(1, len(doc.pages) + 1))
    for b in doc.blocks:
        page = doc.pages[b.page_number - 1]
        assert page.char_start <= b.char_start and b.char_end <= page.char_end
        assert doc.page_of(b.char_start) == b.page_number
    assert "\xa0" not in doc.text


def test_amd_income_statement_table(real):
    doc = real["AMD_2021_10K"]
    table = next(b for b in doc.blocks if b.kind == "table" and b.page_number == 51)
    assert table.text.splitlines()[0] == "Net revenue | $ 16,434 | $ 9,763 | $ 6,731"
    assert table.section[:2] == ("PART II", "ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA")


def test_amd_item_headings_in_reading_order(real):
    doc = real["AMD_2021_10K"]
    items = [b.text.split(".")[0].upper() for b in doc.blocks if b.heading_level == 2]
    expected = ["ITEM " + n for n in ["1", "1A", "1B", "2", "3", "4", "5", "6", "7", "7A", "8",
                                      "9", "9A", "9B", "9C", "10", "11", "12", "13", "14", "15", "16"]]
    assert items == expected


def test_corning_quirks_are_handled(real):
    doc = real["CORNING_2021_10K"]
    assert not any(b.text == "Table of Contents" for b in doc.blocks)       # running header gone
    assert sum(p.region == "after_signatures" for p in doc.pages) == 65     # pages 61-125
    statement = next(b for b in doc.blocks if b.text.startswith("Consolidated Statements of Income"))
    assert doc.pages[statement.page_number - 1].region == "after_signatures"  # kept, not dropped


def test_verizon_running_header_removed(real):
    doc = real["VERIZON_2022_10K"]
    assert not any("Annual Report on Form 10-K" in b.text and len(b.text) < 60 for b in doc.blocks)
    assert doc.stats["edge_blocks_removed"] > 100
