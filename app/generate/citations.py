"""Turn the model's [n] markers into verifiable citations.

A citation is (chunk id, document, page range, character span) taken from the
stored chunk, never from the model's text. Three things are checked:

- markers that name a source number the prompt didn't contain (invalid);
- sentences that state something but cite nothing (uncited);
- which sources were cited at all (the UI shows only those).
"""

import re
from dataclasses import dataclass

from app.generate.prompt import Source

# [1]  [1][3]  [1, 3]  [1,3]  — a group of numbers inside one pair of brackets.
MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Sentence ends: . ! ? followed by space/end, or a line break. Decimal points
# ("19.5%") and abbreviations are not split because a space must follow.
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# Sentence-final punctuation followed by one or more marker groups.
TRAILING_MARKERS = re.compile(r"([.!?])((?:[ \t]*\[\d+(?:\s*,\s*\d+)*\])+)")


@dataclass(frozen=True)
class Citation:
    n: int
    chunk_id: int
    doc_key: str
    company: str
    fiscal_year: int
    page_number: int
    page_end: int
    char_start: int     # offsets into the document's canonical text (documents.canonical_text)
    char_end: int

    @property
    def label(self) -> str:
        pages = f"p. {self.page_number}" if self.page_end == self.page_number else f"pp. {self.page_number}–{self.page_end}"
        return f"{self.company} {self.fiscal_year} 10-K, {pages}"


@dataclass(frozen=True)
class CitationReport:
    citations: tuple[Citation, ...]       # one per distinct valid source number, in order of first use
    invalid_markers: tuple[int, ...]      # numbers with no such source
    uncited_sentences: tuple[str, ...]


def marker_numbers(text: str) -> list[int]:
    """All cited numbers in order of appearance, with repeats."""
    return [int(x) for group in MARKER.findall(text) for x in group.split(",")]


def sentences(text: str) -> list[str]:
    """Split into sentences; a fragment that is only markers ("[1][2]") belongs to the one before.

    Models write both "… $16.4 billion [1]." and "… $16.4 billion. [1]"; the second
    would otherwise split into an uncited claim and a "[1]" glued to the next sentence.
    """
    # "billion. [1] Margin" → "billion [1]. Margin": markers move before the full stop.
    text = TRAILING_MARKERS.sub(lambda m: m.group(2) + m.group(1), text)
    out: list[str] = []
    for s in (s.strip() for s in SENTENCE.split(text)):
        if not s:
            continue
        if out and not MARKER.sub("", s).strip(" .,;:"):
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(s)
    return out


def is_claim(sentence: str) -> bool:
    """Heuristic: a sentence worth citing has a digit or at least four words.

    Short connective lines ("In summary:") and list headers don't need a source.
    """
    bare = MARKER.sub("", sentence).strip()
    return bool(re.search(r"\d", bare)) or len(bare.split()) >= 4


def check_citations(answer: str, sources: tuple[Source, ...]) -> CitationReport:
    by_n = {s.n: s for s in sources}
    seen, cites, invalid = set(), [], []
    for n in marker_numbers(answer):
        if n not in by_n:
            if n not in invalid:
                invalid.append(n)
            continue
        if n in seen:
            continue
        seen.add(n)
        h = by_n[n].hit
        cites.append(Citation(n, h.chunk_id, h.doc_key, h.company, h.fiscal_year,
                              h.page_number, h.page_end, h.char_start, h.char_end))
    uncited = tuple(s for s in sentences(answer) if is_claim(s) and not MARKER.search(s))
    return CitationReport(tuple(cites), tuple(invalid), uncited)


def strip_invalid_markers(answer: str, sources: tuple[Source, ...]) -> str:
    """Remove numbers that name no source, so the reader never sees a dangling [9]."""
    valid = {s.n for s in sources}

    def fix(m: re.Match) -> str:
        keep = [x.strip() for x in m.group(1).split(",") if int(x) in valid]
        return f"[{', '.join(keep)}]" if keep else ""
    return MARKER.sub(fix, answer)
