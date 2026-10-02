# 14 — Honest answers

**Status:** started in Phase 0 (2026-10-02); the "partly understood" list is updated every phase. Planned: how to say "I don't know" in a way that scores points; claims never to make; handling an interviewer who is wrong; conceding without collapsing.

---

## What this project does not demonstrate (keep this list current)

- **No production traffic and no real users.** Every latency number comes from one laptop and one client.
- **A small corpus.** About ten filings (exact size in Phase 1). Anything said about millions of documents is reasoning, not measurement.
- **Single node.** No replicas, sharding or failover were built or tested.
- **A small, self-written eval set.** About fifty questions written by us — small samples make small differences look meaningful (over-prep question H1).
- **No backups, no high availability.** The database is re-derivable from the PDFs; that's the only reason this is acceptable.

## How to say "I don't know" and still score

1. **Acknowledge** plainly: "I haven't measured that."
2. **Reason from first principles** out loud: "I'd expect X, because Y."
3. **Say how you'd find out**: "I'd test it by Z, and the number I'd look at is W."

## Claims never to make

- That RAG eliminates hallucination.
- That any metric difference is significant without a significance test.
- That pgvector, or anything else, "scales to N" without having measured it or shown the arithmetic.
- Any number not produced by a command you can name.

## Things I only partly understand (honest list — update every phase)

| Topic | What I know | What I don't | How I'd find out |
|---|---|---|---|
| pgvector HNSW under deletes and updates | Postgres writes new row versions; dead ones are cleaned by VACUUM, including their index entries | Exactly how pgvector repairs the HNSW graph when entries are removed | Read pgvector's source and docs; measure recall before and after mass deletes (Phase 4–5) |
| Docker registry `referrers` request (T-001) | The pull failed there after layers downloaded; a retry worked | Exactly why Docker fetches that endpoint during a pull | Docker and OCI distribution-spec documentation |
| LangChain's Postgres vector store layout | It manages its own tables and, as far as I know, stores metadata as JSON | Its current schema in detail | Read the current package source before claiming more in a design review |
| Research on fine-tuning vs retrieval for new knowledge | Ovadia et al. (2023) and Gekhman et al. (2024) are the papers I'd cite | Their exact numbers and setups | Read both before quoting anything beyond the headline |
| Colima's port forwarding | The observable path: Mac 127.0.0.1:5432 → VM → container; the server sees 172.18.0.1 | The implementation | Colima / Lima documentation |

## The five over-prep questions (from [02-question-map.md](02-question-map.md))

H1–H5 each get an honest-answer section here once their evidence exists (Phases 4, 5, 11, 12, 13). Until then, the honest answer to each is "not yet measured" — and saying exactly that, with the phase that will measure it, is the right answer.

### "What's your answer quality with the real model?" (asked after Phase 9)
**ID:** P9-08 · **Round:** project deep-dive  **Difficulty:** 2/5

**30-second answer.** "At the end of the generation phase I hadn't measured it, because the API key wasn't available yet. Everything was built and tested against the real SDK with a mocked transport and a deterministic fake model, and every output is labelled with its provider. What I can state is pipeline behaviour: context p50 2,144 tokens, 0 invalid citations, all 7,411 citation spans exact. Quality numbers come from the eval harness with the real model."

**2-minute answer.** Explain why I didn't estimate: inventing an accuracy number is worse than saying "not measured". Then the cost estimate, labelled as an estimate: about $0.00024 input per question at the published price. And the plan: one command (`make bench-answer`) fills in the numbers once the key is in `.env`.

**If they push — level 2.** *"Why not just use a free local model?"* It would measure a different system. The design target is the OpenAI generator, and I'd rather report "not yet" than a proxy.

**If they push — level 3.** *"What would you expect?"* I'd only say what the retrieval numbers bound. Evidence is in the top 10 for about 29% of FinanceBench questions (61% with the right filing), so answer accuracy can't exceed that unless the model answers from memory, which rule 2 forbids.

**If they push — level 4.** *"Isn't the fake misleading?"* Only if unlabelled. It's opt-in (`LLM_PROVIDER=fake`), never a fallback, and its outputs say "fake".

**Whiteboard it.**
```text
 measured : pipeline (tokens, citation validity, spans, retrieval latency)
 estimated: cost ≈ $0.00024 input / question (published price × counted tokens)
 not yet  : accuracy, faithfulness, refusal accuracy, LLM latency
```

**Trap.** Quoting a number you didn't measure.

**Bridge.** "The golden set and judge fill exactly these gaps."
