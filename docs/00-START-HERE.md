# 00 — Start here

**Status:** written in Phase 0 (2026-10-02); refreshed in Phase 16. This is a navigation page, so it does not use the 13-section skeleton the topic docs use.

---

## What this project is

A question-answering assistant over a set of complex PDF documents (annual reports), built from scratch, which answers only from the documents and cites the exact page and characters it used — or says the answer isn't there. The part that makes it more than a "chat with your PDFs" demo is the **evaluation harness**: a set of questions with known answers, retrieval and answer-quality metrics we implement ourselves, and an **ablation table** that shows, with numbers, which retrieval choices actually helped.

These docs are written for a final-year engineering student who knows basic Python and nothing yet about embeddings, vector search, Postgres full-text search, rerankers or evaluation. Someone should be able to rebuild the whole system from them.

## How to read these docs

**Path 1 — learn the system (start here if you're new).** Read in number order: [01](01-what-is-rag.md) (what RAG is) → [02](02-architecture-overview.md) (the whole system) → [03](03-environment-and-infra.md) (how it runs), then each component doc as it is built. Every doc tells you its prerequisites at the top.

**Path 2 — prepare for interviews.** Start with [interview/00-how-interviews-go.md](interview/00-how-interviews-go.md), learn a pitch from [interview/01-the-pitch.md](interview/01-the-pitch.md), drill the trade-offs in [interview/09-tradeoff-cards.md](interview/09-tradeoff-cards.md), and use [interview/16-rapid-revision.md](interview/16-rapid-revision.md) the night before. [interview/02-question-map.md](interview/02-question-map.md) indexes every question.

**Path 3 — read in a terminal.** Every diagram image is followed by a collapsed block, *"Same diagram as text"*, holding an ASCII version. In a plain-text viewer the `<details>` tags simply show the text.

## Conventions used everywhere

- **Bold term** — defined right there, in one line, the first time it appears. All terms are collected in [21-glossary.md](21-glossary.md) with a link to the doc that explains them. A concept is explained in exactly one doc; others link to it.
- **Status line** — the second line of every numbered doc says whether it's written and in which phase.
- **The 13-section skeleton** — every topic doc (01–20) uses the same sections: *In one paragraph · Why it exists · Where it sits · The flow · The code · Data in / data out · Decisions & alternatives (Decision Cards) · Prerequisite concepts · What if we used something else? · Failure modes · Try it yourself · Numbers · Interview talking points · Check yourself · New terms*.
- **Decision Cards** — every non-trivial choice gets a card in a fixed format: options compared, what would change if swapped, the general decision rule, where our choice breaks, the measured number, an interview script, follow-up questions, and the trap. All cards are mirrored into [interview/09-tradeoff-cards.md](interview/09-tradeoff-cards.md) by `make cards`.
- **Numbers** — every measurement is shown with the command that produced it. Anything not yet measured says *"not yet measured — measured in Phase N"*. Nothing is estimated and presented as measured.
- **Colours in diagrams** — the same everywhere: blue = ingestion · grey = storage · green = retrieval · purple = generation · orange = eval · white = user / IO. In "where it sits" diagrams, a **red border** (image) or **double-line box ╔═╗** (ASCII) marks the part the doc explains.

## Prerequisites

Measured on the build machine (Apple M1, 8 GB RAM, macOS 27). Versions are what Phase 0 installed and tested.

| Tool | Version | Install |
|---|---|---|
| Homebrew | 7.0.6 | <https://brew.sh> |
| Python | 3.11.9 | already present on the build machine (`python3.11`) |
| Colima (Linux VM for Docker) | 0.10.3 | `brew install colima` |
| Docker CLI / Compose plugin | 29.8.2 / 5.5.1 | `brew install docker docker-compose` |
| Graphviz | 16.1.0 | `brew install graphviz` |
| Node / npm | 25.9.0 / 11.12.1 | already present (mermaid-cli needs Node ≥ 22.13) |
| mermaid-cli (`mmdc`) | 12.0.0 | `npm install -g @mermaid-js/mermaid-cli@12.0.0` |
| Postgres + pgvector | 16.15 + 0.8.7 | pulled by `make up` (pinned by digest in `docker-compose.yml`) |

The Compose plugin also needs linking so `docker compose` finds it:

```bash
mkdir -p ~/.docker/cli-plugins && ln -sfn "$(brew --prefix)/lib/docker/cli-plugins/docker-compose" ~/.docker/cli-plugins/docker-compose
```

## How to run it

```bash
colima start --cpu 2 --memory 2 --disk 10
```

```bash
make install
```

```bash
make up
```

```bash
make corpus
```

```bash
make test
```

`make test` installs requirements and starts the database itself if needed, so on a configured machine it is the only command you need. Then:

| Command | What it does |
|---|---|
| `make help` | lists every target |
| `make psql` | opens a SQL shell inside the database |
| `make corpus` | downloads the 10-K PDFs listed in `data/manifest.json` and verifies their hashes |
| `make inspect` | reports page counts, text, tables, Items and tokens per PDF; renders the corpus charts |
| `make parse` | parses every PDF into blocks with page + character offsets (cached in `data/parsed/`) |
| `make migrate` | applies pending SQL migrations |
| `make ingest` | parses, chunks, embeds and indexes the corpus (default chunking from settings) |
| `make bench-vector` | vector search: recall vs exact, ef_search, filter modes, quantisation |
| `make bench-keyword` | keyword ranking (ts_rank, ts_rank_cd, BM25) vs vector on FinanceBench questions |
| `make diagrams` | renders every diagram to SVG + PNG |
| `make docs` | renders diagrams, mirrors Decision Cards, checks every link, image and ASCII twin |
| `make down` | stops the database (data kept) |
| `make db-reset` | **deletes** the database volume; the next `make up` starts fresh |

What each command does inside, and every error you might hit: [03-environment-and-infra.md](03-environment-and-infra.md).

## Reading order and status

| Doc | Topic | Phase | Status |
|---|---|---|---|
| [01](01-what-is-rag.md) | What is RAG | 0 | ✅ written |
| [02](02-architecture-overview.md) | Architecture overview | 0, refreshed every phase | ✅ written |
| [03](03-environment-and-infra.md) | Environment and infrastructure | 0 | ✅ written |
| [04](04-corpus.md) | Corpus | 1 | ✅ written |
| [05](05-pdf-parsing.md) | PDF parsing | 2 | ✅ written |
| [06](06-chunking.md) | Chunking | 3 | ✅ written |
| [07](07-embeddings.md) | Embeddings | 4 | ✅ written |
| [08](08-database-schema.md) | Database schema | 4 | ✅ written |
| [09](09-vector-search.md) | Vector search | 5 | ✅ written |
| [10](10-keyword-search.md) | Keyword search | 6 | ✅ written |
| [11](11-hybrid-rrf.md) | Hybrid search + RRF | 7 | ✅ written |
| [12](12-reranking.md) | Reranking | 8 | ✅ written |
| [13](13-prompting-and-citations.md) | Prompting and citations | 9 | ✅ written (real-model numbers pending key) |
| [14](14-api-and-streaming.md) | API and streaming | 10 | ✅ written (real-model latency pending OpenAI credits) |
| [15](15-eval-harness.md) | Evaluation harness | 11 | not yet written |
| [16](16-experiments-and-ablations.md) | Experiments and ablations | 12 | not yet written |
| [17](17-cost-and-observability.md) | Cost and observability | 13 | not yet written |
| [18](18-security-prompt-injection.md) | Security and prompt injection | 14 | not yet written |
| [19](19-frontend.md) | Frontend | 15 | not yet written |
| [20](20-deployment-and-demo.md) | Deployment and demo | 16 | not yet written |
| [21](21-glossary.md) | Glossary | every phase | ✅ started |
| [22](22-interview-prep.md) | Interview prep | 12, 16 | not yet written |
| [23](23-troubleshooting.md) | Troubleshooting log | every phase | ✅ started |

## Where things live

```text
app/            the application (config, store; more packages arrive phase by phase)
tests/          pytest suite — `make test`
scripts/        diagram rendering, "where it sits" generation, Decision Card mirroring
docker/initdb/  SQL run once when the database volume is first created
docs/           these docs; diagrams/src = sources, diagrams/out = rendered images
docs/interview/ interview preparation, built up every phase
eval/           golden set, metrics, results (from Phase 11)
data/           the PDF corpus (git-ignored; from Phase 1)
PROGRESS.md     phase-by-phase log of what was built and measured
CLAUDE.md       working rules for AI-assisted sessions on this repo
```
