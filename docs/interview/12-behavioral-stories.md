# 12 — Behavioural stories

**Status:** started in Phase 0 (2026-10-02) with story *seeds*. Stories are mined only from real events recorded in [PROGRESS.md](../../PROGRESS.md) and [23-troubleshooting.md](../23-troubleshooting.md) — no invented stories. Full STAR versions are written once a seed has an outcome number. Planned: the hardest bug; a decision reversed and why; a time I was wrong; prioritising under the 16-phase plan; what I cut and why; what I'd do differently.

---

## Seeds from Phase 0

### S-01 · The diagram that measured badly (a decision reversed)

- **Situation:** the architecture overview was written as a left-to-right flowchart, the obvious direction for a pipeline.
- **What actually happened:** it rendered at 3600 × 474 px — sixteen nodes in one strip, unreadable at half zoom (T-003).
- **What I did:** checked the rendered image instead of trusting the source, switched to top-to-bottom (1488 × 3598 px), widened label wrapping, and made "look at every PNG before embedding it" a standing rule.
- **Outcome number:** aspect ratio from 7.6 : 1 to about 1 : 2.4; legend wrap fixed.
- **Lesson:** verify outputs, not intentions. Small, but a clean example of measure → reverse → codify.

### S-02 · The healthy database that refused every login (a gotcha found by experiment)

- **Situation:** documenting failure modes for the environment doc.
- **What I did:** deliberately changed the database password in `.env` after the volume existed. The container still reported healthy, yet every connection failed (T-004).
- **Outcome:** the cause — the image applies the password only on first initialisation — went into the docs, and a test now proves a wrong password is rejected.
- **Lesson:** "healthy" means "accepting connections", not "configured the way you think". To develop into a full STAR story if a real incident echoes it later.

## Seeds from Phase 2

### S-03 · Deleting an optimisation after measuring it

- **Situation:** table detection is the slow part of parsing (~0.1 s per page), so I added a pre-filter: skip pdfplumber on pages that draw no lines, since its default strategy needs lines.
- **What I did:** measured with and without on two filings before keeping it.
- **Outcome number:** AMD 14.9 s vs 15.2 s, Boeing 16.3 s vs 16.6 s — about 2% — with byte-identical output, because 118/118 and 213/215 pages draw *something* (EDGAR PDFs draw boxes everywhere). I deleted it.
- **Lesson:** an optimisation is a hypothesis about the data; measure on the real data before paying its complexity cost.

### S-04 · The bug that only one company had

- **Situation:** after the first full parse, one filing (Corning 2021) had 18 headings where its sibling year had 213.
- **What I did:** compared against the sibling, dropped from document stats to raw PyMuPDF blocks to individual lines, found sections merged into one block with non-breaking-space "blank" lines, and fixed paragraph splitting at line level — then re-checked all ten documents.
- **Outcome number:** 509 → 1,429 blocks, 18 → 169 headings; no regressions elsewhere.
- **Lesson:** per-document statistics against siblings are the cheapest bug detector there is.

## Seeds from Phase 6

### S-05 · Building BM25 — and not shipping it

- **Situation:** keyword search returned company subsidiary lists for a goodwill question; textbook answer: Postgres ranking lacks IDF, use BM25.
- **What I did:** implemented BM25 in SQL (document frequencies from `ts_stat`), then compared it with both built-in rankings on the same query and on 28 labelled FinanceBench questions.
- **Outcome number:** the failure was `ts_rank_cd`'s, not `ts_rank`'s; `ts_rank` matched BM25 on the example, scored 4 vs 2 of 28, and ran in 31 vs 72 ms. I made `ts_rank` the default and corrected my own write-up.
- **Lesson:** I was wrong about the cause until I compared all options on the same input; measuring beats the textbook, and being willing to say "my first explanation was wrong" is part of the job.

### S-06 · A conclusion that came from my own bug

- **Situation:** the hybrid benchmark said weighted-score fusion was worse than RRF at every weight, a clean result I had already written into the docs and a decision card.
- **What I did:** checking the write-up's numbers, I noticed that at α_vec = 0.3 the fusion found 20 of 50 figures while its keyword input alone found 50. A fusion worse than its own input is a bug signal. Min-max normalisation scored a one-hit list as 0.
- **Outcome number:** after the fix, 49 of 50. Weighted fusion at 0.5 turned out competitive with RRF (FinanceBench hit@10 0.357 vs 0.286, within noise). I rewrote the card, kept RRF for a different, honest reason (no weight to tune on the test set), and logged it as T-032.
- **Lesson:** sanity-check results against their inputs before believing them, especially results that confirm what you expected.

### S-07 · The reranker that got worse with more data

- **Situation:** I expected a cross-encoder to fix hybrid search's ranking problems, and that reading more candidates would help it.
- **What I did:** measured reranked accuracy next to the recall ceiling for N = 10…100 and for two models, then looked at the top results question by question.
- **Outcome number:** the ceiling rose from 0.29 to 0.71, but reranked top-10 fell to 0.25. The top results were the right topic from the wrong company or year. One more experiment (filter to the right filing) doubled top-10 to 0.607. I chose the smallest N and the small model, and moved company/year filters up the plan.
- **Lesson:** measure each stage's ceiling separately. The fix was metadata, not a bigger model.
