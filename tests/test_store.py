"""Phase 4: schema, repository and the ingest pipeline, against the rag_test database.

A FakeEmbedder (deterministic vectors from a hash of the text) keeps these fast;
the real model is exercised in tests/test_embedder.py.
"""

import hashlib

import numpy as np
import psycopg
import pytest

from app.ingest.models import Block, Page, ParsedDocument
from app.ingest.pipeline import ingest
from app.store import repository as repo
from app.store.migrate import apply_migrations


class FakeEmbedder:
    key = "fake-model@00000000"
    dims = 8

    def __init__(self):
        self.texts_embedded = 0

    def embed_documents(self, texts):
        self.texts_embedded += len(texts)
        rows = []
        for t in texts:
            v = np.frombuffer(hashlib.sha256(t.encode()).digest()[: self.dims * 4], dtype=np.uint32).astype(np.float32)
            rows.append(v / np.linalg.norm(v))
        return np.array(rows, dtype=np.float32)


SENTENCE = "Net revenue increased because demand for our products grew across every region. "


def make_doc(key: str, sha: str, paragraphs: int = 6, repeats: int = 3) -> tuple[dict, ParsedDocument]:
    """A two-page synthetic document; first half of the paragraphs on page 1."""
    text, blocks = "", []
    per_page = max(1, paragraphs // 2)
    for i in range(paragraphs):
        body = f"Paragraph {i}. " + SENTENCE * repeats
        start = len(text) + (2 if text else 0)
        text = (text + "\n\n" if text else "") + body
        blocks.append(Block(i, 1 if i < per_page else 2, start, start + len(body), "text", 0,
                            ("PART II", "Item 7. MD&A"), (0, 0, 1, 1), body))
    page1_end = blocks[per_page - 1].char_end
    pages = [Page(1, 0, page1_end, 612, 792, "body")]
    if paragraphs > per_page:
        pages.append(Page(2, blocks[per_page].char_start, len(text), 612, 792, "body"))
    entry = {"doc_key": key, "company": "Acme", "ticker": "ACM", "fiscal_year": 2022, "form": "10-K"}
    return entry, ParsedDocument(key, sha, "test", text, pages, blocks)


def count(db, table: str) -> int:
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_migrations_are_recorded_and_idempotent(db):
    assert apply_migrations(db) == []  # already applied by the fixture
    from app.store.migrate import MIGRATIONS
    names = [r[0] for r in db.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names == sorted(f.name for f in MIGRATIONS.glob("*.sql"))
    assert names[0] == "0001_documents_chunks_embeddings.sql"


def test_constraints_reject_inverted_offsets(db):
    entry, doc = make_doc("A", "a" * 64)
    with db.transaction():
        doc_id, _ = repo.upsert_document(db, entry, doc)
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            db.execute("INSERT INTO pages VALUES (%s, 99, 10, 5, 612, 792, 'body')", (doc_id,))


def test_ingest_end_to_end_and_rerun_is_a_no_op(db):
    emb = FakeEmbedder()
    docs = [make_doc("A", "a" * 64), make_doc("B", "b" * 64)]
    first = ingest(db, docs, "structure", 40, 8, emb)
    assert first.documents == {"A": "inserted", "B": "inserted"}
    # Each distinct chunk text is embedded exactly once (A and B are identical,
    # and repeated tail windows inside one document are identical too).
    assert first.chunks_inserted > 2
    distinct = db.execute("SELECT count(DISTINCT content_sha256) FROM chunks").fetchone()[0]
    assert first.embeddings_computed == distinct == emb.texts_embedded
    assert first.embeddings_computed + first.embeddings_reused == first.chunks_inserted
    assert count(db, "embeddings") == first.chunks_inserted
    assert first.index_created
    # Every stored chunk's text is exactly its slice of the document's canonical text.
    mismatches = db.execute("""SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id
                               WHERE substr(d.canonical_text, c.char_start + 1, c.char_end - c.char_start) <> c.text""").fetchone()[0]
    assert mismatches == 0
    # The generated tsvector column is filled by Postgres itself: every chunk whose
    # text contains "revenue" matches the stemmed query, and no other chunk does.
    fts, text = db.execute("""SELECT count(*) FILTER (WHERE tsv @@ to_tsquery('english', 'revenue')),
                                     count(*) FILTER (WHERE text ILIKE '%revenue%') FROM chunks""").fetchone()
    assert fts == text > 0

    before = emb.texts_embedded
    again = ingest(db, docs, "structure", 40, 8, emb)
    assert again.documents == {"A": "unchanged", "B": "unchanged"}
    assert (again.chunks_inserted, again.embeddings_computed, again.index_created) == (0, 0, False)
    assert emb.texts_embedded == before
    assert again.chunk_set_id == first.chunk_set_id


def test_changed_pdf_replaces_the_document_and_cascades(db):
    emb = FakeEmbedder()
    ingest(db, [make_doc("A", "a" * 64)], "structure", 40, 8, emb)
    old_chunks = count(db, "chunks")
    report = ingest(db, [make_doc("A", "c" * 64, paragraphs=3)], "structure", 40, 8, emb)
    assert report.documents == {"A": "replaced"}
    assert count(db, "documents") == 1
    assert count(db, "chunks") < old_chunks  # old chunks (and their embeddings) went with the old row
    assert count(db, "embeddings") == count(db, "chunks")


def test_identical_chunk_text_reuses_embeddings_across_chunk_sets(db):
    # Short paragraphs (one sentence) are never split, so the structure chunker
    # produces identical chunks whatever the overlap — a second chunk set with a
    # different overlap must reuse every vector and compute none.
    emb = FakeEmbedder()
    docs = [make_doc("A", "a" * 64, repeats=1)]
    first = ingest(db, docs, "structure", 40, 8, emb)
    computed_before = emb.texts_embedded
    second = ingest(db, docs, "structure", 40, 4, emb)
    assert first.chunk_set_id != second.chunk_set_id
    assert second.chunks_inserted == first.chunks_inserted
    assert (second.embeddings_reused, second.embeddings_computed) == (second.chunks_inserted, 0)
    assert emb.texts_embedded == computed_before


def test_chunk_set_ids_are_not_burned_by_reruns(db):
    ids = [repo.get_or_create_chunk_set(db, "fixed", 64, 8, "t") for _ in range(3)]
    ids.append(repo.get_or_create_chunk_set(db, "fixed", 128, 16, "t"))
    assert ids == [1, 1, 1, 2]


def test_partial_hnsw_index_serves_vector_queries(db):
    emb = FakeEmbedder()
    report = ingest(db, [make_doc("A", "a" * 64)], "structure", 40, 8, emb)
    db.execute("SET enable_seqscan = off")  # tiny table: force the planner to show it *can* use the index
    query = repo.vector_literal(emb.embed_documents(["revenue"])[0])
    plan = "\n".join(r[0] for r in db.execute(
        f"""EXPLAIN SELECT chunk_id FROM embeddings
            WHERE chunk_set_id = {report.chunk_set_id} AND model = '{emb.key}'
            ORDER BY embedding::vector(8) <=> '{query}'::vector(8) LIMIT 3"""))
    assert report.index_name in plan
    defn = db.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", (report.index_name,)).fetchone()[0]
    assert "USING hnsw" in defn and "vector_cosine_ops" in defn and "WHERE" in defn
