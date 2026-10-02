"""Vector search: the k chunks whose embeddings are nearest the question's.

Three ways to apply metadata filters, because filtering interacts badly with
approximate search (card #18):

    post       HNSW finds the ef_search nearest vectors, *then* the filter runs.
               Fast; returns fewer than k rows when matches are rare.
    iterative  HNSW keeps walking the graph until k rows pass the filter
               (pgvector >= 0.8, hnsw.iterative_scan). The default.
    exact      no index: compute the distance to every row that passes the
               filter and sort. Perfect recall; cost grows with the rows scanned.
               (With no filter this is the brute-force ground truth for ANN recall.)
"""

from dataclasses import dataclass

import psycopg
from psycopg import sql

from app.retrieve.types import Filters, Hit
from app.telemetry.trace import stage
from app.store.repository import vector_literal

FILTER_MODES = ("post", "iterative", "exact")


@dataclass
class VectorRetriever:
    embedder: object          # anything with .key, .dims, .embed_query(text)
    chunk_set_id: int
    # pgvector's default is 40 (recall@10 0.928 here); 160 reaches 0.996 for
    # about +0.5 ms per query (scripts/bench_vector.py, 150 queries).
    ef_search: int = 160
    filter_mode: str = "iterative"

    def __post_init__(self):
        if self.filter_mode not in FILTER_MODES:
            raise ValueError(f"filter_mode must be one of {FILTER_MODES}")

    def query_sql(self, filters: Filters, exact: bool) -> sql.Composed:
        # Chunk set and model are written into the SQL as literals, not bound
        # parameters: the planner can only use the *partial* HNSW index if it
        # can prove `chunk_set_id = 1 AND model = '…'` matches the index's WHERE
        # at planning time, and a generic plan for `chunk_set_id = $1` can't.
        distance = sql.SQL("e.embedding::vector({dims}) <=> %(q)s::vector({dims})").format(
            dims=sql.Literal(self.embedder.dims))
        # `+ 0` turns the ORDER BY into an expression the index can't produce,
        # forcing an exact scan over the rows that pass the WHERE clause.
        order = sql.SQL("({d}) + 0").format(d=distance) if exact else distance
        where = [sql.SQL("e.chunk_set_id = {s}").format(s=sql.Literal(self.chunk_set_id)),
                 sql.SQL("e.model = {m}").format(m=sql.Literal(self.embedder.key))]
        if filters.companies:
            where.append(sql.SQL("d.company = ANY(%(companies)s)"))
        if filters.fiscal_years:
            where.append(sql.SQL("d.fiscal_year = ANY(%(years)s)"))
        return sql.SQL("""
            SELECT c.id, d.doc_key, d.company, d.fiscal_year, c.page_number, c.page_end,
                   c.char_start, c.char_end, c.section, c.text, {distance} AS distance
            FROM embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE {where}
            ORDER BY {order}
            LIMIT %(k)s""").format(distance=distance, where=sql.SQL(" AND ").join(where), order=order)

    def search(self, conn: psycopg.Connection, query: str, k: int = 10,
               filters: Filters | None = None, query_vector=None) -> list[Hit]:
        with stage("retrieve.vector"):     # includes retrieve.vector.embed (nested stage)
            return self._search(conn, query, k, filters, query_vector)

    def _search(self, conn: psycopg.Connection, query: str, k: int = 10,
                filters: Filters | None = None, query_vector=None) -> list[Hit]:
        filters = filters or Filters()
        with stage("retrieve.vector.embed"):
            vec = query_vector if query_vector is not None else self.embedder.embed_query(query)
        exact = self.filter_mode == "exact"
        params = {"q": vector_literal(vec), "k": k,
                  "companies": list(filters.companies or []), "years": list(filters.fiscal_years or [])}
        with conn.transaction():
            # Both settings are set on *every* search. SET LOCAL lasts until the end
            # of the top-level transaction, and conn.transaction() inside an already
            # open transaction is only a savepoint — so a setting left by an earlier
            # search on the same connection would otherwise leak into this one.
            conn.execute(sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(self.ef_search)))
            conn.execute(sql.SQL("SET LOCAL hnsw.iterative_scan = {}").format(
                sql.Literal("relaxed_order" if self.filter_mode == "iterative" else "off")))
            rows = conn.execute(self.query_sql(filters, exact), params).fetchall()
        # relaxed_order can return rows slightly out of order; sort by true distance.
        rows.sort(key=lambda r: r[-1])
        return [Hit(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(r[8]), r[9],
                    score=1.0 - float(r[10]), rank=i + 1) for i, r in enumerate(rows)]
