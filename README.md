# RAG assistant with a self-built evaluation harness

A question-answering assistant over complex PDF documents that answers only from the documents, cites the exact page and character span it used, or says the answer isn't there — plus an evaluation harness and ablation study showing which retrieval choices actually help.

**Status:** Phases 0–11 of 16 done: ingestion, hybrid retrieval + reranking, cited generation (Gemini), FastAPI with streaming, and the eval harness. Baseline retrieval on the 61-question golden set: hit@5 0.769 [95% CI 0.65–0.88]. Ablations, cost/observability, security, UI and packaging are next; the full README (architecture, headline metrics, demo) is written in Phase 16. Progress log: [PROGRESS.md](PROGRESS.md).

## Quick start

Prerequisites and versions: [docs/00-START-HERE.md](docs/00-START-HERE.md#prerequisites).

```bash
colima start --cpu 2 --memory 2 --disk 10
```

```bash
make test
```

`make test` creates the Python 3.11 venv, installs pinned requirements, starts Postgres 16 + pgvector 0.8.7 in Docker, and runs the suite.

## Documentation

Start at [docs/00-START-HERE.md](docs/00-START-HERE.md). Every component has a teaching doc written in the same phase as its code, with rendered diagrams and text versions of each. Interview preparation lives in [docs/interview/](docs/interview/00-how-interviews-go.md).
