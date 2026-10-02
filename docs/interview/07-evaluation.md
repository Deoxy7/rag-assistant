# 07 — Evaluation

**Status:** started in Phase 1 (2026-10-02); main coverage in Phase 11.

What this file will contain: every metric derived from a worked example with hand-computed numbers; why retrieval is measured before generation; building the golden set and its biases; LLM-as-judge reliability, variance and how the judge is validated; faithfulness vs answer relevance vs context precision; statistical significance on ~50 questions (and the honest admission that it's a small sample); how to present the ablation table verbally; what the numbers do not prove. Over-prep questions H1 and H2 land here.

Every question added here uses the answer format in [02-question-map.md](02-question-map.md) (30-second answer, 2-minute answer, push levels 2–4, whiteboard, trap, bridge) and gets an `**ID:**` line so the map's completeness test can find it.

---

## Phase 1 questions

### Q: What makes a good evaluation corpus? Why not test on a small clean set of articles?
**ID:** P1-01 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "A good eval corpus reproduces the hardest realistic version of the workload. On clean articles every technique looks good, so an ablation shows nothing. Mine is ten real 10-Ks: 606 table pages, a fixed legal structure, exhibits that are three-quarters of PepsiCo's files, and two near-identical years per company — the things that actually break retrieval."

**2-minute answer.** Name the properties and the measured number for each: structure (22 Item headings per filing), tables (606 of 2,224 pages), noise (running headers on up to 144 of 215 pages), near-duplicates (2021 vs 2022 of each company), imbalance (PepsiCo = 1,052 of 2,224 pages), and an external question source (28 FinanceBench questions). Then the principle: a corpus is a test bench; its job is to make differences between methods *visible*.

**If they push — level 2.** *"Isn't ten documents too few?"* For scale claims, yes, and I don't make them. For retrieval it's 1.4 M tokens and thousands of chunks with hard near-duplicates. The genuinely small part is the question set (~50–80), which limits statistical power more than the corpus does.

**If they push — level 3.** *"How does the PepsiCo imbalance bias your results?"* Pooled metrics over chunks would be dominated by PepsiCo; pooled over *questions* they're dominated by whichever documents have the most questions. I'll report per-document breakdowns alongside pooled numbers so one company can't hide a failure elsewhere.

**If they push — level 4.** *"Would your conclusions transfer to contracts or medical records?"* Partly: the mechanisms — keyword search winning on exact identifiers, near-duplicates confusing retrieval — are general, but the specific winning chunk size or k is corpus-dependent. I'd rerun the ablation, not reuse the numbers.

**Whiteboard it.**
```text
 property        measured
 tables          606 / 2,224 pages
 exhibits        1,142 pages after signatures
 near-dupes      2021 vs 2022 × 5 companies
 external Qs     28 (FinanceBench)
```

**Trap.** "More documents = better corpus." Size without difficulty measures nothing.

**Bridge.** "That's why the golden set mixes FinanceBench questions with my own table and multi-hop questions."

---

### Q: What is FinanceBench, and why use it alongside your own questions?
**ID:** P1-07 · **Round:** ML screen  **Difficulty:** 3/5

**30-second answer.** "FinanceBench (Islam et al., 2023) is a benchmark of questions over public-company filings, written by annotators with the evidence page recorded. Its open-source sample has 150 questions; 28 are on my ten filings. Using them means part of my evaluation was written by people who never saw my chunks, which reduces the risk that my questions are unconsciously tailored to my own pipeline."

**2-minute answer.** Explain the leakage risk: if I write questions while looking at my own chunks, I'll phrase them in the chunks' vocabulary, which flatters retrieval — especially keyword search. External questions don't have that bias. Their evidence page numbers also map onto my page-level offsets, so I can convert them to evidence spans. Caveats: 28 is small, many FinanceBench questions need numerical reasoning (a generation problem, not retrieval), and the licence is CC BY-NC 4.0 — fine for a portfolio project, not for commercial reuse.

**If they push — level 2.** *"Are their page numbers compatible with yours?"* Their evidence pages are zero-indexed; mine are one-based. That off-by-one is exactly the kind of thing a test should pin (Phase 11).

**If they push — level 3.** *"Could the LLM have seen FinanceBench during training?"* Possibly — it's public. That would inflate closed-book scores on those questions, which is one more reason to report FinanceBench and self-written questions separately.

**If they push — level 4.** *"How would you know if your questions are biased toward your pipeline?"* Compare the two subsets: if my questions score much higher than FinanceBench's at equal difficulty, my questions are probably tailored. It's a heuristic, not proof; I haven't run it yet (Phase 11).

**Whiteboard it.**
```text
 golden set = FinanceBench (external, 28)  +  mine (tables, multi-hop, unanswerable)
              └─ report separately ─┘          └─ watch for vocabulary leakage
```

**Trap.** "I wrote all the questions myself, so I know they're correct." Correct isn't the issue — bias is.

**Bridge.** "The same bias question applies to the LLM judge — that's how I validate it."

---

### Q: How do you know your parser is good enough?
**ID:** P2-08 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Three layers. Invariants that must always hold — slicing the canonical text with every block's offsets returns exactly that block, for all 30,327 blocks. Rule tests on synthetic PDFs, one per quirk I found. And per-document statistics compared across the corpus, which is how the PepsiCo header bug and Corning's missing headings showed up. Whether it's good enough *for answers* is measured downstream: table and section questions in the golden set."

**2-minute answer.** Explain why parsing quality is best judged by its effect: a perfect-looking parse that still loses column headers will show up as failed table questions; an imperfect level-3 heading list may not matter at all. So the eval reports metrics by question type (table-reading vs prose), and a parser change is accepted only if those don't regress.

**If they push — level 2.** *"Why not a labelled parsing benchmark?"* Labelling block boundaries and reading order for even 50 pages is hours of work; I'd do it if retrieval failures pointed at parsing.

**If they push — level 3.** *"What would you compare against?"* A second parser's output on the same pages (pdfplumber-only, or a vision model on a sample), diffing text coverage: characters present in one and missing in the other point at extraction gaps.

**If they push — level 4.** *"Is the offset invariant sufficient?"* No — it proves internal consistency, not that the text is right. A block could be the wrong paragraph in the wrong order and still satisfy it. That's why outputs were also read by eye on sample pages.

**Whiteboard it.**
```text
 1 invariants   text[b.start:b.end] == b.text   (30,327 / 30,327)
 2 rule tests   synthetic PDF per quirk         (16 tests)
 3 outliers     per-doc stats vs siblings
 4 downstream   golden questions by type        (Phase 11)
```

**Trap.** "All tests pass, so parsing is correct." Tests prove what they check.

**Bridge.** "That's the same reasoning as measuring retrieval separately from generation."

---

### Q: How can you compare retrieval quality across chunking strategies when each produces different chunks?
**ID:** P3-08 · **Round:** ML screen  **Difficulty:** 4/5

**30-second answer.** "Labels aren't chunk ids — they're evidence spans: document, page, and character range of the passage that answers the question. Every chunk from every strategy is a character range of the same canonical text, so 'is this retrieved chunk relevant?' becomes 'does it overlap the evidence span enough?', which works for any chunking."

**2-minute answer.** Why chunk-id labels fail: re-chunking changes ids, so labels would only be valid for one configuration and the ablation would need relabelling nine times. Spans survive. The judgement call is the overlap rule — e.g. relevant if the chunk covers at least half the span, or the span covers at least half the chunk when the evidence is a whole table. That threshold changes the numbers, so it's defined once, tested, and reported.

**If they push — level 2.** *"Doesn't a bigger chunk get more 'relevant' hits for free?"* Yes — bigger chunks overlap evidence more easily, flattering recall. That's why precision and the median chunk size are reported alongside, and the overlap rule is relative to the span.

**If they push — level 3.** *"What about evidence split across two chunks?"* Both partial chunks may fall below the threshold; the question then shows as a miss for that configuration — which is a real retrieval weakness, not a labelling artefact, and exactly what the strategy comparison should reveal.

**If they push — level 4.** *"Is there a threshold-free alternative?"* Character-level recall: the fraction of evidence characters covered by the union of top-k chunks. It's continuous and threshold-free, but less standard than recall@k; I'd report it as a secondary metric.

**Whiteboard it.**
```text
 evidence span:      [==========]            doc, 188700–189100
 chunk A (fixed):  [=====]                   overlap 40%
 chunk B (struct):    [================]     overlap 100%  → relevant
```

**Trap.** Labelling chunk ids and then changing the chunker.

**Bridge.** "That overlap rule is defined in Phase 11 — it's the heart of the harness."

---

### Q: You implemented BM25 and then didn't make it the default. Defend that.
**ID:** P6-05 · **Round:** project deep-dive · ML screen  **Difficulty:** 3/5

**30-second answer.** "I built BM25 to test the textbook claim that it beats Postgres's ranking on this corpus. On 28 FinanceBench questions ts_rank found the evidence for 4, BM25 for 2 — noise at that sample size, but no evidence for BM25 — and ts_rank was 31 ms vs 72. Both handled the failure case that motivated BM25. So the simpler, faster option is the default and BM25 stays switchable for the larger golden set in Phase 12."

**2-minute answer.** Explain why 2 vs 4 of 28 is noise: one question is 3.6 points; a paired test on 28 binary outcomes with only a few disagreements can't distinguish them. State what would change the decision: a significant gain on the larger, more exact-token-heavy golden set.

**If they push — level 2.** *"Wasn't building it wasted effort?"* It produced a measured answer to a question interviewers ask ("why not BM25?"), it's 40 lines, and it remains an ablation axis.

**If they push — level 3.** *"How many questions would you need?"* It depends on how often the methods disagree; with a handful of disagreements per 30 questions, you'd need hundreds to detect a few-point difference reliably. That's the H1 over-prep topic.

**If they push — level 4.** *"Could the golden set be biased toward one ranker?"* Yes — if I write questions using document wording, keyword methods benefit. Reporting FinanceBench (external) separately guards against that.

**Whiteboard it.**
```text
 hit@10 (28 q): ts_rank 4 · bm25 2 · ts_rank_cd 2   → no evidence for bm25
 latency:       31 ms     72 ms     47 ms           → default ts_rank
```

**Trap.** Shipping the textbook-best option without measuring.

**Bridge.** "Significance on small samples is exactly what the eval harness has to handle."

---

## Phase 7 questions

### Q: With 28 labelled questions, how do you decide whether hybrid beats vector?
**ID:** P7-07 · **Round:** project deep-dive · ML screen  **Difficulty:** 4/5

**30-second answer.** "Mostly, you can't. One question is 3.6 points. Hybrid and vector disagreed on 6 questions, hybrid winning 2 and losing 4, and a paired sign test on 6 discordant pairs isn't close to significant. So I didn't decide on that set alone. I added a second, mechanically labelled set of 50 exact-figure queries, where the gap is 0 vs 50, which is not noise. The real decision is deferred to a 50+ question golden set with question types chosen on purpose."

**2-minute answer.** Explain why the comparison is paired. Both methods answer the same questions, so only the discordant questions carry information, not the two hit rates. Name the sweep problem: choosing the best k or weight out of several on these 28 questions and then reporting it is test-set tuning. Hence "k = 60 kept, weighted α = 0.5 not adopted despite +2 questions". Then the remedies: more questions, stratification by type (exact-token, table, multi-hop, unanswerable), and bootstrap confidence intervals in the harness.

**If they push — level 2.** *"Compute the sign test."* 6 discordant pairs, split 4–2. P(≥ 4 of 6 one way | p = 0.5) = (15 + 6 + 1)/64 = 0.34, so 0.69 two-sided.

**If they push — level 3.** *"Isn't your figures set unfair to vector?"* It's artificial: the query is just the figure. That's why it's reported as its own column, not merged into an average. It measures one capability, exact-token lookup.

**If they push — level 4.** *"How many questions would you need?"* It depends on the discordance rate. To detect a 10-point difference with ~20% of questions discordant at 80% power, on the order of 200 questions. 50 detects only large effects, and I'll say so in the report.

**Whiteboard it.**
```text
               hybrid hit   hybrid miss
 vector hit        6             4   ← lost by hybrid
 vector miss       2            16   ← 2 gained
 discordant = 4 + 2 = 6 → split 4–2 → sign test p ≈ 0.69
```

**Trap.** Reporting "hybrid −7 points" as a finding, or tuning k on the test set.

**Bridge.** "That's why the eval harness reports confidence intervals, not just means."

---

## Phase 8 questions

### Q: What is a recall ceiling, and why did you measure it next to reranked accuracy?
**ID:** P8-05 · **Round:** project deep-dive · ML screen  **Difficulty:** 3/5

**30-second answer.** "The recall ceiling is the share of questions whose evidence is anywhere in the reranker's input. No reranker can beat it, so the gap between the ceiling and the reranked result is the reranker's own loss. Here the ceiling at N = 100 was 0.714 and the reranked top-10 was 0.250. That tells me the problem is judgement, not recall, and spending effort on a better first stage would be wasted."

**2-minute answer.** Decompose any end-to-end miss into stages: not retrieved (first-stage recall), retrieved but not ranked high (reranker), ranked high but answered wrongly (generator, Phase 9). The ceiling separates the first two. A third run, the oracle filter, shows what share of the reranker's loss is entity confusion: with the right filing, the ceiling at N = 10 is 0.607 and reranked top-5 rises to 0.464.

**If they push — level 2.** *"Why does it matter for planning?"* It tells you which component to improve. Here it's not embeddings or depth, but entity filtering and reranker judgement.

**If they push — level 3.** *"How does this generalise?"* Every multi-stage system should report each stage's ceiling: retrieval recall@N, rerank recall@k, generation faithfulness given the right context. Phase 11's harness computes recall@k per stage.

**If they push — level 4.** *"Any caveat with your hit definition?"* A hit is a chunk on an evidence page, not one containing the exact answer sentence. That overstates hits when a page has several chunks. The golden set (Phase 11) uses evidence spans instead.

**Whiteboard it.**
```text
 miss = not in pool        (1 − ceiling)
      + in pool, ranked low (ceiling − reranked)   ← here .714 − .250
      + ranked high, answered wrong (Phase 9)
```

**Trap.** Tuning the first stage when the loss is in the reranker.

**Bridge.** "The eval harness makes this per-stage breakdown routine."

---

## Phase 9 questions

### Q: What's the difference between a valid citation and a faithful answer, and how would you measure each?
**ID:** P9-05 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "A citation is valid if the source number exists and maps to a stored chunk. My code checks that deterministically: invalid markers are removed and counted, uncited claims are flagged. An answer is faithful if each claim is actually supported by the source it cites. That needs reading: an LLM judge or a human checks each claim against its source. A valid citation on a wrong number is the dangerous case, because it looks trustworthy."

**2-minute answer.** Add the in-between metrics: citation precision (the share of citations that support their claim) and citation recall (the share of claims with a supporting citation). Add a cheap automatic pre-check: numbers in the claim appear in the cited text. Then answer correctness against the golden answer. Phase 11 implements these. Today, with the fake model, only validity is measured (0 invalid markers, 0 uncited claims on 26 answers), and that says the parser works, not that a model cites well.

**If they push — level 2.** *"Judge bias?"* Judges favour long answers and their own model family, and vary across runs. Pin the judge, cache it, and check it against a human-labelled sample.

**If they push — level 3.** *"Could the generator grade itself?"* It's cheaper but biased toward agreeing with itself. Use a different or stronger model as judge, or at least a different prompt.

**If they push — level 4.** *"What's a claim?"* Here, a sentence with a digit or at least four words. A judge can decompose sentences into atomic claims, at extra cost.

**Whiteboard it.**
```text
 valid      : [n] ∈ sources                      (code, exact)
 cited      : every claim has ≥1 [n]             (code, heuristic)
 faithful   : source[n] supports the claim       (judge / human)
 correct    : matches the golden answer          (judge / exact for numbers)
```

**Trap.** Reporting "100% of answers cited" as quality.

**Bridge.** "The eval harness measures all four, separately."
