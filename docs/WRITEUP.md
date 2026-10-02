# Write-up: a cited RAG assistant, measured

**Status:** written in Phase 16 (2026-10-03). A two-page account of what was built, what the measurements say, what went wrong, and what I'd do next. Every number links to the doc that holds its command and raw output.

## The problem

Ask a chatbot about a company's annual report and it will answer fluently, and sometimes from memory rather than the report. The same model used here, with no documents, was judged correct on **0.067** of my answerable questions. It "answered" 3 of 9 questions about companies and years that aren't in the corpus at all ([16](16-experiments-and-ablations.md)). So the goal was a system that:
- answers only from ten SEC 10-K filings (2,224 pages, five companies, fiscal 2021–2022);
- ties every claim to a page and character span you can open;
- refuses when the filings don't say;
- comes with the evidence that each design choice earned its place.

## What was built

A pipeline in plain Python over one Postgres instance ([02](02-architecture-overview.md), [20](20-deployment-and-demo.md)):

1. **Parsing** keeps one canonical text per filing with exact character offsets, page ranges and the bounding box of every text block ([05](05-pdf-parsing.md)). Offsets were a hard requirement from Phase 2, because the citation design depends on them. LangChain's splitter was rejected for chunking after its offsets came back wrong (T-019).
2. **Chunking** is structure-aware, at 256 embedding-model tokens: 7,411 chunks ([06](06-chunking.md)). **Embeddings** are `bge-small-en-v1.5`, local ([07](07-embeddings.md)).
3. **Retrieval** is hybrid. pgvector HNSW for meaning and Postgres full-text search for exact words, 50 results each, fused with Reciprocal Rank Fusion, then a cross-encoder reorders the top 10 ([09](09-vector-search.md)–[12](12-reranking.md)). Vector search alone found 0 of 50 exact dollar figures in its top 5; hybrid found 50.
4. **Generation.** The model sees numbered, fenced sources and writes `[n]`. Code maps `n` back to the stored chunk, so a citation can't point at text that doesn't exist ([13](13-prompting-and-citations.md)). A fixed refusal token becomes a clean "I can't answer that".
5. **Serving.** FastAPI streams answers over Server-Sent Events, with the refusal held back until it can't be a refusal ([14](14-api-and-streaming.md)). Each request records per-stage timings, tokens, and list-price vs billed cost ([17](17-cost-and-observability.md)). A Streamlit UI opens each citation on its PDF page with the cited blocks highlighted ([19](19-frontend.md)).
6. **Evaluation.**
   - A 61-question golden set whose labels are *evidence spans* (exact quotes resolved to character offsets), not chunk ids, so one set grades every chunking configuration ([15](15-eval-harness.md)).
   - Retrieval metrics with bootstrap confidence intervals and sign tests.
   - Abstention metrics for unanswerable questions.
   - An LLM judge from a different model family than the generator.
   - A closed-book baseline, and a 57-configuration ablation ([16](16-experiments-and-ablations.md)).

## What the measurements say

- **Retrieval works for single facts, less for tables and multi-hop.** hit@5 is 0.769 overall [0.65–0.88]: factual 0.909, exact figures 0.875, tables 0.615, multi-hop 0.556. For multi-hop questions only a third of the needed pieces are found (recall@5 0.333).
- **Retrieval is most of the answer quality.** Correctness 0.721 with retrieval vs 0.067 without, same model; 37 questions won vs 4. Faithfulness to the cited sources is 0.923. All 9 unanswerable questions were refused; 23% of answerable ones were wrongly refused, mostly where retrieval missed.
- **The reranker is the most robust single choice.** It improved hit@5 in 23 of 27 paired configurations, +0.067 on average. A 12× larger reranker and a deeper rerank were not better ([12](12-reranking.md)).
- **My test set has a bias, and the ablation exposed it.** Keyword-only search looks excellent on my golden set (0.638 on average) and poor on FinanceBench's analyst questions (0.183). Across the 54 grid cells the two scores correlate at Spearman −0.53. My questions reuse the filings' words. So I kept hybrid, the one mode that holds up on both, rather than crowning my own test set's winner. No configuration beat the default significantly; 30 were significantly worse.
- **Prompt rules aren't security.** On a real model, the pre-Phase-14 prompt let 6 of 28 poisoned-document attacks through; a stronger prompt, 3. Code at the boundaries brought it to 1: quarantine, fences a document can't forge, and an output policy that also filters streamed tokens. An off-the-shelf injection classifier caught 1 of my 7 attacks; my pattern list caught 5 ([18](18-security-prompt-injection.md)).
- **Latency and cost are dominated by the free tier, not the code.** Unthrottled: retrieval ~320 ms, first token 402 ms, full answer 862 ms. Throttled: one answer spent 16 of its 16.8 s sleeping on rate-limit retries, which a whole-request timer had reported as "time to first token" (T-057). About $0.002 per answer at list price, $0 billed.

## What went wrong, and what it taught

Every error is in [23-troubleshooting.md](23-troubleshooting.md) (70 entries). The ones that changed the design:

- **The eval found a bug the tests didn't.** A question containing a figure like "16,434" matched nothing in keyword search, because the query also required another word (T-042). Fixing it moved hit@5 0.692 → 0.731. A full-text audit of the labels then found 8 questions with answer locations I had missed (→ 0.769). Lesson: the eval checks the system and the eval checks itself; both need auditing.
- **Providers fail in more ways than "429".** A 429 can mean slow down, or that today's quota is gone. A 402 means the money is gone. Hidden thinking tokens can eat the output budget and leave an answer of `'1'` (T-046). The client now tells these apart, and fails fast when retrying can't help (T-052, T-054). The generator changed three times for quota and billing reasons, which is why everything provider-specific is configuration.
- **Measurements need controls.** An injection "success" turned out to be a question the model refuses anyway (T-061). A UI latency number turned out to be rate-limit sleep. Each fix was a baseline measured under identical conditions.

## Limits I'd flag to a reviewer

- The golden set is small (61) and self-written: wide confidence intervals and the vocabulary bias above.
- The LLM judge hasn't been checked against human grades. It called one cited-but-wrong figure "faithful".
- The answer numbers were measured with prompt template 1. Template 2 (the security default) awaits a re-score once the generator's daily quota resets (T-063). The injection suite ran on `gpt-oss-20b`, not the production generator, for the same reason.
- Data poisoning: a planted false figure still reaches the reader when it fills a retrieval gap, now honestly cited to its source.
- One machine, one process; the UI and API are not load-tested beyond 4 concurrent clients.

## What I'd do next

1. Re-score template 2 on the golden set, and rerun the injection suite on the production generator.
2. Grade 30 answers by hand to calibrate the judge.
3. Query decomposition for multi-hop questions, the weakest type (recall@5 0.333).
4. Ingestion provenance: per-document trust labels shown with every citation.
5. Grow the golden set with questions written by someone who hasn't read the filings, to break the vocabulary bias.
