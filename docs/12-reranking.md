# 12 — Reranking

**Status:** not yet written — filled in Phase 8.

What this doc will cover: A cross-encoder over the fused top-N, its measured latency, and the switch for rerank on/off and depth N.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #24, #25, #26
7a. Prerequisite concepts — bi-encoder vs cross-encoder, ColBERT late interaction, LLM-as-reranker, the retrieve-then-rerank funnel
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — rerank latency p50/p95 vs N, quality vs N
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: retrieve-then-rerank funnel with counts at each stage
