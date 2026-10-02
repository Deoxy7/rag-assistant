# 10 — Keyword search

**Status:** not yet written — filled in Phase 6.

What this doc will cover: Postgres full-text search: tsvector, lexemes, ts_rank, phrase handling, and the queries where keywords beat vectors.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #21
7a. Prerequisite concepts — inverted index, tokenisation, stemming, stop words, tsvector and tsquery, ts_rank vs ts_rank_cd, BM25 intuition, phrase search, GIN
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — queries where keyword search wins vs vector search, query latency
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: full-text pipeline: text → lexemes → index → rank
