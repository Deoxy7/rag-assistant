# Run `make` or `make help` to list targets.
# Written for the GNU make 3.81 that ships with macOS: no .ONESHELL, no make-4 features.
# Every recipe uses paths relative to the repo root, because the repo's absolute
# path may contain spaces (make splits unquoted paths on spaces).

.DEFAULT_GOAL := help
.PHONY: help install up down db-reset psql corpus inspect parse migrate ingest bench-vector bench-keyword bench-hybrid bench-rerank bench-answer ask test diagrams cards docs

PYTHON_BIN ?= python3.11
VENV := .venv
PY := $(VENV)/bin/python
# A stamp file, not .venv/bin/python, marks "requirements installed": the venv's
# python is a symlink, and `touch` on a symlink would modify the system Python.
STAMP := $(VENV)/.requirements-installed

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

$(STAMP): requirements.txt
	test -x $(PY) || $(PYTHON_BIN) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip==26.2.1
	$(PY) -m pip install --quiet -r requirements.txt
	touch $(STAMP)

install: $(STAMP) ## Create .venv (Python 3.11) and install pinned requirements

.env:
	cp .env.example .env
	@echo "Created .env from .env.example"

up: .env ## Start Postgres + pgvector and wait until it accepts connections
	@docker info >/dev/null 2>&1 || { echo "Docker is not running. Start it with: colima start"; exit 1; }
	docker compose up -d --wait

down: ## Stop Postgres (data is kept in the pgdata volume)
	docker compose down

db-reset: ## DESTRUCTIVE: stop Postgres and delete its volume (all local data)
	docker compose down -v

psql: ## Open a psql shell inside the database container
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

corpus: install ## Download the PDFs in data/manifest.json (if missing) and verify every sha256
	$(PY) scripts/fetch_corpus.py

inspect: corpus ## Report page counts, text, tables, items, tokens; render docs/diagrams/out/04-*.png
	$(PY) scripts/inspect_corpus.py --charts

parse: corpus ## Parse every PDF into blocks with page + char offsets (cached in data/parsed/)
	$(PY) -m app.ingest.parse_corpus

migrate: install up ## Apply pending SQL migrations (app/store/migrations/)
	$(PY) -m app.store.migrate

ingest: migrate corpus ## Parse, chunk, embed and index the corpus (default chunking from settings)
	$(PY) -m app.ingest.pipeline

bench-vector: install up ## Vector search: recall vs exact, ef_search, filter modes, quantisation
	$(PY) scripts/bench_vector.py --chart

bench-keyword: install up ## Keyword ranking (ts_rank, ts_rank_cd, BM25) vs vector on FinanceBench questions
	$(PY) scripts/bench_keyword.py

bench-hybrid: install up ## Vector vs keyword vs hybrid (RRF k, weighted fusion) on FinanceBench + exact figures
	$(PY) scripts/bench_hybrid.py

bench-rerank: install up ## Cross-encoder reranking over hybrid top-N: quality and latency vs N, two models
	$(PY) scripts/bench_rerank.py

bench-answer: install up ## End-to-end answers on FinanceBench: context, citations, refusals, latency, cost [ARGS="--provider fake"]
	$(PY) scripts/bench_answer.py $(ARGS)

ask: install up ## Answer one question: make ask Q="What was AMD's net revenue in 2022?" [ARGS="--show-prompt --provider fake"]
	$(PY) scripts/ask.py "$(Q)" $(ARGS)

test: install up corpus ## Run the full test suite (starts Postgres and fetches the corpus if needed)
	$(PY) -m pytest

diagrams: install ## Render docs/diagrams sources to SVG + PNG in docs/diagrams/out/
	bash scripts/render_diagrams.sh

cards: install ## Copy every Decision Card in docs/ into docs/interview/09-tradeoff-cards.md
	$(PY) scripts/collect_cards.py

docs: diagrams cards ## Render diagrams, collect cards, then check links, images and ASCII twins
	$(PY) -m pytest tests/test_docs_integrity.py tests/test_tooling.py
