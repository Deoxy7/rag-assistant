# 02 — Question map

**Status:** started in Phase 0 (2026-10-02); every phase adds its questions and the viva's weak spots. Progress: **46 / 150+** questions.

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
| P1-01 | What makes a good evaluation corpus? Why not a clean toy set? | [07](07-evaluation.md) | corpus/eval | ML, deep-dive | 3 | | |
| P1-02 | Why two years of the same company? | [04](04-retrieval.md) | retrieval | deep-dive, ML | 3 | | |
| P1-03 | Same text, 64% more tokens — how? | [03](03-fundamentals.md) | tokenisation | ML, viva | 3 | | |
| P1-04 | How do you version a dataset you can't commit? | [06](06-system-design.md) | data ops | backend, design | 3 | | |
| P1-05 | Signature page detected on p.2 — find the bug | [08](08-debugging-scenarios.md) | debugging | deep-dive, backend | 2 | | |
| P1-06 | CERTIFICATE_VERIFY_FAILED on macOS — debug it | [08](08-debugging-scenarios.md) | debugging | backend | 2 | | |
| P1-07 | What is FinanceBench and why use it? | [07](07-evaluation.md) | eval | ML | 3 | | |
| P1-08 | Detect scanned pages programmatically; cost? | [11](11-cs-core-touchpoints.md) | algorithms | viva, backend | 2 | | |
| P2-01 | How does a PDF store text? Why is extraction hard? | [03](03-fundamentals.md) | parsing | viva, backend | 2 | | |
| P2-02 | Offset → page: algorithm and complexity | [11](11-cs-core-touchpoints.md) | DSA | DSA, viva | 2 | | |
| P2-03 | Unicode normalisation; why before offsets? | [11](11-cs-core-touchpoints.md) | text | viva, backend | 3 | | |
| P2-04 | Headers removed everywhere but the largest doc — debug | [08](08-debugging-scenarios.md) | debugging | deep-dive, backend | 3 | | |
| P2-05 | One company's headings vanished — debug | [08](08-debugging-scenarios.md) | debugging | deep-dive | 3 | | |
| P2-06 | Avoid re-parsing; parse a million PDFs | [06](06-system-design.md) | scale | design, backend | 3 | | |
| P2-07 | Why tables matter for retrieval; your weakness | [04](04-retrieval.md) | retrieval | ML, deep-dive | 3 | | |
| P2-08 | How do you know the parser is good enough? | [07](07-evaluation.md) | eval | ML, deep-dive | 3 | | |
| P3-01 | How did you choose your chunking strategy? | [04](04-retrieval.md) | chunking | deep-dive, ML | 3 | | |
| P3-02 | What does overlap do; how much? | [04](04-retrieval.md) | chunking | ML, viva | 2 | | |
| P3-03 | Why 510 tokens, not 512? | [03](03-fundamentals.md) | tokenisation | ML, viva | 2 | | |
| P3-04 | Library offsets come back -1 — debug | [08](08-debugging-scenarios.md) | debugging | deep-dive, backend | 3 | | |
| P3-05 | 256-token window measures 257 — why? | [08](08-debugging-scenarios.md) | tokenisation | ML, DSA | 3 | | |
| P3-06 | Design patterns in the chunking code | [11](11-cs-core-touchpoints.md) | OOP | viva, backend | 2 | | |
| P3-07 | Chunk size vs cost and storage at scale | [06](06-system-design.md) | scale | design | 3 | | |
| P3-08 | Compare retrieval across chunkers fairly | [07](07-evaluation.md) | eval | ML | 4 | | |
| P4-01 | Walk me through your schema | [05](05-database-and-sql.md) | schema | backend, deep-dive | 3 | | |
| P4-02 | Partial + expression index for HNSW — why both? | [05](05-database-and-sql.md) | indexes | backend | 4 | | |
| P4-03 | How does GIN make full-text search fast? | [05](05-database-and-sql.md) | indexes | backend, viva | 3 | | |
| P4-04 | A filing is re-filed — what happens, what do readers see? (H4) | [05](05-database-and-sql.md) | consistency | design, backend | 4 | | |
| P4-05 | Ingestion for thousands of documents a day | [06](06-system-design.md) | scale | design | 4 | | |
| P4-06 | What is an embedding; why do similar meanings cluster? | [03](03-fundamentals.md) | embeddings | ML, viva | 2 | | |
| P4-07 | Why is the GPU 2.5× faster; same output? | [11](11-cs-core-touchpoints.md) | hardware | viva, ML | 2 | | |
| P4-08 | HNSW index exists but EXPLAIN shows seq scan | [08](08-debugging-scenarios.md) | debugging | backend | 3 | | |

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
| — | Vivas waived by the user on 2026-10-02 ("skip the questions"); self-rate the Confidence column instead | | | |
