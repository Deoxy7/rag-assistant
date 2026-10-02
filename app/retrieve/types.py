"""Shapes shared by every retriever (vector, keyword, hybrid, rerank)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Filters:
    """Metadata restrictions applied to a search. None means 'no restriction'."""

    companies: tuple[str, ...] | None = None
    fiscal_years: tuple[int, ...] | None = None

    def is_empty(self) -> bool:
        return not self.companies and not self.fiscal_years


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    doc_key: str
    company: str
    fiscal_year: int
    page_number: int
    page_end: int
    char_start: int
    char_end: int
    section: tuple[str, ...]
    text: str
    score: float      # higher = better; meaning depends on the retriever
    rank: int         # 1-based position in this retriever's result list
