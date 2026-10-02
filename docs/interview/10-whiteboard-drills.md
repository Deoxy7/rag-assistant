# 10 — Whiteboard drills

**Status:** started in Phase 0 (2026-10-02) with drill 1. Planned: (2) the retrieve-then-rerank funnel with counts — Phase 8; (3) RRF on two toy lists, with arithmetic — Phase 7; (4) the eval loop and metric tree — Phase 11; (5) the ER diagram — Phase 4; plus the "design it for 10× scale" variant — Phase 13.

Each drill: the exact ASCII to practise, the order to draw the boxes, and the narration. Target: under 4 minutes from memory.

---

## Drill 1 — The system in one picture

**Draw in this order** — it mirrors the story you're telling:

1. The storage box in the middle (it's what both halves share).
2. The offline row above it, left to right.
3. The question entering on the left of the bottom row.
4. The two searches pointing up into storage.
5. Fusion → rerank → LLM → answer on the right.

```text
 PDF ─▶ Parse ─▶ Chunk ─▶ Embed ─▶ [ Postgres: text · vectors · keywords ]
                                          │            │
 Question ─▶ API ─▶ vector search ◀───────┘   keyword search
                         └────────▶ RRF ◀──────────┘
                                     ▼
                              Rerank ─▶ LLM ─▶ answer + citations
```

**Narration (about 90 seconds; one sentence per box):**

- (1) "Everything lives in one Postgres: chunk text, vectors via pgvector, and a full-text keyword index."
- (2) "Offline, each PDF is parsed with page and character offsets, chunked, embedded and written there once."
- (3) "Online, a question comes in through the API."
- (4) "It runs two searches in parallel: vector search for similar meaning and keyword search for exact words — they fail differently."
- (5) "RRF merges the two rankings by rank, a cross-encoder reranks the top few, and the LLM answers only from those chunks with character-level citations — or refuses."

**What they'll interrupt with** (and where the answer lives): "why two searches?" → card #20 (Phase 7) · "why one database?" → card #15, P0-04 · "how do citations work?" → card #28 (Phase 9).

**10× scale variant:** added in Phase 13, once per-stage latencies are measured.
