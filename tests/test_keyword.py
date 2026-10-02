"""Phase 6: keyword retrieval (Postgres FTS; ts_rank default, BM25 and ts_rank_cd alternatives) on hand-built chunks."""

import pytest

from app.ingest.chunking import Chunk
from app.ingest.models import Block, Page, ParsedDocument
from app.retrieve.keyword import KeywordRetriever, split_query
from app.retrieve.types import Filters
from app.store import repository as repo

TEXTS = {
    "ACME": [
        "Acme Acme Acme Acme subsidiaries: Acme Holding GmbH, Acme Hungary, Acme Japan.",   # common word, many times
        "Acme recorded a goodwill impairment of $1,200 million in the display segment.",     # the real answer
        "Net revenue | $ 16,434 | $ 9,763 | $ 6,731",
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
        "Acme launched the MI250X accelerator for data centers.",
        "Revenue grew because demand increased across every region.",
    ],
    "OTHER": [
        "Other Corp revenue grew in fiscal 2022.",
        "Other Corp has no goodwill.",
    ],
}


@pytest.fixture
def chunk_set(db):
    with db.transaction():
        set_id = repo.get_or_create_chunk_set(db, "fixed", 64, 8, "t")
        for key, texts in TEXTS.items():
            canonical = "\n\n".join(texts)
            doc = ParsedDocument(key, "0" * 64, "test", canonical, [Page(1, 0, len(canonical), 612, 792, "body")],
                                 [Block(0, 1, 0, len(canonical), "text", 0, ("S",), (0, 0, 1, 1), canonical)])
            entry = {"doc_key": key, "company": key.title(), "ticker": key, "fiscal_year": 2022, "form": "10-K"}
            doc_id, _ = repo.upsert_document(db, entry, doc)
            chunks, pos = [], 0
            for i, t in enumerate(texts):
                chunks.append(Chunk(i, pos, pos + len(t), 1, 1, ("S",), 10, t))
                pos += len(t) + 2
            repo.insert_chunks(db, set_id, doc_id, chunks)
        repo.refresh_text_stats(db, set_id)
    db.commit()
    return set_id


def texts(hits):
    return [h.text for h in hits]


def test_split_query_extracts_quoted_phrases_and_grouped_numbers():
    phrases, rest = split_query('What was "net revenue" of 16,434 in 2021?')
    assert phrases == ["net revenue", "16,434"]
    assert "2021" in rest and "16,434" not in rest and "net revenue" not in rest


def test_natural_questions_match_with_or_semantics(db, chunk_set):
    # With AND every word ("what", stop-worded; "did", "grow", "acme", "2022") would be required.
    hits = KeywordRetriever(chunk_set).search(db, "Did Acme revenue grow in 2022?", k=10)
    assert len(hits) >= 3


def test_grouped_numbers_must_match_as_a_phrase(db, chunk_set):
    hits = KeywordRetriever(chunk_set).search(db, "16,434", k=10)
    assert texts(hits) == ["Net revenue | $ 16,434 | $ 9,763 | $ 6,731"]


def test_stop_word_only_query_returns_nothing(db, chunk_set):
    assert KeywordRetriever(chunk_set).search(db, "what is it?", k=10) == []


def test_cover_density_is_fooled_by_repetition_but_ts_rank_and_bm25_are_not(db, chunk_set):
    # The subsidiary list repeats "Acme" four times in a row; ts_rank_cd rewards
    # that dense cluster of a query term. ts_rank (with length normalisation)
    # and BM25 (with IDF: "acme" is in most chunks) rank the real answer first.
    q = "Acme goodwill impairment"
    answer = "Acme recorded a goodwill impairment"
    assert KeywordRetriever(chunk_set, rank_function="ts_rank").search(db, q, k=1)[0].text.startswith(answer)
    assert KeywordRetriever(chunk_set, rank_function="bm25").search(db, q, k=1)[0].text.startswith(answer)
    assert KeywordRetriever(chunk_set, rank_function="ts_rank_cd").search(db, q, k=1)[0].text.startswith("Acme Acme")


def test_rare_tokens_and_item_numbers_are_found(db, chunk_set):
    assert texts(KeywordRetriever(chunk_set).search(db, "MI250X", k=1)) == ["Acme launched the MI250X accelerator for data centers."]
    assert KeywordRetriever(chunk_set).search(db, "Item 7A", k=1)[0].text.startswith("Item 7A.")


def test_filters_restrict_results(db, chunk_set):
    hits = KeywordRetriever(chunk_set).search(db, "revenue grew", k=10, filters=Filters(companies=("Other",)))
    assert hits and all(h.company == "Other" for h in hits)


@pytest.mark.parametrize("rank_function", ["bm25", "ts_rank", "ts_rank_cd"])
def test_every_rank_function_returns_ranked_hits(db, chunk_set, rank_function):
    hits = KeywordRetriever(chunk_set, rank_function=rank_function).search(db, "goodwill impairment", k=5)
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(a.score >= b.score for a, b in zip(hits, hits[1:]))


def test_stemming_quirk_corning_becomes_corn(db):
    # Documented false positive: the English stemmer maps "Corning" to the lexeme "corn".
    assert db.execute("SELECT to_tsvector('english', 'Corning')::text").fetchone()[0] == "'corn':1"
