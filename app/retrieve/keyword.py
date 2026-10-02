"""Keyword search with Postgres full-text search over the generated `chunks.tsv`.

Two things differ from Postgres's defaults, both measured on this corpus
(ranking defaults to ts_rank; BM25 is implemented in SQL as an alternative):

1. OR, not AND. plainto_tsquery() ANDs every word, so the natural question
   "What was AMD's net revenue in 2021?" (amd & net & revenu & 2021) matched
   1 chunk and a long FinanceBench question matched 0. Words are OR-ed instead
   and ranking decides; 2,808 chunks match the OR form of that question.
2. Exact phrases are required. Text in "double quotes", and numbers written
   with thousands separators ("16,434", which the parser splits into 16 and
   434), become phrase queries that must match: '16' <-> '434'.
"""

import re
from dataclasses import dataclass

import psycopg
from psycopg import sql

from app.retrieve.types import Filters, Hit
from app.telemetry.trace import stage

RANK_FUNCTIONS = ("ts_rank", "bm25", "ts_rank_cd")
BM25_K1 = 1.2   # term-frequency saturation: the 2nd occurrence counts less than the 1st, the 10th barely
BM25_B = 0.75   # length normalisation: 0 = none, 1 = full
QUOTED = re.compile(r'"([^"]+)"')
GROUPED_NUMBER = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")


def split_query(question: str) -> tuple[list[str], str]:
    """(phrases that must match, remaining free text)."""
    phrases = QUOTED.findall(question)
    rest = QUOTED.sub(" ", question)
    phrases += GROUPED_NUMBER.findall(rest)
    rest = GROUPED_NUMBER.sub(" ", rest)
    return [p for p in phrases if p.strip()], rest


@dataclass
class KeywordRetriever:
    chunk_set_id: int
    # Measured (scripts/bench_keyword.py, 28 FinanceBench questions): ts_rank
    # hit@10 0.143 at 31 ms vs BM25 0.071 at 72 ms; both rank "goodwill
    # impairment Corning" correctly, ts_rank_cd does not. BM25 stays available
    # as an ablation option for Phase 12's larger golden set.
    rank_function: str = "ts_rank"
    # ts_rank normalization bit 1: divide by 1 + log(document length), so long
    # chunks don't win just by containing more words.
    normalization: int = 1

    def __post_init__(self):
        if self.rank_function not in RANK_FUNCTIONS:
            raise ValueError(f"rank_function must be one of {RANK_FUNCTIONS}")

    def tsquery_sql(self, phrases: list[str]) -> tuple[sql.Composed, sql.Composed]:
        """(match query, rank query).

        No phrases: both are the OR of the words. With phrases (quoted text,
        grouped numbers): a chunk must contain every phrase, and nothing else;
        the other words only *rank* the matches. An earlier version also required
        at least one other word to match (phrases && (w₁ | w₂ …)), so "What does
        the figure $404,381 represent in Boeing's FY2022 10-K?" matched nothing:
        the backlog table contains 404,381 but none of figure/represent/boeing/fy2022.
        """
        # plainto_tsquery normalises the words (stems, drops stop words) and
        # joins them with &; turning & into | on its text form gives OR.
        words = sql.SQL("replace(plainto_tsquery('english', %(rest)s)::text, '&', '|')::tsquery")
        parts = [sql.SQL("phraseto_tsquery('english', {})").format(sql.Placeholder(f"p{i}"))
                 for i in range(len(phrases))]
        if not parts:
            return words, words
        required = sql.SQL("({})").format(sql.SQL(" && ").join(parts))
        rank = sql.SQL("CASE WHEN numnode({w}) = 0 THEN {r} ELSE {r} || {w} END").format(w=words, r=required)
        return required, rank

    def bm25_sql(self, q: sql.Composable, where: list) -> sql.Composed:
        """BM25 over the GIN-matched candidates, computed in SQL.

        For each query lexeme t in chunk c:
            idf(t)   = ln(1 + (N - df + 0.5) / (df + 0.5))
            part(t)  = idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avg_len))
        score(c) = Σ part(t). tf = occurrences of t in c (positions in the tsvector);
        len = distinct lexemes in c (Postgres' length(tsvector)); N, df, avg_len
        from lexeme_stats / chunk_set_stats (refreshed at ingest).
        """
        return sql.SQL("""
            WITH q AS (SELECT {q} AS query),
            terms AS (SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', %(rest)s))) AS lexeme
                      UNION SELECT unnest(tsvector_to_array(to_tsvector('english', %(phrase_text)s)))),
            stats AS (SELECT n_chunks, avg_length FROM chunk_set_stats WHERE chunk_set_id = {s}),
            idf AS (SELECT t.lexeme, ln(1 + (s.n_chunks - coalesce(l.df, 0) + 0.5) / (coalesce(l.df, 0) + 0.5)) AS idf
                    FROM terms t CROSS JOIN stats s
                    LEFT JOIN lexeme_stats l ON l.chunk_set_id = {s} AND l.lexeme = t.lexeme),
            cand AS (SELECT c.id, c.tsv FROM q, chunks c JOIN documents d ON d.id = c.document_id WHERE {where}),
            scored AS (
                SELECT cand.id, sum(idf.idf * u.tf * ({k1} + 1)
                                    / (u.tf + {k1} * (1 - {b} + {b} * length(cand.tsv) / s.avg_length))) AS score
                FROM cand
                CROSS JOIN stats s
                CROSS JOIN LATERAL (SELECT lexeme, cardinality(positions) AS tf FROM unnest(cand.tsv)) u
                JOIN idf ON idf.lexeme = u.lexeme
                GROUP BY cand.id
                ORDER BY score DESC, cand.id
                LIMIT %(k)s)
            SELECT c.id, d.doc_key, d.company, d.fiscal_year, c.page_number, c.page_end,
                   c.char_start, c.char_end, c.section, c.text, scored.score
            FROM scored JOIN chunks c ON c.id = scored.id JOIN documents d ON d.id = c.document_id
            ORDER BY scored.score DESC, c.id""").format(
            q=q, s=sql.Literal(self.chunk_set_id), where=sql.SQL(" AND ").join(where),
            k1=sql.Literal(BM25_K1), b=sql.Literal(BM25_B))

    def search(self, conn: psycopg.Connection, question: str, k: int = 10,
               filters: Filters | None = None) -> list[Hit]:
        with stage("retrieve.keyword"):
            return self._search(conn, question, k, filters)

    def _search(self, conn: psycopg.Connection, question: str, k: int = 10,
                filters: Filters | None = None) -> list[Hit]:
        filters = filters or Filters()
        phrases, rest = split_query(question)
        params: dict = {"rest": rest, "k": k, "companies": list(filters.companies or []),
                        "years": list(filters.fiscal_years or [])}
        params.update({f"p{i}": p for i, p in enumerate(phrases)})
        params["phrase_text"] = " ".join(phrases)
        q, rank_q = self.tsquery_sql(phrases)
        # A question made only of stop words ("what is it?") has no lexemes: no results.
        if conn.execute(sql.SQL("SELECT numnode({q})").format(q=q), params).fetchone()[0] == 0:
            return []
        where = [sql.SQL("c.chunk_set_id = {}").format(sql.Literal(self.chunk_set_id)), sql.SQL("c.tsv @@ q.query")]
        if filters.companies:
            where.append(sql.SQL("d.company = ANY(%(companies)s)"))
        if filters.fiscal_years:
            where.append(sql.SQL("d.fiscal_year = ANY(%(years)s)"))
        if self.rank_function == "bm25":
            rows = conn.execute(self.bm25_sql(q, where), params).fetchall()
        else:
            rows = conn.execute(sql.SQL("""
                SELECT c.id, d.doc_key, d.company, d.fiscal_year, c.page_number, c.page_end,
                       c.char_start, c.char_end, c.section, c.text,
                       {rank}(c.tsv, q.rank_query, {norm}) AS score
                FROM (SELECT {q} AS query, {rq} AS rank_query) q, chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE {where}
                ORDER BY score DESC, c.id
                LIMIT %(k)s""").format(rank=sql.Identifier(self.rank_function), norm=sql.Literal(self.normalization),
                                        q=q, rq=rank_q, where=sql.SQL(" AND ").join(where)), params).fetchall()
        return [Hit(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(r[8]), r[9],
                    score=float(r[10]), rank=i + 1) for i, r in enumerate(rows)]
