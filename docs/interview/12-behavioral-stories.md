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
