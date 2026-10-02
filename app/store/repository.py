"""Every SQL statement the ingestion path runs, in one place (Repository pattern).

Callers pass an open connection and plain Python objects; nothing outside this
module writes SQL against these tables. The store layer must not import the
ingest layer above it (tests/test_architecture.py), so documents and chunks are
accepted by shape — any object with the fields used below — not by type. Bulk inserts use COPY, which streams
rows in one round trip instead of one INSERT per row.
"""

import hashlib

import numpy as np
import psycopg
from psycopg import sql


HNSW_M = 16                # graph links per node (pgvector default)
HNSW_EF_CONSTRUCTION = 64  # candidate list size while building (pgvector default)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(vec: np.ndarray) -> str:
    """pgvector's text format: '[0.1,0.2,…]'. Python's float repr round-trips float32 exactly."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


# --- documents ------------------------------------------------------------------

def upsert_document(conn: psycopg.Connection, entry: dict, doc) -> tuple[int, str]:
    """Insert a document, or replace it if its PDF bytes or parser version changed.

    `doc` is a ParsedDocument (source_sha256, parser_version, text, pages, blocks).

    Returns (document_id, action) with action in {"unchanged", "inserted", "replaced"}.
    Replacing deletes the old row; ON DELETE CASCADE removes its pages, blocks,
    chunks and embeddings in the same transaction, so readers never see a mix.
    """
    row = conn.execute("SELECT id, source_sha256, parser_version FROM documents WHERE doc_key = %s",
                       (entry["doc_key"],)).fetchone()
    if row and row[1] == doc.source_sha256 and row[2] == doc.parser_version:
        return row[0], "unchanged"
    action = "inserted"
    if row:
        conn.execute("DELETE FROM documents WHERE id = %s", (row[0],))
        action = "replaced"
    doc_id = conn.execute(
        """INSERT INTO documents (doc_key, company, ticker, fiscal_year, form, source_sha256,
                                  parser_version, page_count, canonical_text)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (entry["doc_key"], entry["company"], entry["ticker"], entry["fiscal_year"], entry["form"],
         doc.source_sha256, doc.parser_version, len(doc.pages), doc.text),
    ).fetchone()[0]
    with conn.cursor().copy("COPY pages (document_id, page_number, char_start, char_end, width, height, region) FROM STDIN") as copy:
        for p in doc.pages:
            copy.write_row((doc_id, p.page_number, p.char_start, p.char_end, p.width, p.height, p.region))
    with conn.cursor().copy("COPY blocks (document_id, block_index, page_number, char_start, char_end, kind, heading_level, section, bbox) FROM STDIN") as copy:
        for b in doc.blocks:
            copy.write_row((doc_id, b.index, b.page_number, b.char_start, b.char_end, b.kind,
                            b.heading_level, list(b.section), list(b.bbox)))
    return doc_id, action


# --- chunks ---------------------------------------------------------------------

def get_or_create_chunk_set(conn: psycopg.Connection, strategy: str, size: int, overlap: int, tokenizer: str) -> int:
    """Look up first, insert only if missing: `INSERT … ON CONFLICT DO NOTHING`
    alone would consume an identity value on every re-run (we saw ids 1, 3)."""
    params = (strategy, size, overlap, tokenizer)
    found = conn.execute("SELECT id FROM chunk_sets WHERE strategy = %s AND chunk_size = %s "
                         "AND chunk_overlap = %s AND tokenizer = %s", params).fetchone()
    if found:
        return found[0]
    return conn.execute(
        """INSERT INTO chunk_sets (strategy, chunk_size, chunk_overlap, tokenizer) VALUES (%s, %s, %s, %s)
           ON CONFLICT (strategy, chunk_size, chunk_overlap, tokenizer)
           DO UPDATE SET strategy = EXCLUDED.strategy   -- no-op update so RETURNING works under a race
           RETURNING id""", params).fetchone()[0]


def has_chunks(conn: psycopg.Connection, chunk_set_id: int, document_id: int) -> bool:
    return conn.execute("SELECT EXISTS (SELECT 1 FROM chunks WHERE chunk_set_id = %s AND document_id = %s)",
                        (chunk_set_id, document_id)).fetchone()[0]


def insert_chunks(conn: psycopg.Connection, chunk_set_id: int, document_id: int, chunks: list) -> int:
    """`chunks` are Chunk objects from app/ingest/chunking.py."""
    with conn.cursor().copy("""COPY chunks (chunk_set_id, document_id, chunk_index, char_start, char_end,
                                            page_number, page_end, section, token_count, text, content_sha256)
                               FROM STDIN""") as copy:
        for c in chunks:
            copy.write_row((chunk_set_id, document_id, c.chunk_index, c.char_start, c.char_end, c.page_number,
                            c.page_end, list(c.section), c.token_count, c.text, sha256_text(c.text)))
    return len(chunks)


# --- embeddings -----------------------------------------------------------------

def reuse_embeddings(conn: psycopg.Connection, chunk_set_id: int, model: str) -> int:
    """Copy vectors from any chunk with identical text (same content_sha256) that
    already has one for this model — the embedding cache. Returns rows copied."""
    cur = conn.execute(
        """INSERT INTO embeddings (chunk_id, model, chunk_set_id, dims, embedding)
           SELECT DISTINCT ON (c.id) c.id, e.model, c.chunk_set_id, e.dims, e.embedding
           FROM chunks c
           JOIN chunks donor ON donor.content_sha256 = c.content_sha256 AND donor.id <> c.id
           JOIN embeddings e ON e.chunk_id = donor.id AND e.model = %(model)s
           WHERE c.chunk_set_id = %(set)s
             AND NOT EXISTS (SELECT 1 FROM embeddings x WHERE x.chunk_id = c.id AND x.model = %(model)s)
           ORDER BY c.id""",
        {"model": model, "set": chunk_set_id})
    return cur.rowcount


def chunks_missing_embeddings(conn: psycopg.Connection, chunk_set_id: int, model: str) -> list[tuple[int, str]]:
    return conn.execute(
        """SELECT c.id, c.text FROM chunks c
           WHERE c.chunk_set_id = %s
             AND NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.chunk_id = c.id AND e.model = %s)
           ORDER BY c.id""", (chunk_set_id, model)).fetchall()


def insert_embeddings(conn: psycopg.Connection, chunk_set_id: int, model: str,
                      chunk_ids: list[int], vectors: np.ndarray) -> int:
    dims = vectors.shape[1]
    with conn.cursor().copy("COPY embeddings (chunk_id, model, chunk_set_id, dims, embedding) FROM STDIN") as copy:
        for chunk_id, vec in zip(chunk_ids, vectors):
            copy.write_row((chunk_id, model, chunk_set_id, dims, vector_literal(vec)))
    return len(chunk_ids)


def refresh_text_stats(conn: psycopg.Connection, chunk_set_id: int) -> int:
    """Recompute BM25 statistics for one chunk set; returns the number of lexemes.

    ts_stat() takes a query *string* and returns, for every lexeme in the
    tsvectors it produces, ndoc = the number of rows containing it. The chunk set
    id is an integer from our own table, formatted with sql.Literal.
    """
    conn.execute("DELETE FROM lexeme_stats WHERE chunk_set_id = %s", (chunk_set_id,))
    conn.execute("DELETE FROM chunk_set_stats WHERE chunk_set_id = %s", (chunk_set_id,))
    inner = sql.SQL("SELECT tsv FROM chunks WHERE chunk_set_id = {}").format(sql.Literal(chunk_set_id))
    cur = conn.execute(sql.SQL("""INSERT INTO lexeme_stats (chunk_set_id, lexeme, df)
                                  SELECT {s}, word, ndoc FROM ts_stat({q})""").format(
        s=sql.Literal(chunk_set_id), q=sql.Literal(inner.as_string(conn))))
    conn.execute("""INSERT INTO chunk_set_stats (chunk_set_id, n_chunks, avg_length)
                    SELECT chunk_set_id, count(*), avg(length(tsv)) FROM chunks
                    WHERE chunk_set_id = %s GROUP BY chunk_set_id""", (chunk_set_id,))
    return cur.rowcount


def hnsw_index_name(chunk_set_id: int, model: str) -> str:
    return f"embeddings_hnsw_set{chunk_set_id}_{hashlib.sha1(model.encode()).hexdigest()[:8]}"


def ensure_hnsw_index(conn: psycopg.Connection, chunk_set_id: int, model: str, dims: int) -> tuple[str, bool]:
    """One partial HNSW index per (chunk set, model).

    The column is an untyped `vector` (dimensions vary by model), and HNSW needs
    a fixed dimension, so the index is on the expression embedding::vector(dims).
    The WHERE clause makes it *partial*: it holds only one configuration's
    vectors, so a search never has to filter out other configurations' rows
    (which is where approximate search loses results — card #18).
    Returns (index name, created_now).
    """
    name = hnsw_index_name(chunk_set_id, model)
    exists = conn.execute("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = %s)", (name,)).fetchone()[0]
    if exists:
        return name, False
    conn.execute(sql.SQL(
        """CREATE INDEX {name} ON embeddings
           USING hnsw ((embedding::vector({dims})) vector_cosine_ops)
           WITH (m = {m}, ef_construction = {ef})
           WHERE chunk_set_id = {set} AND model = {model}""").format(
        name=sql.Identifier(name), dims=sql.Literal(dims), m=sql.Literal(HNSW_M),
        ef=sql.Literal(HNSW_EF_CONSTRUCTION), set=sql.Literal(chunk_set_id), model=sql.Literal(model)))
    return name, True


def relation_sizes(conn: psycopg.Connection) -> list[tuple[str, int]]:
    """(name, bytes) for our tables (including their TOAST data) and indexes."""
    return conn.execute(
        """SELECT c.relname, pg_total_relation_size(c.oid) FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'i')
             AND c.relname NOT LIKE 'pg_%' ORDER BY 2 DESC""").fetchall()


# --- LLM response cache (migration 0003) -------------------------------------------

def llm_cache_get(conn: psycopg.Connection, key: str) -> tuple[str, int, int] | None:
    """(response_text, input_tokens, output_tokens) for a cached key, counting the hit; None if absent."""
    row = conn.execute("""UPDATE llm_cache SET hits = hits + 1 WHERE key = %s
                          RETURNING response_text, input_tokens, output_tokens""", (key,)).fetchone()
    return (row[0], row[1], row[2]) if row else None


def llm_cache_put(conn: psycopg.Connection, key: str, provider: str, model: str,
                  text: str, input_tokens: int, output_tokens: int) -> None:
    conn.execute("""INSERT INTO llm_cache (key, provider, model, response_text, input_tokens, output_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING""",
                 (key, provider, model, text, input_tokens, output_tokens))


# --- citation support -------------------------------------------------------------

def chunk_regions(conn: psycopg.Connection, chunk_id: int) -> list[tuple[int, tuple[float, float, float, float]]]:
    """(page_number, bbox) of every parsed block that overlaps the chunk's character span.

    Lets a citation be drawn on the PDF page: the chunk's span came from these
    blocks, and each block kept its PyMuPDF bounding box (x0, y0, x1, y1, points).
    """
    rows = conn.execute("""SELECT b.page_number, b.bbox FROM chunks c
                           JOIN blocks b ON b.document_id = c.document_id
                                        AND b.char_start < c.char_end AND b.char_end > c.char_start
                           WHERE c.id = %s ORDER BY b.block_index""", (chunk_id,)).fetchall()
    return [(r[0], tuple(r[1])) for r in rows]


# --- API reads ---------------------------------------------------------------------

def list_documents(conn: psycopg.Connection, chunk_set_id: int) -> list[dict]:
    rows = conn.execute("""SELECT d.doc_key, d.company, d.ticker, d.fiscal_year, d.form, d.page_count,
                                  count(c.id)
                           FROM documents d LEFT JOIN chunks c ON c.document_id = d.id AND c.chunk_set_id = %s
                           GROUP BY d.id ORDER BY d.company, d.fiscal_year""", (chunk_set_id,)).fetchall()
    keys = ("doc_key", "company", "ticker", "fiscal_year", "form", "pages", "chunks")
    return [dict(zip(keys, r)) for r in rows]


def known_companies(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT company FROM documents")}


def find_chunk_set(conn: psycopg.Connection, strategy: str, size: int, overlap: int, tokenizer: str) -> int | None:
    """The id of an existing chunk set, or None (readers must never create one)."""
    row = conn.execute("SELECT id FROM chunk_sets WHERE strategy = %s AND chunk_size = %s "
                       "AND chunk_overlap = %s AND tokenizer = %s", (strategy, size, overlap, tokenizer)).fetchone()
    return row[0] if row else None


# --- evaluation reads ----------------------------------------------------------------

def chunks_overlapping(conn: psycopg.Connection, chunk_set_id: int, doc_key: str,
                       char_start: int, char_end: int) -> list[tuple[int, str, int, int]]:
    """(chunk_id, doc_key, char_start, char_end) of every chunk in the set overlapping [char_start, char_end)."""
    return conn.execute("""SELECT c.id, d.doc_key, c.char_start, c.char_end FROM chunks c
                           JOIN documents d ON d.id = c.document_id
                           WHERE c.chunk_set_id = %s AND d.doc_key = %s
                             AND c.char_start < %s AND c.char_end > %s
                           ORDER BY c.id""", (chunk_set_id, doc_key, char_end, char_start)).fetchall()
