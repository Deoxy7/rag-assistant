"""Phase 3: three chunkers, one invariant — offsets index the canonical text.

Hand-built documents pin each strategy's rules; AMD 2021 pins the properties
on real data (exact offsets, size limits, full coverage, no section mixing).
"""

import pytest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.embed.tokenizer import count_tokens, token_spans
from app.ingest import chunking
from app.ingest.models import Block, Page, ParsedDocument
from app.ingest.parse_corpus import load_or_parse, manifest_documents


def make_doc(parts: list[tuple[str, int, tuple[str, ...], str]]) -> ParsedDocument:
    """parts: (kind, heading_level, section, text), all on page 1."""
    text, blocks, offset = "", [], 0
    for i, (kind, level, section, body) in enumerate(parts):
        if text:
            text += "\n\n"
            offset += 2
        blocks.append(Block(i, 1, offset, offset + len(body), kind, level, section, (0, 0, 1, 1), body))
        text += body
        offset += len(body)
    return ParsedDocument("T", "0" * 64, "test", text, [Page(1, 0, len(text), 612, 792, "body")], blocks)


SENTENCE = "Revenue increased because demand for our products grew across every region. "


def assert_valid(doc: ParsedDocument, chunks: list[chunking.Chunk], size: int) -> None:
    for c in chunks:
        assert doc.text[c.char_start:c.char_end] == c.text
        assert c.token_count == count_tokens(c.text) <= size
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert [c.char_start for c in chunks] == sorted(c.char_start for c in chunks)


def covered(doc: ParsedDocument, chunks: list[chunking.Chunk]) -> bool:
    """Every non-whitespace character of the document is inside some chunk."""
    mask = bytearray(len(doc.text))
    for c in chunks:
        mask[c.char_start:c.char_end] = b"\x01" * (c.char_end - c.char_start)
    return all(mask[i] or ch.isspace() for i, ch in enumerate(doc.text))


# --- windows -------------------------------------------------------------------

def test_word_groups_keep_subword_pieces_together():
    text = "Net revenue $ 16,434"
    groups = chunking.word_groups(token_spans(text))
    assert [text[s:e] for s, e, _ in groups] == ["Net", "revenue", "$", "16,434"]
    assert groups[-1][2] == 4  # 16 | , | 43 | ##4


def test_windows_never_exceed_size_and_overlap_repeats_words():
    text = SENTENCE * 40
    windows = chunking.token_windows(token_spans(text), size=50, overlap=10)
    counts = [count_tokens(text[s:e]) for s, e in windows]
    assert max(counts) <= 50
    assert all(b[0] < a[1] for a, b in zip(windows, windows[1:]))  # consecutive windows overlap
    assert windows[0][0] == 0 and windows[-1][1] == len(text.rstrip())


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError, match="overlap"):
        chunking.token_windows([(0, 1)], size=10, overlap=10)


# --- factory -------------------------------------------------------------------

def test_factory_rejects_unknown_strategy_and_oversized_chunks():
    with pytest.raises(ValueError, match="unknown chunk strategy"):
        chunking.get_chunker("semantic", 256, 32)
    with pytest.raises(ValueError, match="510"):
        chunking.get_chunker("fixed", 512, 64)  # 512 + [CLS] + [SEP] would be truncated
    assert chunking.get_chunker("fixed", 510, 63).size == 510


# --- strategies on hand-built documents ---------------------------------------

ITEM7 = ("PART II", "Item 7. MD&A")
ITEM8 = ("PART II", "Item 8. Financial Statements")


def test_structure_starts_chunks_at_headings_and_keeps_heading_runs_together():
    doc = make_doc([
        ("heading", 1, ("PART II",), "PART II"),
        ("heading", 2, ITEM7, "Item 7. MD&A"),
        ("text", 0, ITEM7, SENTENCE * 2),
        ("heading", 2, ITEM8, "Item 8. Financial Statements"),
        ("text", 0, ITEM8, SENTENCE),
    ])
    chunks = chunking.StructureChunker(200, 20).chunk(doc)
    assert_valid(doc, chunks, 200)
    assert len(chunks) == 2
    assert chunks[0].text.startswith("PART II\n\nItem 7. MD&A\n\nRevenue")  # headings merged with their body
    assert chunks[1].text.startswith("Item 8. Financial Statements")
    assert chunks[1].section == ITEM8


def test_structure_never_mixes_sections():
    doc = make_doc([("text", 0, ITEM7, SENTENCE), ("text", 0, ITEM8, SENTENCE)])
    chunks = chunking.StructureChunker(200, 20).chunk(doc)
    assert len(chunks) == 2 and [c.section for c in chunks] == [ITEM7, ITEM8]


def test_structure_splits_an_oversized_block_with_overlap():
    doc = make_doc([("text", 0, ITEM7, SENTENCE * 30)])
    chunks = chunking.StructureChunker(60, 10).chunk(doc)
    assert_valid(doc, chunks, 60)
    assert len(chunks) > 1 and covered(doc, chunks)
    assert all(b.char_start < a.char_end for a, b in zip(chunks, chunks[1:]))


def test_fixed_ignores_structure():
    doc = make_doc([("text", 0, ITEM7, SENTENCE), ("text", 0, ITEM8, SENTENCE)])
    chunks = chunking.FixedSizeChunker(200, 20).chunk(doc)
    assert len(chunks) == 1 and "Item" not in chunks[0].text and "\n\n" in chunks[0].text


def test_langchain_start_index_is_wrong_for_token_lengths_and_ours_is_right():
    # Regression for T-019: LangChain subtracts chunk_overlap as characters when
    # computing start_index, so with a token length function it reports -1.
    text = " ".join(f"Sentence {i} talks about revenue and margins." for i in range(60))
    lc = RecursiveCharacterTextSplitter(chunk_size=40, chunk_overlap=20, length_function=count_tokens,
                                        add_start_index=True).create_documents([text])
    assert any(d.metadata["start_index"] == -1 for d in lc)
    doc = make_doc([("text", 0, ITEM7, text)])
    ours = chunking.RecursiveChunker(40, 20).chunk(doc)
    assert_valid(doc, ours, 40)
    assert covered(doc, ours)


# --- real document --------------------------------------------------------------

@pytest.fixture(scope="module")
def amd():
    return load_or_parse(next(e for e in manifest_documents() if e["doc_key"] == "AMD_2021_10K"))


@pytest.mark.parametrize("strategy", ["fixed", "recursive", "structure"])
def test_real_document_chunks_are_exact_bounded_and_complete(amd, strategy):
    chunks = chunking.get_chunker(strategy, 256, 32).chunk(amd)
    assert_valid(amd, chunks, 256)
    assert covered(amd, chunks)
    for c in chunks:
        assert c.page_number <= c.page_end
        assert amd.page_of(c.char_start) == c.page_number


def test_real_structure_chunks_stay_inside_one_item(amd):
    starts = [b.char_start for b in amd.blocks]
    import bisect
    for c in chunking.get_chunker("structure", 256, 32).chunk(amd):
        first = bisect.bisect_right(starts, c.char_start) - 1
        last = bisect.bisect_left(starts, c.char_end) - 1
        items = {amd.blocks[i].section[:2] for i in range(first, last + 1) if amd.blocks[i].kind != "heading"}
        assert len(items) <= 1, f"chunk {c.chunk_index} mixes {items}"
