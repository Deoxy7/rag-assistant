# 00 — How interviews about this project go

**Status:** written in Phase 0 (2026-10-02); revised in Phase 16.

This file is the map. The rest of `docs/interview/` is the territory. Everything below is framed as *what this kind of round is designed to test* and *what this architecture invites* — general patterns, not claims about any particular company.

---

## 1. The round types and what each is really testing

| Round | What it's really testing | Depth expected | What to bring from this project |
|---|---|---|---|
| HR / "tell me about yourself" | Ownership, communication, motivation, whether you can tell a story with a point | Shallow on tech, deep on *why* and *what you learned* | The 20-second pitch ([01](01-the-pitch.md)); one real story ([12](12-behavioral-stories.md)) |
| Viva / academic panel | That you understand what you wrote — definitions, why a line exists | Medium; precise definitions matter more than scale | Prerequisite-concept sections of each doc; "explain this line" from §5 of each doc |
| Project deep-dive (30–60 min) | That you *built* it rather than followed a tutorial; they pick one thing and drill | Deep and narrow: 3–4 levels on one decision | Decision Cards ([09](09-tradeoff-cards.md)), the numbers ([16](16-rapid-revision.md)) |
| Backend / SDE technical | API design, databases, concurrency, failure handling | Medium-deep on DB and API; scale questions likely | FastAPI + SSE, Postgres schema and indexes, transactions ([05](05-database-and-sql.md), [06](06-system-design.md)) |
| ML / AI engineer screen | Retrieval quality, embeddings, evaluation methodology, honest use of metrics | Deep on retrieval and eval; expects numbers | Eval harness, ablation table, judge validation ([04](04-retrieval.md), [07](07-evaluation.md)) |
| System design | Whether you start from requirements and reason about bottlenecks | Broad, then deep on 1–2 components | Workload contract first, then the scale-up answers in [06](06-system-design.md) |
| DSA / coding | Problem solving; this project supplies natural problems | Implementation-level | Top-k heaps, merging ranked lists, LRU caches ([11](11-cs-core-touchpoints.md)) |

## 2. The progressive-questioning pattern

A deep-dive interviewer takes one thing you said and asks "why" or "how" until you reach the floor of what you know. Each answer earns a harder question. A worked example, four levels deep, on a decision from Phase 0:

**Level 1 — "You stored vectors in Postgres. Why not a vector database?"**
- *Weak:* "Postgres is popular and pgvector is easy."
- *Strong:* "At about ten documents, one database holding text, vectors, keyword index and metadata means a document update is one transaction and filters are plain SQL. A dedicated vector DB earns its keep at hundreds of millions of vectors; here it would only add a consistency problem." (Card #15.)

**Level 2 — "How does pgvector find the nearest vectors without scanning everything?"**
- *Weak:* "It uses an index."
- *Strong:* "An HNSW index — a layered graph where each vector links to its near neighbours. Search starts at the sparse top layer, greedily walks toward the query, drops a layer, and repeats. `ef_search` sets how many candidates it keeps; more candidates means higher recall and more latency." ([08](../08-database-schema.md), Phase 4.)

**Level 3 — "What happens when you add `WHERE company = 'X'`?"**
- *Weak:* "It filters the results."
- *Strong:* "The index returns the nearest candidates and the filter runs on them afterwards, so if most neighbours belong to other companies you can get fewer than k rows — a recall cliff. pgvector 0.8 added iterative index scans that keep searching until enough rows pass the filter." (Card #18, Phase 5.)

**Level 4 — "Show me the number."**
- *Strong:* "With the filter on, plain HNSW returned ⟨n⟩ of 5 rows on ⟨query⟩; with iterative scan, 5 of 5 at ⟨latency⟩ ms. Command: ⟨…⟩." (Filled in Phase 5.)
- *If you're at your floor:* "I measured it on my corpus only. Beyond that I'd expect the cliff to worsen as the filter gets more selective, because the fraction of neighbours that survive shrinks — but I haven't measured that curve." Saying where your knowledge ends, with reasoning, scores better than bluffing.

The lesson: an answer that only says *what* fails at level 2. Every doc in this repo is written to survive three pushes — learn the push, not just the first answer.

## 3. How to open: the workload contract

Senior interviewers often open on the *workload*, not the architecture. Before drawing a box, restate it — it shows you design for a real system:

1. **How big is the corpus?** (documents, pages, tokens)
2. **How often does it change?** (static, daily, continuous)
3. **How many queries?** (QPS now and at peak)
4. **Who can see what?** (one tenant, or per-user permissions over the same corpus)
5. **Are citations required?** (and at what granularity)
6. **What happens when the evidence is inadequate?** (answer anyway, or refuse)
7. **Which latency matters?** (time to first token, or complete answer)

This project's answers are in [02-architecture-overview.md §6](../02-architecture-overview.md#the-workload-contract). Say them in under a minute, then draw.

## 4. Depth by room

| Room | Wants | Avoid |
|---|---|---|
| Viva / academic | Correct definitions; that you can explain any line of your code | Hand-waving; buzzwords you can't define |
| HR | A clear story: problem → what you did → result → what you learned | Jargon; answers longer than two minutes |
| Technical (backend) | Trade-offs, failure modes, how it scales | "It just works"; ignoring concurrency and failure |
| Technical (ML/AI) | How you *know* it works: metrics, baselines, ablations, judge validation | Quoting metrics you can't derive; claiming significance on 50 questions without a test |

## 5. How ML/AI screens and backend screens read this project differently

- **ML/AI screens** will go straight to the eval harness: how the golden set was built, why recall@k before faithfulness, how the LLM judge was validated, whether the hybrid improvement is real or noise. The retrieval docs (09–12) and [07-evaluation.md](07-evaluation.md) are the core.
- **Backend screens** will go to the database and the API: schema, indexes, transactions during ingestion, SSE vs WebSockets, what happens at 1,000 QPS, connection pooling. [05](05-database-and-sql.md) and [06](06-system-design.md) are the core.
- **Both** will ask what broke and how you fixed it — [23-troubleshooting.md](../23-troubleshooting.md) is the evidence.

## 6. Company types (tendencies, not rules)

- **Product companies** tend to drill depth and trade-offs and push on scale: expect four-level drills and "how would this work at 100×?".
- **Service companies** tend to weight breadth of fundamentals, communication, and CS core: expect definitions, OOP and DBMS basics, and "explain your project simply".
- **AI startups** tend to weight shipping and practicality: evaluation, cost per query, latency, what you'd do next week.

Calibrate within the first five minutes from the questions you're actually asked.

## 7. Time management in a 45-minute round

| Minutes | What |
|---|---|
| 0–2 | Pitch (the 90-second version) |
| 2–5 | They choose a direction; you restate the workload contract if it's a design question |
| 5–35 | Deep-dive: answer, give the number, stop, let them push |
| 35–40 | Scaling or "what would you change" |
| 40–45 | Your questions for them |

Rule: answer → one number → stop. Long monologues spend your time on topics *you* chose, not on the ones that would have scored.

## 8. Driving the interview

- **Plant hooks.** Mention a specific, interesting detail in the pitch ("…and the hybrid lost to dense-only on table questions"). Interviewers follow concrete hooks. Each hook in [01-the-pitch.md](01-the-pitch.md) has its prepared answer.
- **Use controlled vocabulary.** Say the precise term and define it in half a sentence: "a recall cliff — the filter removes most of the nearest neighbours, so you get fewer than k results". It shows fluency and stops misunderstandings.
- **Offer the next question.** "I can go into how I validated the judge, if that's useful." It steers toward strong ground, and the interviewer is free to decline.
- **Bridge.** Every answer in this folder ends with a *Bridge*: a one-line way to steer from the current topic to one you're strongest on.
- **Concede cleanly.** When an interviewer finds a real weakness: acknowledge it, say what you'd measure, say how you'd fix it. Don't collapse and don't argue. See [14-honest-answers.md](14-honest-answers.md).
