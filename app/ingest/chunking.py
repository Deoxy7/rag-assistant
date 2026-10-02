"""Three interchangeable chunkers behind one interface.

Every chunker takes a ParsedDocument and returns Chunks whose offsets index the
document's canonical text, so `doc.text[c.char_start:c.char_end] == c.text`
for every chunk, whatever the strategy. That invariant is what lets Phase 11
compare chunks from *different* strategies against the same evidence spans.

    fixed      token windows of exactly `size` tokens, ignoring all structure
    recursive  LangChain's recursive splitter: paragraph → line → sentence → word
    structure  whole blocks grouped within one section; a heading starts a chunk

Sizes are in embedding-model tokens (app/embed/tokenizer.py).
"""

import bisect
from dataclasses import dataclass
from typing import Protocol

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.embed.tokenizer import count_tokens, token_spans
from app.ingest.models import Block, ParsedDocument


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    char_start: int
    char_end: int
    page_number: int        # page where the chunk starts
    page_end: int           # page where it ends (chunks may cross a page break)
    section: tuple[str, ...]  # section path of the block where the chunk starts
    token_count: int        # embedding-model tokens, excluding [CLS]/[SEP]
    text: str


class Chunker(Protocol):
    name: str
    size: int
    overlap: int

    def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...


def make_chunk(doc: ParsedDocument, index: int, start: int, end: int, block_starts: list[int]) -> Chunk:
    text = doc.text[start:end]
    # The block containing `start` gives the section path (binary search over block starts).
    block = doc.blocks[max(0, bisect.bisect_right(block_starts, start) - 1)]
    return Chunk(index, start, end, doc.page_of(start), doc.page_of(end - 1), block.section,
                 count_tokens(text), text)


def word_groups(spans: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Group token spans into whole words: (char_start, char_end, n_tokens).

    A token that starts exactly where the previous one ended continues the same
    word ("16,434" → 16 | , | 43 | ##4). Windows are cut only between words:
    a slice starting mid-word re-tokenizes differently, so its token count would
    no longer match the window (a 256-token window measured 257).
    """
    groups: list[list[int]] = []
    for start, end in spans:
        if groups and start == groups[-1][1]:
            groups[-1][1] = end
            groups[-1][2] += 1
        else:
            groups.append([start, end, 1])
    return [tuple(g) for g in groups]


def token_windows(spans: list[tuple[int, int]], size: int, overlap: int) -> list[tuple[int, int]]:
    """Character ranges of windows holding at most `size` tokens of whole words;
    each window starts about `overlap` tokens before the previous one ended."""
    if overlap >= size:
        raise ValueError(f"overlap ({overlap}) must be smaller than size ({size})")
    words = word_groups(spans)
    windows: list[tuple[int, int]] = []
    first = 0
    while first < len(words):
        last, total = first, 0
        while last < len(words) and (total + words[last][2] <= size or last == first):
            total += words[last][2]
            last += 1
        windows.append((words[first][0], words[last - 1][1]))
        if last == len(words):
            break
        # Step back from `last` until about `overlap` tokens are repeated,
        # always moving forward at least one word.
        back, repeated = last, 0
        while back - 1 > first and repeated + words[back - 1][2] <= overlap:
            back -= 1
            repeated += words[back][2]
        first = back
    return windows


class FixedSizeChunker:
    """The baseline: windows of `size` tokens over the whole text, blind to
    pages, sections, tables and sentences."""

    name = "fixed"

    def __init__(self, size: int, overlap: int):
        self.size, self.overlap = size, overlap

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        starts = [b.char_start for b in doc.blocks]
        windows = token_windows(token_spans(doc.text), self.size, self.overlap)
        return [make_chunk(doc, i, s, e, starts) for i, (s, e) in enumerate(windows)]


class RecursiveChunker:
    """LangChain's RecursiveCharacterTextSplitter, measuring length in our tokens.

    It tries to split on paragraph breaks first, then lines, then sentence ends,
    then spaces, so pieces end at natural boundaries when possible. Its own
    start_index is wrong when length is measured in tokens (see chunk()), so we
    locate every chunk ourselves and fail loudly if one can't be found.
    """

    name = "recursive"

    def __init__(self, size: int, overlap: int):
        self.size, self.overlap = size, overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            length_function=count_tokens,
            separators=["\n\n", "\n", ". ", " ", ""],
            # Attach a separator to the piece it ends, so a sentence's full stop
            # stays with its sentence (the default starts the next chunk with ". ").
            keep_separator="end",
        )

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        starts = [b.char_start for b in doc.blocks]
        chunks = []
        previous = -1
        for i, text in enumerate(self.splitter.split_text(doc.text)):
            # Not LangChain's start_index: it computes the search position as
            # `index + previous_len - chunk_overlap`, i.e. it subtracts the
            # overlap as *characters*. Our overlap is in tokens (~4-5 chars each),
            # so its search starts after the real chunk start and returns -1.
            # Each chunk starts strictly after the previous one, so search from there.
            start = doc.text.find(text, previous + 1)
            if start < 0:
                raise ValueError(f"{doc.doc_key}: recursive chunk {i} not found in the canonical text")
            previous = start
            chunks.append(make_chunk(doc, i, start, start + len(text), starts))
        return chunks


class StructureChunker:
    """Section-aware: consecutive whole blocks from the same section, up to `size`
    tokens. A heading always starts a new chunk (so every chunk opens with its
    heading when it has one), and a block too big for one chunk — a long table
    or paragraph — is cut into token windows with overlap.
    """

    name = "structure"

    def __init__(self, size: int, overlap: int):
        self.size, self.overlap = size, overlap

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        starts = [b.char_start for b in doc.blocks]
        ranges: list[tuple[int, int]] = []
        group: list[Block] = []
        group_tokens = 0

        def flush() -> None:
            nonlocal group, group_tokens
            if group:
                ranges.append((group[0].char_start, group[-1].char_end))
            group, group_tokens = [], 0

        for block in doc.blocks:
            tokens = count_tokens(block.text)
            if tokens > self.size:
                flush()
                spans = [(s + block.char_start, e + block.char_start) for s, e in token_spans(block.text)]
                ranges.extend(token_windows(spans, self.size, self.overlap))
                continue
            # A heading (or a new PART/ITEM) closes the current chunk — but only once
            # the chunk holds body text. Otherwise "PART II", "ITEM 5…" and its first
            # paragraph would become three chunks of a few tokens each.
            has_body = any(b.kind != "heading" for b in group)
            new_section = bool(group) and block.section[:2] != group[-1].section[:2]
            if (has_body and (block.kind == "heading" or new_section)) or group_tokens + tokens > self.size:
                flush()
            group.append(block)
            group_tokens += tokens
        flush()
        return [make_chunk(doc, i, s, e, starts) for i, (s, e) in enumerate(ranges)]


CHUNKERS = {"fixed": FixedSizeChunker, "recursive": RecursiveChunker, "structure": StructureChunker}


def get_chunker(strategy: str, size: int, overlap: int) -> Chunker:
    """Factory: the only place a strategy name becomes a chunker object."""
    # The model reads embedding_max_tokens *including* [CLS] and [SEP]; a chunk
    # with more content tokens than that minus 2 would be silently truncated.
    limit = get_settings().embedding_max_tokens - 2
    if not 0 < size <= limit:
        raise ValueError(f"chunk size {size} must be between 1 and {limit} tokens (model limit minus [CLS]/[SEP])")
    try:
        cls = CHUNKERS[strategy]
    except KeyError:
        raise ValueError(f"unknown chunk strategy {strategy!r}; choose from {sorted(CHUNKERS)}") from None
    return cls(size, overlap)
