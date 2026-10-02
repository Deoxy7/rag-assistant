# RAG assistant with a self-built evaluation harness

A question-answering assistant over complex PDF documents that answers only from the documents, cites the exact page and character span it used, or says the answer isn't there — plus an evaluation harness and ablation study showing which retrieval choices actually help.

**Status:** Phases 0–12 of 16 done: ingestion, hybrid retrieval + reranking, cited generation, FastAPI with streaming, the eval harness and the ablation study. Retrieval on the 61-question golden set: hit@5 0.769 [95% CI 0.65–0.88]. With retrieval, answers are judged correct for 0.721 of answerable questions; the same model without retrieval (closed book) manages 0.067. Cost/observability, security, UI and packaging are next; the full README (architecture, headline metrics, demo) is written in Phase 16. Progress log: [PROGRESS.md](PROGRESS.md).

## Quick start

Prerequisites and versions: [docs/00-START-HERE.md](docs/00-START-HERE.md#prerequisites).

```bash
colima start --cpu 2 --memory 2 --disk 10
```

```bash
make test
```

`make test` creates the Python 3.11 venv, installs pinned requirements, starts Postgres 16 + pgvector 0.8.7 in Docker, and runs the suite.

## Models: why the generator and the judge are different

| Role | Model | Provider (OpenAI-compatible API) | Configured by |
|---|---|---|---|
| Embeddings | `BAAI/bge-small-en-v1.5` (local) | sentence-transformers | `EMBEDDING_MODEL` (pinned revision; never changed, as re-embedding would invalidate every eval number) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L6-v2` (local) | sentence-transformers | `RERANK_MODEL` |
| **Generator** (writes answers) | `qwen/qwen3.8-27b` (Alibaba Qwen family) | Groq | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `GROQ_API_KEY` |
| **Judge** (grades answers in the eval) | `openai/gpt-oss-120b` (OpenAI open-weights family) | Groq | `LLM_JUDGE_PROVIDER`, `LLM_JUDGE_BASE_URL`, `LLM_JUDGE_MODEL` |

The judge is deliberately **a different model from a different family** than the generator:

- **Self-preference.** A model grading its own output tends to rate it favourably. It recognises its own phrasing and shares its reasoning habits.
- **Shared blind spots.** A judge that makes the same mistakes as the generator (here: taking the wrong year's column from a table) won't catch them. Two families trained differently are less likely to fail the same way.
- **Independence of the measurement.** Switching the generator must not silently change the ruler. With a separate judge setting, generator experiments are graded by a fixed, pinned judge.

The judge is also larger (120B vs 27B parameters), so it grades a smaller model rather than a peer.

It is still an LLM judge with known biases. It scored one confidently wrong but cited number as "faithful" because the number does appear in the cited table (see [docs/16](docs/16-experiments-and-ablations.md)). Its verdicts are a relative measure for comparing configurations; agreement with human grades hasn't been measured. Retrieval itself is graded without any LLM, against exact evidence spans.

**How we got here** (each step is in [docs/23-troubleshooting.md](docs/23-troubleshooting.md)): OpenAI (account had no credits) → Gemini 3.5 Flash (the free tier allowed 20 requests/day; a full eval needs 61) → Gemini 3.5 Flash-Lite (the project then returned HTTP 402 "prepayment credits depleted") → Qwen on Groq's free tier, with a judge from another family. Any OpenAI-compatible provider can be swapped in by editing `.env`; see the template in [.env.example](.env.example).

## Documentation

Start at [docs/00-START-HERE.md](docs/00-START-HERE.md). Every component has a teaching doc written in the same phase as its code, with rendered diagrams and text versions of each. Interview preparation lives in [docs/interview/](docs/interview/00-how-interviews-go.md).
