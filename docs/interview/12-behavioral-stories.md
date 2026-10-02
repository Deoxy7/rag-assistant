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
