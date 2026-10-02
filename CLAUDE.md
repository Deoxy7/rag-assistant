# CLAUDE.md — working rules for this repo

A document-grounded RAG assistant with a self-built eval harness, built phase by phase as a teaching project for a final-year student preparing for SDE / backend / ML-engineer interviews. **Two deliverables of equal weight: the working system, and `docs/` that teaches it.** The differentiator is eval rigour and an honest ablation table, not UI polish.

## At the start of every session

1. Read this file, `PROGRESS.md`, and `docs/02-architecture-overview.md`.
2. Check which phase is in progress and what its "Next" says. Do not start a new phase without the user saying "continue".

## Non-negotiable rules

- **Docs in the same phase as code.** A phase is done only when its doc exists, its diagrams render to SVG+PNG, and they are embedded. Never batch docs to the end.
- **No stubs, no TODOs, no `pass  # later`** in code. If it can't be finished this phase, it doesn't belong in it. (Doc *scaffolds* marked "Status: not yet written" are allowed.)
- **Every phase ends runnable and tested** — `make test` green — plus commits `feat(phase-N): …` and `docs(phase-N): …`.
- **Stop at every phase boundary.** Print: what was built, docs written, diagrams rendered, what's next, decisions needed. Wait for "continue".
- **Never invent numbers.** Every metric in docs comes from a command actually run, with the command and raw output. Unmeasured → "not yet measured — measured in Phase N". Placeholders in pitch drafts use ⟨angle brackets⟩ naming the phase.
- **Offsets are a hard schema requirement from Phase 2:** every chunk carries `page_number`, `char_start`, `char_end` (agreed: plus `page_end`; offsets index one canonical extracted text per document).
- **Pin every version** with `==` in `requirements.txt` (direct + transitive); record versions in the docs. Images pinned by tag + digest.
- **Ask before deviating** (library, schema, skipped step): propose, give the trade-off in two sentences, wait.
- **Explain, don't just do.** Every non-obvious line of code gets a doc paragraph: why it exists, what breaks without it.
- **Say "I'm not sure"** instead of confident filler; flag what a reviewer should double-check.
- **`docs/23-troubleshooting.md`:** append every real error immediately — text, cause, fix — marked *hit* or *reproduced*.

## Stack (pinned — ask before substituting)

Python 3.11 (`python3.11`; plain `python3` on this machine is 3.14) · FastAPI + Uvicorn, SSE · Postgres 16 + pgvector (0.8.7) + native FTS · LangChain **only** `langchain-text-splitters` (offsets tested) — everything else plain Python · sentence-transformers embeddings + cross-encoder reranker (models chosen in Phases 4/8; proposed `BAAI/bge-small-en-v1.5`, `cross-encoder/ms-marco-MiniLM-L-6-v2`) · PyMuPDF + pdfplumber · self-built eval harness · Streamlit (Phase 15) · Docker Compose for Postgres via **Colima**, app on host · pytest · Mermaid (`mmdc` 12) → SVG+PNG, Graphviz fallback · DB driver psycopg 3 with plain SQL · settings via pydantic-settings in `app/config.py` only.

**Generator / judge LLM: OpenAI API (user's choice).** Exact model picked in Phase 9 from OpenAI's *current* model list and pricing — don't guess from memory. The user supplies the key in `.env`; never print, log or type it.

## Agreed changes to the original plan (Phase 0)

- **A. Golden labels are evidence spans** (doc, page, char_start, char_end), not chunk ids — chunk ids change with every chunking config in the ablation. Relevance = overlap rule, defined and tested in Phase 11.
- **B. Offsets:** `page_number` (start) + `page_end`; char offsets into one stored canonical text per document; page → char-range table; store block bounding boxes in Phase 2.
- **C. Unanswerable questions** are scored with abstention metrics, not recall@k.
- **D. LLM response cache** keyed by hash of (model, prompt template version, params) for reproducible, cheap eval re-runs.
- **E. Colima** instead of Docker Desktop.
- **F. Chunk sizes in embedding-model tokens**, capped at the model's max input (512 for bge-small).
- **G. LangChain** = text splitter only.
- **Proposed for Phase 12:** add a closed-book (no retrieval) baseline row.
- `mmdc` 12 has no `-w`: PNGs use `--size 1800 -s 2 -b white -t neutral`.

## Repo map

`app/` (config, store; ingest/embed/retrieve/generate/api/telemetry arrive in their phases — no empty packages) · `tests/` · `scripts/` (render_diagrams.sh, where_it_sits.py, collect_cards.py) · `docker/initdb/` · `docs/` + `docs/diagrams/{src,out,build}` + `docs/interview/` · `eval/` (Phase 11; results never overwritten) · `data/` (git-ignored corpus).

Layering is enforced by `tests/test_architecture.py`: config ← telemetry ← store/embed ← ingest/retrieve ← generate ← api. Change the table deliberately, never to silence the test.

## Make targets

`make help` · `install` · `up` · `down` · `db-reset` (destructive) · `psql` · `test` (installs + starts DB) · `diagrams` · `cards` · `docs`. Targets are added in the phase that gives them something to do (`ingest` Phase 4, `eval` Phase 11).

## Diagrams

- Sources `docs/diagrams/src/NN-kebab-name.mmd` (NN = owning doc). Render with `make diagrams`; outputs (SVG + PNG + `manifest.tsv`) are committed. Tests fail if a source changed since rendering.
- "Where it sits" diagrams are **generated** from `02-system-architecture.mmd` + `docs/diagrams/where-it-sits.tsv` — add one line per new doc; never hand-copy the architecture.
- One idea per diagram, ≤ ~15 nodes; label every arrow with what flows; LR for pipelines, TD/TB for hierarchies (and for the overview — LR rendered unreadably wide), `sequenceDiagram` for requests, `erDiagram` for schema; spell out acronyms on first use; readable at 50% zoom. **Look at every rendered PNG before embedding it.**
- Colours (classDefs, legend node in every diagram that uses them): ingestion blue `#dbeafe/#1d4ed8` · storage grey `#e5e7eb/#4b5563` · retrieval green `#dcfce7/#15803d` · generation purple `#f3e8ff/#7e22ce` · eval orange `#ffedd5/#c2410c` · user/IO white `#ffffff/#111827` · highlight red `#dc2626`.
- Every embedded diagram is immediately followed by `<details><summary>Same diagram as text (for terminal viewing)</summary>` + a ```` ```text ```` block: box-drawing characters, ≤ 100 columns, labelled arrows, no overlapping lines (enforced by tests).

## Doc standard (topic docs 01–20)

Audience: knows basic Python, nothing about embeddings/vector search/FTS/rerankers/evals; must be able to rebuild the system from the docs. Short sentences, plain words, **bold** each new term with a one-line definition before using it. Line 2 of every numbered doc: `**Status:** …`. 00, 21, 22, 23 are reference pages with their own formats.

Sections, in order: 1 In one paragraph · 2 Why it exists · 3 Where it sits · 4 The flow · 5 The code (real paths, real snippets, explained in small blocks) · 6 Data in / data out (real example, field by field) · 7 Decisions & alternatives (Decision Cards) · 7a Prerequisite concepts (teach the thing behind the thing, from first principles, worked example with real numbers) · 7b "What if we used something else?" table · 8 Failure modes (real error text) · 9 Try it yourself (exact commands + expected output) · 10 Numbers (with commands) · 11 Interview talking points · 12 Check yourself (3 Qs, answers in `<details>`) · 13 New terms (append to `docs/21-glossary.md` the same phase). Cross-link; explain each concept once, in its owning doc.

### Decision Card format

Wrap each card in its own lines `<!-- card:start id=N -->` … `<!-- card:end -->` (N = 1–42 from the mandatory list in `scripts/collect_cards.py`, or `x-slug` for extras). Body starts `#### Decision: <chosen>  (rejected: A, B, C)` then: **One-line defence** · **What problem is this even solving?** · **The options, compared** (table: option / how / strengths / weaknesses / when right) · **What would actually change if we swapped it** (files, schema, p50/p95, cost per 1k queries, new failure mode, ops burden, hours) · **The decision rule** (general principle + crossover) · **Where our choice breaks** (+ migration path) · **The number** (from our system, with command, or "not yet measured — Phase N") · **Interview script (3 sentences)** · **Follow-ups they will ask** (≥ 5, full answers, one hard one with an honest answer) · **The trap**. Every card contains at least one honest point *against* our choice. Run `make cards` to mirror into `docs/interview/09-tradeoff-cards.md` (a test checks it).

## Phase ritual

build → test → write doc → render diagrams → update `PROGRESS.md` + glossary + troubleshooting → commit → **viva**:

1. Append ≥ 8 questions to the right `docs/interview/` files in the full format (30-second, 2-minute, push levels 2–4, whiteboard ≤ 6 lines, trap, bridge) with an `**ID:** PN-NN` line; add each to `02-question-map.md` (test-enforced). Aim for ~10 per phase (target 150+ total).
2. Mirror the phase's cards (`make cards`); add must-know numbers to `16-rapid-revision.md`.
3. Quiz the user: 5 questions, **one at a time, waiting for each answer** — one definition, one trade-off, one "why not X", one debugging scenario, one scaling question.
4. Grade each honestly against the docs — what was right, what was missing, what an interviewer would push on. Not generous. If an answer was weak, rewrite the doc section to be clearer and tell the user to re-read it.
5. Log weak spots in `02-question-map.md`. Then print the phase summary and stop.

Interview docs: frame questions as what this architecture invites, never "from my experience"; numbers over adjectives; analogy → mechanism → code; no marketing for our choices. Over-prep targets H1–H5 are listed in `02-question-map.md`.

## Commits

Local repo on `main`, no remote unless the user adds one. End commit messages with:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```
