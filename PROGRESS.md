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
