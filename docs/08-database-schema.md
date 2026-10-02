# 08 — Database schema

**Status:** not yet written — filled in Phase 4.

What this doc will cover: The documents, chunks and embeddings tables, the tsvector column and GIN index, the HNSW index, and migrations; real ingest timings and row counts.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #6, #7, #16, #17
7a. Prerequisite concepts — primary and foreign keys, B-tree vs GIN vs HNSW vs IVFFlat indexes, generated columns, migrations, transactions during ingestion, MVCC
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — row counts, `make ingest` time, index build time, table and index sizes
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: ER diagram, conceptual HNSW structure
