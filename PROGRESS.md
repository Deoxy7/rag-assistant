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
