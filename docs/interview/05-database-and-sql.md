# 05 — Database and SQL

**Status:** started in Phase 0 (2026-10-02). Questions are appended each phase. Planned coverage: the schema defended table by table and index choice per column (Phase 4); `EXPLAIN ANALYZE` on the real queries, read line by line (Phases 5–6); B-tree vs GIN vs HNSW; normalisation; isolation levels during ingestion; connection pooling (Phase 10); what happens to HNSW as rows are inserted; joins, window functions and CTEs on the real tables.

---

### Q: Why Postgres with pgvector instead of a vector database like Pinecone or Qdrant?
**ID:** P0-04 · **Round:** project deep-dive · backend screen  **Difficulty:** 3/5

**30-second answer.** "Because at this scale one database is simpler *and* more correct. Chunk text, vectors, the full-text index and metadata all live in Postgres, so updating a document is one transaction, a filter like 'only 2023 filings' is a SQL `WHERE`, and both halves of hybrid search run in one place. A dedicated vector DB pays off at hundreds of millions of vectors or very high query rates — not at ten documents."

**2-minute answer.** Walk the consistency argument: with two stores, a re-filed 10-K must be deleted and re-inserted in both, with no shared transaction — you need idempotent writes and a reconciliation job for the case where one write succeeds and the other fails. Then the scale arithmetic: a 384-dim float vector is 384 × 4 = 1,536 bytes, so a million vectors ≈ 1.5 GB raw — one node; a hundred million ≈ 154 GB — that's where a dedicated system starts to earn its keep. Close with the honest weakness: pgvector scales vertically, with no built-in sharding of the vector index. (Card #15.)

**If they push — level 2.** *"What does a vector DB do that pgvector can't?"* Horizontal sharding of the index, built-in quantisation options, sometimes better filtered-search performance, and multi-tenancy features at scale. Many of these are workload-dependent; I haven't benchmarked one against pgvector myself.

**If they push — level 3.** *"How would you migrate if you outgrew Postgres?"* Keep Postgres as the source of truth for text and metadata; stream changes (inserts, updates, deletes) to the vector DB; make writes idempotent by chunk id; read vectors from the vector DB and join metadata back by id. Run both in parallel and compare result sets before cutting over.

**If they push — level 4.** *"How do you keep them consistent during that streaming?"* At-least-once delivery with idempotent upserts gives eventual consistency; a periodic reconciliation compares id sets and re-sends drift. Exactly-once across two systems isn't available without distributed transactions, which I'd avoid. I haven't built this — it's the design I'd start from.

**Whiteboard it.**
```text
 one store:  BEGIN; DELETE old chunks; INSERT new chunks+vectors; COMMIT;  ← atomic
 two stores: write Postgres ✓ ──▶ write vector DB ✗  → drift; needs retry + reconcile
```

**Trap.** "pgvector doesn't scale" (or "vector DBs are always faster") without numbers. The defensible answer is about workload size and the cost of keeping two stores consistent.

**Bridge.** "…and keeping it in Postgres is also why I can do hybrid search with a single SQL round trip — want to see how RRF works?"

---

### Q: What does pgvector actually add to Postgres? Why does `<#>` return a negative number?
**ID:** P0-05 · **Round:** viva · backend screen  **Difficulty:** 3/5

**30-second answer.** "A `vector(n)` column type, distance operators — `<->` for L2, `<=>` for cosine distance, `<#>` for negative inner product — and two approximate-search index types, HNSW and IVFFlat. `<#>` is negated because every pgvector operator is a *distance*, where smaller means closer, so `ORDER BY … LIMIT k` always means nearest first. A bigger dot product means more similar, so negating it keeps that rule."

**2-minute answer.** Do the arithmetic from the smoke tests: L2 between [1,2,3] and [4,5,6] is √(9+9+9) = √27 ≈ 5.196; cosine distance between [1,2,3] and [2,4,6] is 0, because they point the same way — cosine ignores length; inner product of [1,2,3] and [4,5,6] is 32, returned as −32. Mention that the extension must be *enabled* per database (`CREATE EXTENSION vector`), that comparing vectors of different dimensions is an error (`different vector dimensions 3 and 2`), and that these exact values are asserted in `tests/test_db_smoke.py`.

**If they push — level 2.** *"When do cosine and inner product give the same ranking?"* When all vectors are normalised to length 1: then the dot product equals cosine similarity, and ordering by `<#>` or `<=>` gives identical results. Inner product skips the division by lengths, so it's slightly cheaper. Phase 4 decides whether we normalise (card #13).

**If they push — level 3.** *"How do indexes make `ORDER BY embedding <=> $1 LIMIT 5` fast?"* Without an index, Postgres computes the distance to every row and sorts — exact but linear in rows. An HNSW index walks a graph of near neighbours to find *approximately* the nearest ones, visiting a small fraction of rows. The index is built for one operator class, so an index on cosine distance doesn't serve an L2 query. (Phase 4–5.)

**If they push — level 4.** *"What's the index's memory footprint?"* Raw vectors are dims × 4 bytes each — 1,536 bytes at 384 dims — plus the graph's neighbour lists, which depend on the `m` parameter. I'll measure our actual index size in Phase 4 with `pg_relation_size`; I won't guess the overhead factor.

**Whiteboard it.**
```text
 a=[1,2,3]  b=[4,5,6]
 a<->b = √(3²+3²+3²) = 5.196      a<#>b = −(4+10+18) = −32
 a<=>[2,4,6] = 1 − cos(0°) = 0    smaller = closer, for every operator
```

**Trap.** Saying `<=>` returns cosine *similarity*. It returns cosine *distance* = 1 − similarity. Getting the sign or meaning wrong reverses your ranking.

**Bridge.** "That's also why the embedding model choice and normalisation are a decision card of their own."

---

### Q: Your test suite opens its connection with autocommit on. What would break without it?
**ID:** P0-06 · **Round:** backend screen · viva  **Difficulty:** 3/5

**30-second answer.** "In psycopg's default mode every statement joins one open transaction. One of my tests deliberately triggers an SQL error, which aborts that transaction — and Postgres then rejects every later statement on that connection with 'current transaction is aborted, commands ignored until end of transaction block'. With a shared connection, one expected error would fail every test after it. Autocommit makes each statement its own transaction."

**2-minute answer.** Show the real output (from [03 §5.7](../03-environment-and-infra.md#57-testsconftestpy-and-teststest_db_smokepy)): `DataException - different vector dimensions 3 and 2` followed by `InFailedSqlTransaction`. Explain the general rule: a transaction is all-or-nothing, so after an error Postgres won't let you continue as if nothing happened — you must `ROLLBACK`. Then the design choice: autocommit is right for independent read-only checks; *ingestion* in Phase 4 will deliberately use explicit transactions so a document's old chunks are replaced atomically.

**If they push — level 2.** *"Couldn't you use a fresh connection per test?"* Yes — that's cleaner isolation but costs a connection setup per test. For later tests that write data, I'd wrap each test in a transaction and roll it back at the end, which gives isolation without new connections.

**If they push — level 3.** *"What isolation level does Postgres use by default, and does it matter for ingestion?"* Read committed: each statement sees data committed before it began. For replacing a document's chunks in one transaction, readers see either the old set or the new set, never a mix — because the new rows aren't visible until commit. Stricter levels (repeatable read, serializable) matter when a transaction reads, decides, and writes based on what it read.

**If they push — level 4.** *"Could ingestion deadlock?"* Two transactions deadlock when each holds a lock the other needs. Concurrent re-ingestion of *the same* document could contend on its rows; I'd avoid it by ingesting documents sequentially or taking an advisory lock per document id. I haven't hit or tested this — Phase 4 runs ingestion single-threaded.

**Whiteboard it.**
```text
 autocommit off:  BEGIN ─ stmt ✓ ─ stmt ✗ ─ stmt ⛔ aborted … until ROLLBACK
 autocommit on:   [stmt ✓] [stmt ✗] [stmt ✓]   each its own transaction
```

**Trap.** "Autocommit is just faster." The point here is failure isolation, not speed.

**Bridge.** "Ingestion is where transactions really matter — re-ingesting a document is a delete-and-insert that must be atomic."
