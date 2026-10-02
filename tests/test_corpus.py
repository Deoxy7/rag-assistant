"""Phase 1: the corpus is exactly the pinned files, and the inspection logic is right.

Two kinds of test: the inspection functions on a synthetic PDF built here (so
every expected value is known by construction), and a few facts about the real
corpus that docs/04-corpus.md quotes — if a re-download changed them, the doc
would be wrong, so the test fails.
"""

import json
import re
from pathlib import Path

import pymupdf
import pytest

from scripts import fetch_corpus, inspect_corpus

REPO = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((REPO / "data" / "manifest.json").read_text())


# --- the pinned corpus --------------------------------------------------------

def test_manifest_lists_ten_10k_filings_for_five_companies_and_two_years():
    docs = MANIFEST["documents"]
    assert len(docs) == 10
    assert {d["form"] for d in docs} == {"10-K"}
    assert len({d["company"] for d in docs}) == 5
    assert {d["fiscal_year"] for d in docs} == {2021, 2022}
    assert len({d["doc_key"] for d in docs}) == 10


@pytest.mark.parametrize("entry", MANIFEST["documents"] + MANIFEST["auxiliary"], ids=lambda e: e["path"])
def test_every_file_is_present_and_matches_its_pinned_hash(entry):
    path = REPO / "data" / entry["path"]
    assert path.is_file(), f"{entry['path']} missing — run `make corpus`"
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert path.stat().st_size == entry["bytes"]
    assert fetch_corpus.sha256_of(path) == entry["sha256"]


# --- inspection logic on a synthetic PDF -------------------------------------

@pytest.fixture
def synthetic_pdf(tmp_path) -> Path:
    """7 pages: a running header on every page, a TOC, Item headings, an income
    statement on page 6, the signature statement on page 7, and one image-only page."""
    doc = pymupdf.open()
    bodies = [
        "Table of Contents\nItem 1. Business 2\nItem 7. MD&A 5\nSignatures 7",
        "Item 1. Business\n" + "We make widgets. " * 30,
        "",  # page 3: image only (see below)
        "Item 7. Management's Discussion and Analysis\n" + "Revenue grew. " * 30,
        "Item 7A. Quantitative and Qualitative Disclosures\n" + "Rates moved. " * 30,
        "Consolidated Statements of Income\nNet revenue 100\nNet income 10",
        "SIGNATURES\nPursuant to the requirements of Section 13 or 15(d) of the Securities Exchange Act of 1934, signed.",
    ]
    for body in bodies:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 30), "ACME Corp 2022 Annual Report")  # top band: running header
        if body:
            page.insert_textbox(pymupdf.Rect(72, 100, 540, 700), body, fontsize=10)
    # Fill page 3 with an image and no text, like a scanned page.
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    doc[2].insert_image(doc[2].rect, pixmap=pix)
    path = tmp_path / "synthetic.pdf"
    doc.save(path)
    return path


def test_page_stats_flags_near_empty_and_scanned_pages(synthetic_pdf):
    doc = pymupdf.open(synthetic_pdf)
    image_page = inspect_corpus.page_stats(doc[2])
    text_page = inspect_corpus.page_stats(doc[1])
    assert image_page["near_empty"] and image_page["scanned_suspect"]
    assert image_page["image_coverage"] == pytest.approx(1.0)
    assert not text_page["near_empty"] and not text_page["scanned_suspect"]


def test_items_found_reads_item_headings_at_line_starts(synthetic_pdf):
    found = inspect_corpus.items_found(pymupdf.open(synthetic_pdf))
    assert set(found) == {"1", "7", "7A"}
    assert found["7A"] == [5]
    assert found["1"] == [1, 2]  # the TOC line counts too: it starts a line


def test_signature_page_uses_the_legal_statement_not_the_word(synthetic_pdf):
    # Page 1 (the TOC) contains the word "Signatures"; only page 7 has the statement.
    assert inspect_corpus.signatures_page(pymupdf.open(synthetic_pdf)) == 7


def test_income_statement_page_skips_the_table_of_contents(synthetic_pdf):
    assert inspect_corpus.income_statement_page(pymupdf.open(synthetic_pdf)) == 6


def test_running_header_is_detected(synthetic_pdf):
    lines = dict(inspect_corpus.repeated_edge_lines(pymupdf.open(synthetic_pdf)))
    assert lines.get("ACME Corp # Annual Report") == 7  # digits collapsed to '#'


def test_normalised_collapses_non_breaking_spaces():
    assert inspect_corpus.normalised("Table\xa0of\xa0 Contents\n") == "Table of Contents"


# --- facts about the real corpus quoted in docs/04-corpus.md -----------------

def open_real(key: str) -> pymupdf.Document:
    return pymupdf.open(REPO / "data" / "pdfs" / f"{key}.pdf")


def test_real_page_counts():
    counts = {d["doc_key"]: open_real(d["doc_key"]).page_count for d in MANIFEST["documents"]}
    assert sum(counts.values()) == 2224
    assert counts["PEPSICO_2021_10K"] == 549
    assert counts["AMD_2021_10K"] == 118


def test_corning_puts_financial_statements_after_the_signatures():
    doc = open_real("CORNING_2021_10K")
    assert inspect_corpus.signatures_page(doc) == 60
    assert inspect_corpus.income_statement_page(doc) == 65


def test_corning_2021_text_is_full_of_non_breaking_spaces():
    text = "".join(p.get_text() for p in open_real("CORNING_2021_10K"))
    assert text.count("\xa0") == 65886


def test_only_verizon_ships_a_pdf_outline():
    with_outline = {d["doc_key"] for d in MANIFEST["documents"] if open_real(d["doc_key"]).get_toc()}
    assert with_outline == {"VERIZON_2021_10K", "VERIZON_2022_10K"}
