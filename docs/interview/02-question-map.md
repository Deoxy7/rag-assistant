# 02 — Question map

**Status:** started in Phase 0 (2026-10-02); every phase adds its questions and the viva's weak spots. Progress: **14 / 150+** questions.

Every question in `docs/interview/` appears here (a test in `tests/test_docs_integrity.py` fails if one is missing). **Confidence** is yours to fill: 1 = can't answer, 3 = can answer level 1–2, 5 = survives level 4. Re-rate after each drill.

## All questions

| ID | Question | File | Topic | Round | Diff. | Confidence (1–5) | Last drilled |
|---|---|---|---|---|---|---|---|
| P0-01 | Why RAG instead of fine-tuning? | [03](03-fundamentals.md) | RAG basics | deep-dive, ML | 2 | | |
| P0-02 | Million-token context — why not put all documents in the prompt? | [03](03-fundamentals.md) | RAG basics | ML, deep-dive | 3 | | |
| P0-03 | Does RAG stop hallucination? | [03](03-fundamentals.md) | RAG basics | ML, viva | 3 | | |
| P0-04 | Why Postgres + pgvector instead of a vector DB? | [05](05-database-and-sql.md) | storage | deep-dive, backend | 3 | | |
| P0-05 | What does pgvector add? Why is `<#>` negative? | [05](05-database-and-sql.md) | storage | viva, backend | 3 | | |
| P0-06 | What breaks without autocommit in your tests? | [05](05-database-and-sql.md) | DBMS | backend, viva | 3 | | |
| P0-07 | What do you need to know about the workload first? | [06](06-system-design.md) | design | design (senior) | 4 | | |
| P0-08 | Why a monolith, not microservices? | [06](06-system-design.md) | design | design, backend | 3 | | |
| P0-09 | How would you run this in production? Is Compose enough? | [06](06-system-design.md) | ops | backend, design | 3 | | |
| P0-10 | Why didn't you just use LangChain? | [06](06-system-design.md) | tooling | deep-dive | 2 | | |
| P0-11 | Tests pass on your laptop, fail on a teammate's — debug it | [08](08-debugging-scenarios.md) | debugging | backend, deep-dive | 3 | | |
| P0-12 | Container healthy but every login fails — walk me through it | [08](08-debugging-scenarios.md) | debugging | backend, viva | 3 | | |
| P0-13 | Container vs VM; why Docker on a Mac needs a VM | [11](11-cs-core-touchpoints.md) | OS | viva, backend | 2 | | |
| P0-14 | How do you make a Python project reproducible? | [11](11-cs-core-touchpoints.md) | build/ops | backend, viva | 2 | | |

## Over-prepare these: the five hardest questions this build invites

Identified in Phase 0 as the questions you are least likely to answer well by the end. Each gets a full entry in the phase where its evidence exists, and a section in [14-honest-answers.md](14-honest-answers.md).

| # | Question | Needs | Lands in |
|---|---|---|---|
| H1 | "Hybrid beat dense by N points on ~50 questions you wrote. Is that real?" — paired significance tests (bootstrap / permutation), and how the golden set is biased | Phase 11–12 results | [07](07-evaluation.md) |
| H2 | "How do you know your LLM judge is right?" — agreement with hand labels (Cohen's κ), verbosity / position / self-preference bias | A hand-labelled sample (you label it) | [07](07-evaluation.md) |
| H3 | "Your query has `WHERE company = 'X'` and `LIMIT 5` but returns 2 rows. Why, and what is HNSW doing?" | Phase 5 measurements | [04](04-retrieval.md), [05](05-database-and-sql.md) |
| H4 | "A 10-K is re-filed with corrections. Where does the old version still live, and what does a query mid-update see?" — MVCC, HNSW + VACUUM, caches, idempotent re-ingest | Phase 4 ingest design | [05](05-database-and-sql.md), [06](06-system-design.md) |
| H5 | "Take your measured per-stage latencies to 1,000 QPS. What breaks first, and what does it cost?" | Phase 8 + 13 numbers | [06](06-system-design.md) |

## Weak-spot log (from the end-of-phase vivas)

Each viva's misses go here so they resurface. Format: phase · question asked · what was missing · doc section to re-read · re-test date.

| Phase | Viva question | What was missing | Re-read | Re-tested |
|---|---|---|---|---|
| 0 | (filled after the Phase 0 viva) | | | |
