# 01 — The pitch

**Status:** first draft in Phase 0 (2026-10-02); every number filled in from measurements in Phase 16 (2026-10-03). Each number links back through [22-interview-prep](../22-interview-prep.md) to the command that produced it.

Four lengths, each written out to be said verbatim. **[pause]** marks a natural place for the interviewer to cut in — stop there and let them.

---

## 20 seconds — HR, "tell me about yourself"

"I built a question-answering system over company annual reports that answers only from the documents and cites the exact page and passage — or says the answer isn't there. **[pause]** The part I'm proudest of is the evaluation: I wrote my own test set and metrics, and ran experiments to see which retrieval techniques actually helped, including the ones that didn't."

## 90 seconds — opening of a technical round

"It's a retrieval-augmented generation system over SEC annual reports — long PDFs full of tables and numbered sections. **[pause]**

Offline, I parse each PDF and record the page and character offsets of every text block, split it into chunks, embed them, and store everything in Postgres with pgvector and Postgres full-text search, so text, vectors and the keyword index live in one database. **[pause]**

Online, a question runs vector search and keyword search in parallel, the two rankings are fused with reciprocal rank fusion, a cross-encoder reranks the top few, and the LLM answers only from those chunks with character-level citations — or refuses. It streams over FastAPI with server-sent events. **[pause]**

The differentiator is the eval harness: 61 golden questions with known evidence locations, retrieval metrics like recall@k and MRR that I implemented myself, and LLM-judged faithfulness. The evidence is in the top 5 for 77% of questions; with retrieval, answers are correct 72% of the time against 7% for the same model without it. The 57-configuration ablation showed the reranker is the one choice that helps almost everywhere, and that my own test set flatters keyword search."

## 5 minutes — project deep-dive opener

Draw this while talking (practise it in [10-whiteboard-drills.md](10-whiteboard-drills.md)):

```text
 PDF ─▶ Parse ─▶ Chunk ─▶ Embed ─▶ [ Postgres: text · vectors · keywords ]
                                          │            │
 Question ─▶ API ─▶ vector search ◀───────┘   keyword search
                         └────────▶ RRF ◀──────────┘
                                     ▼
                              Rerank ─▶ LLM ─▶ answer + citations
```

1. **The problem (30 s).** "Annual reports are long, structured, full of tables, and nearly identical year to year. A plain LLM can't cite them and will invent figures. I wanted a system whose answers can be checked." **[pause]**
2. **The workload (30 s).** "About ten filings, rarely changing, one user, citations required to the character, refuse when unsure, and first-token latency matters for the UI." **[pause]**
3. **Ingestion (60 s).** "PyMuPDF for text blocks with page and offsets, pdfplumber for tables. The offsets are captured at parse time on purpose — citations and the highlight-in-PDF feature depend on them, and adding them later would mean re-ingesting everything." **[pause]**
4. **Retrieval (90 s).** "Two retrievers because they fail differently: vectors catch paraphrases, keywords catch exact figures and section numbers. RRF fuses by rank, because the raw scores aren't comparable. A cross-encoder reranks the top 10, which costs about 77 ms per query and improved hit@5 in 23 of 27 paired configurations." **[pause]**
5. **Evaluation (60 s).** "Golden questions with evidence spans, so labels survive re-chunking. Retrieval measured before generation. The finding: nothing beat my default significantly, 30 configurations were significantly worse, and golden-set and FinanceBench scores were negatively correlated (−0.53), so I chose the configuration that holds up on both rather than my test set's winner." **[pause]**
6. **What I'd change (30 s).** "Three things: query decomposition for multi-hop questions, which are the weakest type at a third of evidence found; hand-grading 30 answers to calibrate the LLM judge; and questions written by someone who hasn't read the filings, to break my test set's vocabulary bias."

## 15 minutes — full walkthrough, interrupt-driven

Use the 5-minute structure, but at every **[pause]** expect one of the hooks below and go one level deeper using the linked material. Order of depth if they *don't* interrupt:

1. Workload contract → [02 §6](../02-architecture-overview.md#the-workload-contract)
2. Why RAG at all → card #1 ([09](09-tradeoff-cards.md))
3. Why one Postgres → card #15
4. Parsing and offsets → card #5 (Phase 2)
5. Chunking strategy and size → cards #8, #9 (Phase 3)
6. Hybrid + RRF, derived on the whiteboard → card #22 (Phase 7)
7. Reranking cost/benefit → card #25 (Phase 8)
8. Evaluation design and what the numbers don't prove → [07-evaluation.md](07-evaluation.md) (Phase 11)
9. The ablation table and the surprise in it → Phase 12
10. Cost, latency, security, and what I'd do at 100× → Phases 13–14, [06-system-design.md](06-system-design.md)

## Hooks — the follow-up each phrase is designed to provoke

| Hook phrase in the pitch | Question it invites | Prepared answer |
|---|---|---|
| "answers only from the documents… or says it isn't there" | "How do you decide when to refuse?" | Card #3 (Phase 9) |
| "including the ones that didn't [help]" | "What didn't help?" | Phase 12 ablation — the honest loss |
| "nearly identical year to year" | "How do you stop it citing the wrong year?" | Metadata filters (card #18), near-duplicate handling (card #7) |
| "offsets captured at parse time on purpose" | "Why does that matter?" | Card #5 (Phase 2) |
| "they fail differently" | "Give me a query where keywords beat vectors" | [10-keyword-search.md](../10-keyword-search.md) (Phase 6); the "grew/grow" demo in [01-what-is-rag.md](../01-what-is-rag.md#6-data-in--data-out) shows the opposite case today |
| "the raw scores aren't comparable" | "Why not just add the scores?" | Card #22 (Phase 7) |
| "labels survive re-chunking" | "How do you label relevance?" | Evidence spans, [07-evaluation.md](07-evaluation.md) (Phase 11) |
| "one database" | "Why not a vector database?" | Card #15 — question P0-04 in [05-database-and-sql.md](05-database-and-sql.md) |
