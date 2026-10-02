# 16 — Rapid revision

**Status:** started in Phase 0 (2026-10-02); every phase adds its must-know numbers and flashcards. Final form (Phase 16): one-page architecture recall, the 12 numbers to know cold, 40 flashcards, the 10 highest-probability questions, and the 5 sentences that make you sound like you built it.

---

## One-page architecture recall

```text
 PDF ─▶ Parse ─▶ Chunk ─▶ Embed ─▶ [ Postgres: text · vectors · keywords ]
                                          │            │
 Question ─▶ API ─▶ vector search ◀───────┘   keyword search
                         └────────▶ RRF ◀──────────┘
                                     ▼
                              Rerank ─▶ LLM ─▶ answer + citations (or refusal)
```

## Numbers to know cold (so far)

| Number | Value | Unit | Produced by |
|---|---|---|---|
| Postgres version | 16.15 | — | `SELECT version()` |
| pgvector version | 0.8.7 | — | `\dx` / `tests/test_db_smoke.py` |
| Database ready from stopped | 5.76 | s | `/usr/bin/time -p make up` |
| Colima VM size | 2 CPU · 2 | GB RAM | `colima start --cpu 2 --memory 2` |
| Bytes per 384-dim float vector | 1,536 | bytes | 384 × 4 (arithmetic) |
| Corpus | 10 × 10-K · 5 companies · FY2021+2022 | — | `data/manifest.json` |
| Corpus pages / table pages / scanned | 2,224 / 606 / 0 | pages | `make inspect` |
| Corpus size in LLM tokens | 1,415,012 | `o200k_base` tokens | `make inspect` |
| FinanceBench questions on our filings | 28 of 150 | questions | FinanceBench open-source set |
| Parsed blocks / tables / headings | 30,327 / 1,073 / 2,655 | blocks | `make parse` |
| Parse time, whole corpus | 3 min 4 s | — | `make parse` (no cache) |
| Max chunk size | 510 | bge-small tokens | 512 − [CLS] − [SEP] |
| Chunks at 256 tokens (fixed / recursive / structure) | 5,604 / 6,538 / 7,411 | chunks | `python -m app.ingest.chunk_corpus` |
| Embedding speed (M1) | MPS 116 / CPU 46 | chunks/s | benchmark, batch 64 |
| Default ingest from empty | 80.2 | s | `make ingest` |
| Distinct texts / chunks (structure/256) | 6,812 / 7,411 | — | SQL |
| HNSW index (7,411 vectors) | 13.8 MB, 1.4 s build, 2.6 ms query | — | `make ingest`, EXPLAIN |
| HNSW recall@10 vs exact (ef 40 / 160) | 0.928 / 0.996 | — | `make bench-vector` |
| Exact vs HNSW latency (7,411 vectors) | 11.4 vs 3.4 | ms p50 | same |
| Recall cliff, post-filter (forced, 6.9% filter) | 3.8 rows avg, 31/150 zero, recall 0.379 | — | same |
| FinanceBench hit@10 (28 q): vector / ts_rank / BM25 | 0.357 / 0.143 / 0.071 | — | `make bench-keyword` |
| Keyword latency p50: ts_rank / BM25 | 31.5 / 71.6 | ms | same |
| Retrieval metrics, latencies | not yet measured | | Phases 11, 13 |

## Flashcards (Phase 0)

| Q | A |
|---|---|
| What does RAG stand for, in one sentence? | Retrieval-Augmented Generation: retrieve relevant passages at question time and have the LLM answer from them, with citations. |
| Parametric vs non-parametric memory? | In the model's weights vs in an external, searchable, citable index. |
| Does RAG eliminate hallucination? | No — it reduces it; retrieval can fetch the wrong passage, and the model can misread the right one. |
| Why not long-context stuffing? | Cost ∝ corpus tokens on every question, latency grows with prompt length, lost-in-the-middle, hard window limit. |
| What does pgvector add? | A `vector` type, distance operators (`<->`, `<=>`, `<#>`), HNSW and IVFFlat indexes. |
| Why is `<#>` negative? | Every operator is a distance (smaller = closer); negating the dot product keeps ORDER BY ASC = nearest first. |
| Cosine distance of [1,2,3] and [2,4,6]? | 0 — same direction; cosine ignores length. |
| Container vs VM? | Container = processes on the host kernel (namespaces + cgroups); VM = own kernel on a hypervisor. |
| Why pin the image by digest? | Tags can be re-pushed; a digest is a content hash and can never change. |
| Why does a changed `POSTGRES_PASSWORD` break logins? | The image applies it only when initialising an empty volume. |
| Why autocommit in the test fixture? | One expected SQL error would otherwise abort the shared transaction for every later test. |
| What's the workload contract? | Size, change rate, QPS, permissions, citations, what to do when unsure, which latency matters. |
| p50 vs mean? | p50 is the median request; the mean is dragged by the tail and hides it. |
| What's odd about PepsiCo's PDFs? | ~400 of ~500 pages are exhibits after the signature page. |
| What's odd about Corning's? | Financial statements come *after* the signatures; 2021 is full of non-breaking spaces (2.64 chars/token). |
| Why two years per company? | Hard negatives: near-identical text, different facts — tests wrong-year retrieval. |
| The offset invariant? | `doc.text[b.char_start:b.char_end] == b.text` for every block (30,327/30,327). |
| Why normalise before offsets? | NFKC can change length; offsets must index the stored text. |
| Parser's known weakness? | Table column headers above the ruled area end up outside the table block. |
| Three chunkers? | fixed (token windows), recursive (LangChain, ¶→line→sentence), structure (whole blocks per section). |
| Why not LangChain's start_index? | It subtracts token overlap from a character position → -1. |
| Why cut windows between words? | Mid-word slices re-tokenize differently (257 ≠ 256). |
| Cosine for unit vectors? | = dot product; L2² = 2 − 2cos, so all three rank identically. |
| Why a separate embeddings table? | Multiple models per chunk; per-model partial HNSW; side-by-side upgrades. |
| Why partial HNSW per chunk set? | A shared index would post-filter ANN results → fewer than k (recall cliff). |
| What repeats between years? | 5–17% of FY2022 chunks are identical to an FY2021 chunk → identical vectors. |
| Recall cliff fix? | Iterative index scan (pgvector 0.8) — 10 rows, recall 0.973. |
| Why literals for chunk set/model? | Generic plans can't prove a partial index predicate with $params. |
| SET LOCAL gotcha? | Lasts to the end of the top-level transaction; nested transaction = savepoint. |
| Why OR in keyword search? | plainto_tsquery ANDs all words: 1 match vs 2,808. |
| Why phrase for 16,434? | Parser splits at the comma into 16 and 434. |
| Default keyword ranking? | ts_rank — BM25 built, measured, not better here; ts_rank_cd fooled by repetition. |
| Stemming quirk? | "Corning" → `corn`. |

## Top questions so far

P0-01 (RAG vs fine-tuning), P0-04 (pgvector vs vector DB), P0-07 (workload contract) — see [02-question-map.md](02-question-map.md).
