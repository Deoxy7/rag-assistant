# 22 — Interview prep

**Status:** first filled in Phase 12 (2026-10-02/03) with the measured retrieval, ablation and real-model generation numbers; refreshed in Phase 16. Every number below has a command in the doc it links to.

The detailed bank (150+ questions, each with 30-second / 2-minute answers and push-backs) lives in [docs/interview/](interview/00-how-interviews-go.md); this page is the short version to read the night before.

---

## 1. The ten most likely questions, with answers built from real numbers

**1. "Walk me through the system."** Ten SEC 10-K filings: PepsiCo, Verizon, Corning, AMD and Boeing, FY2021 and FY2022, 2,224 pages. The pipeline:
- Parse them into text with exact character offsets.
- Chunk into 256-token pieces that respect document structure: 7,411 chunks.
- Embed with bge-small (384 dimensions) into Postgres + pgvector, with Postgres full-text search alongside.
- At query time, run vector and keyword search, fuse the two lists with RRF, rerank the top 10 with a cross-encoder, and ask Gemini to answer *only* from numbered sources.
- Map each `[n]` it writes back to the stored chunk, page and character span.

A self-built eval harness measures every stage. → [02](02-architecture-overview.md)

**2. "How good is it?"** Retrieval: on my 61-question golden set (52 answerable), the evidence is in the top 5 for **76.9% of questions, 95% CI 65–88%**: 91% for single facts, 62% for tables, and 56% for multi-hop questions, where only 33% of the needed pieces are found. On FinanceBench's 28 analyst questions, page-hit@10 is 0.286. Answers, with real models (Qwen 27B generates, gpt-oss-120B judges): **correctness 0.721 [0.60–0.84]**, faithfulness to cited sources 0.923, all 9 unanswerable questions refused, and 23% of answerable questions refused, mostly where retrieval missed. The same model **without retrieval scores 0.067**. → [15](15-eval-harness.md), [16](16-experiments-and-ablations.md)

**3. "Why hybrid search?"** Vector search found 0 of 50 exact figures in its top 5; keyword search found 50. Fusing with RRF keeps both. In the ablation, hybrid is the only mode that holds up on both test sets: golden 0.649 and FinanceBench 0.302 on average, while vector-only scores 0.453 / 0.401 and keyword-only 0.638 / 0.183. → [11](11-hybrid-rrf.md), [16](16-experiments-and-ablations.md)

**4. "Does the reranker help?"** Yes: it's the most robust effect measured. It improves hit@5 in 23 of 27 paired configurations (+0.067 on average); on the default chunking, 0.635 → 0.769 (sign test p = 0.04). It costs about 77 ms. A deeper rerank (N = 20) and a 12× larger reranker were *not* better. → [12](12-reranking.md)

**5. "How do you know you didn't overfit your eval?"** I can't fully. I wrote the golden questions from the filings, and they reuse its words. The ablation exposed this: across 54 configurations, golden-set and FinanceBench scores are **negatively** correlated (Spearman −0.53). Keyword search looks great on mine and bad on FinanceBench. So I keep hybrid, which is robust on both, rather than crowning my own test set's winner. → [16](16-experiments-and-ablations.md) card x-default-after-ablation

**6. "How do citations work, and can the model fake one?"** The model writes only `[n]`. Code maps `n` to the chunk it was shown: document, PDF page, character span, and on-page bounding boxes. I verified that all 7,411 chunk spans equal the stored text exactly. Invalid numbers are removed and uncited claims flagged. → [13](13-prompting-and-citations.md)

**7. "What happens when the answer isn't in the documents?"** The model is told to reply with a fixed token, `INSUFFICIENT_CONTEXT`, which the API turns into a clean refusal. In the full run it refused **9 of 9** unanswerable questions; the closed-book model answered 3 of them from memory (Apple, Tesla, and an AMD fiscal 2024 figure). The model ignored the exact format about 1 time in 15 (token appended after an explanation), which the detector now handles. A score threshold was tested and rejected (AUROC 0.66). → [15](15-eval-harness.md) card #3

**8. "What broke, and how did you find it?"**
- The eval found a keyword bug: a question containing a figure matched nothing, because the query required another word too. Fixing it moved hit@5 0.692 → 0.731.
- A full-text label audit found 8 questions with answer locations I'd missed (→ 0.769).
- Gemini counts hidden thinking tokens against `max_tokens`, so an answer came back as `'1'`.
- A 429 can mean "slow down" or "your daily quota is gone".

→ [23-troubleshooting.md](23-troubleshooting.md) T-042, T-046, T-052

**9. "How would you scale it?"** The measured bottleneck is the model passes, not the database. With 4 concurrent clients, throughput went 6.8 → 13.7 req/s, because embedding and reranking are serialised by a lock on one GPU. Next steps: a batched model-serving process, concurrent vector and keyword searches, a connection pool, and async streaming once open streams approach the thread-pool limit (40). → [14](14-api-and-streaming.md)

**10. "Why not LangChain / a vector DB / RAGAS?"** Each core piece is short, owned code I can test exactly: span-graded metrics, offset-exact citations, plain-SQL retrieval in one Postgres. LangChain's splitter returned wrong character offsets (T-019), which is exactly the detail citations depend on. → cards #15, #34, #35

## 2. Numbers to know cold

| What | Number |
|---|---|
| Corpus | 10 filings · 2,224 pages · 1.42 M tokens · 7,411 chunks (structure/256) |
| Golden set | 61 q: 22 factual, 13 table, 8 exact-token, 9 multi-hop, 9 unanswerable |
| Baseline retrieval | hit@5 0.769 [0.65–0.88] · recall@10 0.760 · MRR 0.535 · nDCG@10 0.523 |
| By type (hit@5) | factual 0.909 · exact 0.875 · table 0.615 · multi-hop 0.556 (recall@5 0.333) |
| FinanceBench page-hit@10 | 0.286 (baseline) · best config 0.500 (vector-only, 510) |
| Ablation | 57 configurations · rerank +0.067 hit@5, better in 23 of 27 pairs · Spearman(golden, FB) −0.53 · 30 significantly worse than baseline, none better |
| Exact figures | vector 0/50 in the top 5 → hybrid 50/50 |
| Reranker | MiniLM-L6, N = 10, 77 ms MPS; bge-base 6× slower, no better |
| Right-filing filter | FinanceBench hit@10 0.286 → 0.607 |
| Latency | retrieval ~110 ms · API p50 143 ms (fake LLM) · one Gemini answer 2.5 s |
| Generator / judge | qwen/qwen3.8-27b / openai/gpt-oss-120b, both on Groq (different families; README "Models") |
| RAG vs closed book | correctness 0.721 vs 0.067 (37 vs 4 questions won) · unanswerable refused 9/9 vs 6/9 |
| RAG answers | faithfulness 0.923 · 92.5% cite an evidence passage · false refusals 23% |
| Cache | smoke eval 101 s → identical rerun 13 s, 0 tokens · full judged rerun 26 s |

The full list is in [interview/16-rapid-revision.md](interview/16-rapid-revision.md).

## 3. Where each answer is explained in depth

| Topic | Doc | Question bank |
|---|---|---|
| Parsing, offsets | [05](05-pdf-parsing.md) | [interview/03](interview/03-fundamentals.md) |
| Chunking | [06](06-chunking.md) | P3-xx |
| Vector search, HNSW, filters | [09](09-vector-search.md) | P5-xx |
| Keyword search, BM25 | [10](10-keyword-search.md) | P6-xx |
| RRF | [11](11-hybrid-rrf.md) | P7-xx |
| Reranking | [12](12-reranking.md) | P8-xx |
| Prompting, citations, provider | [13](13-prompting-and-citations.md) | P9-xx, P11-09…11 |
| API, SSE | [14](14-api-and-streaming.md) | P10-xx |
| Eval harness | [15](15-eval-harness.md) | P11-xx |
| Ablations | [16](16-experiments-and-ablations.md) | P12-xx |
| Every question by id | — | [interview/02-question-map.md](interview/02-question-map.md) |

## 4. Weak spots (be ready for these)

- **The judge hasn't been checked against human grades**, and it called one cited-but-wrong number "faithful" (G032). Correctness against references caught it.
- **The generator changed three times** (OpenAI → Gemini → Qwen on Groq) because of quotas and billing. Answer numbers belong to Qwen + gpt-oss; retrieval numbers don't depend on the LLM.
- **My test set flatters keyword search.** Know the −0.53 correlation and the explanation.
- **Multi-hop retrieval is weak** (recall@5 0.33); the planned fix, query decomposition, isn't built.
- **The default is the best cell of the weakest chunking strategy.** That's a winner's-curse risk, and fixed256-hybrid-rr is the candidate to re-test.

The end-of-phase vivas were waived on 2026-10-02 at the user's request, so no viva weak spots are recorded. The list above is from the measurements.
