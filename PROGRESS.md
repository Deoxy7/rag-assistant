# PROGRESS

One section per phase. Read this, `CLAUDE.md` and `docs/02-architecture-overview.md` at the start of every session.

## Phase 0 — Foundations   [DONE 2026-10-02]

Built:    git repo; Python 3.11.9 venv with pinned `requirements.txt`; `.env.example`; `docker-compose.yml` (pgvector/pgvector:0.8.7-pg16-bookworm pinned by digest, bound to 127.0.0.1, healthcheck); `docker/initdb/001-extensions.sql`; `Makefile` (help, install, up, down, db-reset, psql, test, diagrams, cards, docs); `app/config.py` (pydantic-settings); `app/store/db.py`; docs tooling `scripts/render_diagrams.sh`, `scripts/where_it_sits.py`, `scripts/collect_cards.py`; `CLAUDE.md`, `README.md`.
Docs:     `docs/00-START-HERE.md`, `01-what-is-rag.md`, `02-architecture-overview.md`, `03-environment-and-infra.md` written in full; 04–20 and 22 scaffolded; `21-glossary.md` and `23-troubleshooting.md` started. `docs/interview/`: all 17 files created; 00, 01 (draft), 02 written; 14 questions (P0-01…P0-14) in 03, 05, 06, 08, 11; 09 generated with 7 cards; 10, 12, 14, 16 started.
Diagrams: `01-rag-vs-plain-prompting`, `02-system-architecture`, `02-request-lifecycle`, `03-local-dev-topology`, plus generated `01-where-it-sits`, `03-where-it-sits` — SVG + PNG in `docs/diagrams/out/`.
Cards:    #1 (RAG vs fine-tuning/long-context/prompting), #15 (pgvector vs vector DBs), #34 (plain Python vs LangChain/LlamaIndex), #39 (Compose vs managed vs bare metal); extras x-modular-monolith, x-colima, x-psycopg-plain-sql.
Tests:    `make test` — 238 passed in 0.23 s (test_db_smoke 9, test_config 4, test_architecture 2, test_tooling 11, test_docs_integrity 212 parametrized checks).
Numbers:  `make up` 0.67 s running / 5.76 s from stopped / 5.73 s on a fresh volume; Colima first start 13 min 17 s (VM image download), later starts 44 s; image 157 MB compressed / 650 MB on disk; 6 diagrams render in 9.7 s.
Decisions: generator/judge LLM = **OpenAI API** (user's choice; model chosen in Phase 9 from current pricing — note the API is billed per token, not free). Accepted changes A–G (see `CLAUDE.md`): evidence-span golden labels; `page_end` + canonical-text offsets + block bboxes; abstention metrics; LLM response cache; Colima; chunk sizes in tokens ≤ 512; LangChain = text splitter only. mermaid-cli 12 uses `--size 1800 -s 2` instead of `-w 1800`.
Open:     corpus confirmation (proposed: ~10 SEC 10-K PDFs, 5 companies × 2 years) — needed before Phase 1 downloads; embedding and reranker models (proposed bge-small-en-v1.5, ms-marco-MiniLM-L-6-v2) — Phase 4/8; the "16-day" deadline date; closed-book baseline row proposed for Phase 12.
Next:     Phase 1 — Corpus.

Note (2026-10-02, after Phase 0): the user waived the end-of-phase viva quizzes and per-phase stops ("Skip the questions, just complete the project"). Phases now run back to back.

## Phase 1 — Corpus   [DONE 2026-10-02]

Built:    `data/manifest.json` (10 × Form 10-K PDFs: PepsiCo, Verizon, Corning, AMD, Boeing × FY2021/FY2022, mirrored by FinanceBench; + FinanceBench question files; sha256-pinned); `scripts/fetch_corpus.py` (`make corpus`, certifi TLS, atomic .part downloads); `scripts/inspect_corpus.py` (`make inspect`); `.gitignore` keeps only the manifest from `data/`; `tests/test_corpus.py`, `tests/test_environment.py` (venv == requirements.txt); new pinned packages: pymupdf, pdfplumber, matplotlib, certifi, tiktoken.
Docs:     `docs/04-corpus.md`; 8 interview questions (P1-01…P1-08) in 03, 04, 06, 07, 08, 11; card #2.
Diagrams: `04-corpus-composition`, `04-document-anatomy`, generated `04-where-it-sits`; charts `04-pages-per-document.png`, `04-chars-per-page-histogram.png` (matplotlib).
Numbers:  2,224 pages; 6,128,300 chars; 1,415,012 o200k_base tokens; 606 table pages; 0 scanned; 35 near-empty; 1,142 pages after signature pages; Corning 2021: 65,886 non-breaking spaces, 2.64 chars/token; download 21.3 MB in 43 s; inspection 3 min 17 s.
Decisions: corpus = FinanceBench-mirrored 10-Ks (licence CC BY-NC 4.0 per HF card; GitHub repo has no licence file). Pages after the signature page are labelled, never dropped (Corning's financial statements live there). Text must be NFKC-normalised at parse time (non-breaking spaces).
Open:     Phase 2 must strip running headers ("Table of Contents" on up to 144/215 pages) and normalise whitespace before computing offsets.
Next:     Phase 2 — Parsing.

## Phase 2 — PDF parsing   [DONE 2026-10-02]

Built:    `app/ingest/models.py` (Page, Block, ParsedDocument; offset invariant; `page_of` binary search); `app/ingest/pdf_parser.py` (PyMuPDF line-level paragraphs, NFKC, running header/footer + page-number removal, pdfplumber tables, two-column ordering, PART/ITEM/bold headings, section paths, page regions, bboxes); `app/ingest/parse_corpus.py` (`make parse`, cache keyed by PDF sha256 + PARSER_VERSION 2.3); `tests/test_pdf_parser.py` (9 synthetic rule tests + 7 on AMD 2021, Corning 2021, Verizon 2022).
Docs:     `docs/05-pdf-parsing.md`; cards #4, #5; 8 interview questions (P2-01…P2-08); stories S-03, S-04.
Diagrams: `05-parsing-pipeline`, `05-page-to-blocks`, generated `05-where-it-sits`.
Numbers:  30,327 blocks, 2,655 headings, 1,073 tables; 1,334 header/footer + 1,275 page-number blocks removed; 0 two-column pages; offsets exact for 30,327/30,327 blocks; full parse 3 min 4 s; pdfplumber pre-filter measured at ~2% and removed.
Decisions: offsets into one NFKC-normalised canonical text per document, blocks joined by "\n\n"; pages after signatures tagged `after_signatures`, never dropped; level-3 headings exclude digits/parentheses.
Open:     table column headers above the ruled area fall outside table blocks (measure via table questions in Phase 11); unruled tables not detected; two-column logic only synthetically tested.
Next:     Phase 3 — Chunking.

## Phase 3 — Chunking   [DONE 2026-10-02]

Built:    `app/embed/tokenizer.py` (bge-small tokenizer pinned to revision 5c38ec7c, counts + offset mapping); `app/ingest/chunking.py` (Chunk; FixedSizeChunker, RecursiveChunker (LangChain splitter, own offsets), StructureChunker; word-boundary token windows; `get_chunker` factory rejecting size > 510); `app/ingest/chunk_corpus.py` (stats for 3 strategies × 128/256/510); settings `chunk_strategy`/`chunk_size`/`chunk_overlap`, model settings; `tests/test_chunking.py` (13 tests); pinned sentence-transformers 6.1.0, torch 2.14.1, transformers 5.18.0, langchain-text-splitters 1.1.2 (+ transitive).
Docs:     `docs/06-chunking.md`; cards #8, #9, #10; 8 interview questions (P3-01…P3-08).
Diagrams: `06-chunking-strategies`, `06-overlap-mechanics`, generated `06-where-it-sits`.
Numbers:  at 256 tokens: fixed 5,604 chunks, recursive 6,538 (p50 223), structure 7,411 (p50 196); at 128: 11,206 / 13,870 / 14,513; at 510: 2,809 / 3,042 / 4,183. Tokenizer: 1.18 M chars → 247,369 tokens in 0.5 s. All chunk offsets verified (`--check`).
Decisions: LangChain's `start_index` not used (unit bug); windows cut between whole words; separators kept at chunk end; heading runs merged with following body; default structure/256/32.
Open:     structure creates many tiny chunks for short sections (1,061 under 64 tokens at 256) — watch in Phase 12; parent-document retrieval deferred unless Phase 11 shows multi-chunk evidence.
Next:     Phase 4 — Embeddings + schema.

## Phase 4 — Embeddings + schema   [DONE 2026-10-02]

Built:    `app/store/migrations/0001_documents_chunks_embeddings.sql` (documents, pages, blocks, chunk_sets, chunks with generated tsvector + GIN, embeddings per (chunk, model)); `app/store/migrate.py` (`make migrate`); `app/store/repository.py` (all ingestion SQL, COPY, content-hash embedding reuse, partial expression HNSW index per chunk set + model); `app/embed/embedder.py` (bge-small on MPS, normalised, query instruction + LRU cache); `app/ingest/pipeline.py` (`make ingest`, idempotent, per-document transactions, distinct-text embedding); `tests/test_store.py` (7, against `rag_test`), `tests/test_embedder.py` (4); `db.connect(dbname=…)`.
Docs:     `docs/07-embeddings.md`, `docs/08-database-schema.md`; cards #6, #7, #11, #12, #13, #14, #16, #17; 8 interview questions (P4-01…P4-08).
Diagrams: `07-embedding-batch-flow`, `08-er-diagram`, `08-hnsw-concept`, generated `07-` and `08-where-it-sits`.
Numbers:  embedding MPS 116.4 vs CPU 45.7 chunks/s (Δ ≤ 3.3e-7); default ingest 80.2 s (6,812 computed, 599 reused); re-run 2.8 s; HNSW 13.84 MB built in 1.4 s, query 2.6 ms; GIN query 0.099 ms; FY2022 chunks identical to FY2021: 5–17% per company.
Decisions: separate embeddings table keyed by (chunk, model) with untyped vector + per-model partial HNSW (cosine, m=16, ef_construction=64); keep duplicate chunk rows, embed distinct text once; idempotent per-document batch ingest; pgvector Python adapter not needed (text literals + COPY).
Open:     confirm partial-index use with prepared statements (Phase 5); HNSW recall vs exact (Phase 5); embeddings.chunk_set_id equality not DB-enforced.
Next:     Phase 5 — Vector retrieval.

## Phase 5 — Vector retrieval   [DONE 2026-10-02]

Built:    `app/retrieve/types.py` (Filters, Hit); `app/retrieve/vector.py` (VectorRetriever: post / iterative / exact filter modes, literal chunk-set + model so the partial HNSW index survives generic plans, ef_search default 160, both HNSW settings SET LOCAL on every search); `scripts/bench_vector.py` (`make bench-vector`); `tests/test_vector.py` (6). Diagrams `09-vector-search-path`, `09-filter-modes`, chart `09-recall-vs-ef-search.png` rendered. Raw bench output: `docs/diagrams/bench_vector_2026-10-02.txt`.
Numbers:  recall@10 vs exact: ef_search 10/20/40/80/160/320 → 0.742/0.849/0.928/0.976/0.996/0.998 at 2.8–3.9 ms p50; exact scan 11.4 ms. Filter Corning 2021 (6.9%): planner pre-filters by itself (recall 1.0); with HNSW path forced, post-filter avg 3.8 rows, 31/150 queries return 0, recall 0.379; iterative 10 rows, recall 0.973. halfvec index 7.93 MB vs 13.87 MB at recall 0.925 vs 0.928; binary+rerank40 recall 0.572.
Bugs found (log as T-025, T-026 in docs/23): SET LOCAL leaks across searches because conn.transaction() inside an open transaction is a savepoint; psycopg auto-prepare (after 5 runs) caches plans so planner settings like enable_sort stop applying.
Docs:     `docs/09-vector-search.md`; cards #18, #19; 8 interview questions (P5-01…P5-08); T-025…T-027.
Next:     Phase 6 — Keyword retrieval.

## Phase 6 — Keyword retrieval   [DONE 2026-10-02]

Built:    `app/retrieve/keyword.py` (OR semantics, required phrases for quoted text and grouped numbers, ts_rank default, ts_rank_cd and BM25-in-SQL alternatives, metadata filters); migration `0002_text_stats.sql` (lexeme_stats, chunk_set_stats) + `repo.refresh_text_stats` (ts_stat) called by the pipeline; `scripts/bench_keyword.py` (`make bench-keyword`); `tests/test_keyword.py` (11).
Docs:     `docs/10-keyword-search.md`; card #21; 8 interview questions (P6-01…P6-08); story S-05; T-028…T-030.
Diagrams: `10-fts-pipeline`, generated `10-where-it-sits`.
Numbers:  AND vs OR: 1 vs 2,808 matches; FinanceBench 28 q hit@10: vector 0.357, ts_rank 0.143, ts_rank_cd 0.071, BM25 0.071; keyword found nothing vector missed; p50 ts_rank 31.5 ms, BM25 71.6 ms; BM25 worked example 16.895.
Decisions: ts_rank (normalisation 1) default after measuring; BM25 kept as ablation; phrase-required grouped numbers.
Open:     "FY22" vs "fiscal 2022" lexical mismatch (query rewriting not built); stemmer maps Corning → corn.
Next:     Phase 7 — Hybrid + RRF.

## Phase 7 — Hybrid retrieval + RRF   [DONE 2026-10-02]

Built:    `app/retrieve/hybrid.py` (`rrf` with deterministic tie-break, `weighted_fusion` (min-max), `HybridRetriever` at depth 50, `get_retriever` factory for `retrieval_mode` vector / keyword / hybrid); settings `retrieval_mode`, `rrf_k`, `retrieval_depth`; `scripts/bench_hybrid.py` (`make bench-hybrid`: FinanceBench 28 q + 50 rare exact-figure queries, k sweep, weighted sweep, latency); `tests/test_hybrid.py` (12).
Docs:     `docs/11-hybrid-rrf.md` (RRF derived by hand); cards #20, #22, #23; 8 interview questions (P7-01…P7-08); story S-06; T-031, T-032.
Diagrams: `11-rrf-fusion`, `11-rrf-worked-example`, generated `11-where-it-sits`.
Numbers:  exact figures hit@5: vector 0.00, keyword 1.00, hybrid 1.00 (hit@1 0.46, tie-break decided); FinanceBench hit@10: vector 0.357, keyword 0.143, hybrid RRF k=60 0.286 (k=1 0.357); hit@20 vector 0.429, hybrid 0.393 (all k); weighted α=0.5: FB hit@10 0.357, figures hit@5 0.98; p50 vector 3.6 ms (embedding cached), keyword 31.6, hybrid 48.5.
Decisions: hybrid RRF k=60 default — hybrid loses 2 of 28 FB questions (noise) but fixes exact figures; a reranker re-sorts the top-N next. Weighted α=0.5 competitive but its weight was picked on the test queries; both in the Phase 12 ablation.
Open:     interleaving pushes good vector hits down when keyword is noise (reranker should fix); searches run sequentially (concurrency not built); long questions make keyword search slow (269 ms max).
Next:     Phase 8 — cross-encoder reranking.

## Phase 8 — Reranking   [DONE 2026-10-02]

Built:    `app/retrieve/rerank.py` (`Reranker`: pinned CrossEncoder, device auto, max_length 512; `rerank` stable re-sort; `RerankingRetriever` wraps any retriever, fetches max(N, k); `retriever_from_settings` = retrieval_mode + optional rerank); settings `rerank_enabled`, `rerank_n` (10), `rerank_model` (cross-encoder/ms-marco-MiniLM-L6-v2 @ 233902d2), `rerank_model_revision`, `rerank_device`, `rerank_batch_size`, `rerank_max_length`; `scripts/bench_rerank.py` (`make bench-rerank`; flags --models, --ns, --device, --first, --oracle-filter); `tests/test_rerank.py` (8).
Docs:     `docs/12-reranking.md`; cards #24, #25, #26; 8 interview questions (P8-01…P8-08); story S-07; T-033, T-034.
Diagrams: `12-rerank-funnel`, `12-bi-vs-cross-encoder`, generated `12-where-it-sits`.
Numbers:  hybrid → +MiniLM N=10: figures hit@1 0.46 → 0.82; FB hit@1 0.036 → 0.107, hit@5 0.143 → 0.179, hit@10 0.286 (unchanged by construction). Ceiling N=10/20/50/100: 0.286/0.393/0.500/0.714; reranked FB@10 0.286/0.286/0.214/0.250. MiniLM p50 76.5/136.0/267.2/285.3 ms (MPS), 152.6/316.6/621.5/765.4 (CPU). bge-reranker-base N=10: 434.7 ms, FB@5 0.143, fig@1 0.88. Oracle filing filter: FB@10 0.607 (no rerank), MiniLM N=10 FB@5 0.464.
Decisions: rerank on, MiniLM, N=10 (never meaningfully worse than larger N; half the latency of 20); bigger reranker rejected (6× slower, no FB gain).
Open:     wrong-company/year hard negatives dominate FB misses → auto company/year filter from the question as a Phase 12 ablation; contextual chunk headers as another; background-run CPU slowdown (T-033) cause unconfirmed.
Next:     Phase 9 — generation + citations (OpenAI; key from .env or fake client).

## Phase 9 — Generation + citations   [DONE 2026-10-02, real-model numbers pending API key]

Built:    `app/generate/` — `prompt.py` (6-rule INSTRUCTIONS, REFUSAL_TOKEN, PROMPT_VERSION, o200k token counting, `pack_context` whole chunks under a budget, rank/sandwich order, numbered headers with company/year/PDF page/section), `citations.py` (marker parsing incl. marker-after-period, Citation with chunk id/doc/pages/char span, invalid-marker removal, uncited-claim flags), `llm.py` (OpenAIClient on the Responses API with streaming, store=False, temperature only if set; FakeLLM extractive + refusal; CachedLLM over Postgres; get_llm with MissingAPIKey, no silent fallback), `answer.py` (answer_question / stream_answer, refusal on no context or token); migration `0003_llm_cache.sql`; `repo.llm_cache_get/put`, `repo.chunk_regions`; settings llm_provider, openai_api_key (SecretStr), llm_model gpt-6-luna, prices, budget 3000, answer_top_k 10, context_order; `scripts/ask.py` (`make ask`), `scripts/bench_answer.py` (`make bench-answer`), `scripts/render_citation_example.py`; openai==3.23.0 + jiter pinned; `tests/test_generate.py` (30, incl. SDK against httpx.MockTransport).
Docs:     `docs/13-prompting-and-citations.md` (full real prompt printed); cards #27, #28, #29; 8 interview questions (P9-01…P9-08); T-035…T-037.
Diagrams: `13-context-assembly`, `13-citation-mapping`, `13-citation-on-page` (rendered PDF page with the cited block highlighted), generated `13-where-it-sits`.
Numbers:  (fake model = pipeline only) context tokens p50 2,144 / max 2,596 at k=10; 0 of 280 sources dropped by the 3,000 budget; input tokens p50 2,388 (≈ $0.00024/question at $0.10/1M, estimate); 0 invalid markers, 0 uncited claims on 26 fake answers; chunk spans == stored text 7,411/7,411; retrieval p50 130 ms in the pipeline. Real-model latency, faithfulness, citation precision, refusal accuracy: not yet measured (no OPENAI_API_KEY).
Decisions: gpt-6-luna from the pricing page (not yet exercised against the API); text + [n] markers over JSON (streams); temperature not sent by default; whole-chunk packing; PDF page numbers (not printed folios).
Open:     OPENAI_API_KEY needed for every real-model number; header tokens ≈ 18% of context; repeated tables (652 tokens) → de-dup ablation; exhibit-list noise; refusal score threshold waits for Phase 11.
Next:     Phase 10 — FastAPI /query with SSE, /documents, /health.

