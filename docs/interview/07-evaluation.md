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

---

## Phase 10 questions

### Q: How do you test an API whose main dependency (a paid LLM) isn't available?
**ID:** P10-08 · **Round:** backend screen · project deep-dive  **Difficulty:** 2/5

**30-second answer.** "FastAPI dependency overrides. The tests replace the LLM with a scripted fake and the retriever with a fixed list, and run the app without its startup, so no models and no network. That covers contracts, eight bad-request cases, the 503 for a missing key, SSE framing, the refusal gate, an LLM timeout mid-stream (an in-band error event) and the quota error mapping. One slow test runs the real startup against the ingested database with the offline fake LLM, end to end."

**2-minute answer.** Explain the layering: unit tests of the gate and error classifier; contract tests through TestClient; one integration test with real retrieval. The SDK itself is tested against a mocked HTTP transport (Phase 9). What's left untested is real-model behaviour, which the eval harness measures, not unit tests.

**If they push — level 2.** *"How do you parse SSE in tests?"* Split the body on blank lines, read the `event:` and `data:` fields, and JSON-decode the data, like a client would.

**If they push — level 3.** *"Flaky risks?"* Global state: settings and `get_llm`'s cache are reset in each test that changes them.

**If they push — level 4.** *"Contract tests for consumers?"* The OpenAPI schema is tested for the four paths and the event-stream response, so a breaking change shows up as a failing test.

**Whiteboard it.**
```text
 unit:        RefusalGate · classify(429 quota vs rate)
 contract:    TestClient + overrides (fake retriever, scripted LLM) — 21 tests
 integration: real lifespan + DB + fake LLM — 1 slow test
```

**Trap.** Only testing with the live API, which makes tests cost money and fail when the account does.

**Bridge.** "The account really did run out of credits; the tests didn't care."

---

## Phase 11 questions

### Q: Walk me through your evaluation set. How was it built, and how do you know it's any good?
**ID:** P11-01 · **Round:** project deep-dive · ML screen  **Difficulty:** 4/5

**30-second answer.** "61 questions I wrote from the ten filings: 22 single facts, 13 table lookups, 8 exact-token questions (figures, product codes), 9 multi-hop questions spanning two filings, and 9 unanswerable ones whose absence I checked by full-text search, with wrong-year traps throughout. Each label is an exact quote, resolved to every occurrence in the stored text on every run. Weaknesses: I wrote both the questions and the system, and they reuse the filings' wording. So I always report FinanceBench beside it: hit@10 0.29 there vs 0.81 here."

**2-minute answer.** Explain the label format: items (facts the answer needs), alternatives (different passages stating the fact), occurrences. Then the label audit: searching each answer's figures across the whole filing found 8 questions with answer locations I'd missed. Adding them raised hit@5 from 0.731 to 0.769, so the earlier labels under-credited the retriever. Name the residual risk: rounded restatements ("$23.6 billion") aren't found by a figure search.

**If they push — level 2.** *"Why not generate questions with an LLM?"* Generated questions mirror chunk wording, which is leakage, and labels need review anyway. Fine for augmentation, not as the only set.

**If they push — level 3.** *"How big should it be?"* The CI on hit@5 is about ±12 points with 52 answerable questions. Halving that needs about four times as many questions. Paired tests help in the meantime.

**If they push — level 4.** *"How do you version it?"* The file's sha256 is stored in every result. Any edit makes a new hash, so old and new results are never silently compared.

**Whiteboard it.**
```text
 question → items[] → alternatives[] → occurrences (resolved each run)
 22 factual · 13 table · 8 exact · 9 multi-hop (2 filings) · 9 unanswerable (absence searched)
 audit: +8 questions' alternatives → hit@5 .731 → .769   ·   FinanceBench hit@10 .29 (external)
```

**Trap.** Presenting a self-written set's numbers as general accuracy.

**Bridge.** "Which is why every number comes with an interval and an external comparison."

---

### Q: Derive nDCG@3 for a ranking, and explain why you use graded relevance.
**ID:** P11-02 · **Round:** ML screen · whiteboard  **Difficulty:** 3/5

**30-second answer.** "DCG@k sums, over positions i, (2^g − 1) / log₂(i + 1), where g is the grade. IDCG is the same sum for the best possible ordering of all relevant chunks. nDCG = DCG / IDCG. Example: ranks 1–3 graded 0, 2, 1 with an ideal of [2, 2]: DCG = 3/log₂3 + 1/log₂4 = 1.893 + 0.5 = 2.393; IDCG = 3/1 + 3/log₂3 = 4.893; nDCG = 0.489. Grades: 2 if the chunk holds the whole evidence quote, 1 if at least half (it straddles a chunk boundary)."

**2-minute answer.** Explain why the ideal ranking comes from *every* chunk in the set that overlaps the evidence, not just retrieved ones. Otherwise a retriever that finds one weak chunk would look perfect. Then a real example: G045 has 9 relevant chunks in the set and one found at rank 3, so nDCG@3 = 1.5/6.393 = 0.2346 and nDCG@10 = 0.1175, exactly what the result file says.

**If they push — level 2.** *"Why 2^g − 1?"* It's the common gain function: it makes a fully relevant chunk worth 3× a partial one, not 2×. A linear gain (g) is also used. The choice should be stated.

**If they push — level 3.** *"MRR vs nDCG?"* MRR looks only at the first relevant result. nDCG counts all of them, graded, with a log discount.

**If they push — level 4.** *"What's nDCG's blind spot for RAG?"* It doesn't know the generator reads all k chunks almost equally. A relevant chunk at rank 8 may be as useful as one at rank 2. That's why recall@k is the headline and nDCG explains.

**Whiteboard it.**
```text
 grades  0  2  1      ideal 2 2
 DCG  = 0 + 3/log₂3 + 1/log₂4 = 1.893 + 0.5 = 2.393
 IDCG = 3/log₂2 + 3/log₂3     = 3 + 1.893   = 4.893   → nDCG@3 = 0.489
```

**Trap.** Computing IDCG from the retrieved list only.

**Bridge.** "The same graded labels drive every other metric."

---

## Phase 12 questions

### Q: You ran 57 configurations. Which one won, and how sure are you?
**ID:** P12-01 · **Round:** project deep-dive · ML screen  **Difficulty:** 4/5

**30-second answer.** "On my golden set, the default (structure-aware 256-token chunks, hybrid RRF, cross-encoder rerank) tied for best at hit@5 0.769, and nothing beat it significantly in a paired sign test. 30 configurations were significantly worse. But the winner depends on the test set. Across the 54 grid configurations, golden-set and FinanceBench scores have a rank correlation of −0.53. So the honest answer is that hybrid + rerank is the robust choice, and 'the best' configuration for real users needs questions in their own words."

**2-minute answer.** Walk through the three findings: the reranker's consistent gain (23 of 27 pairs, +0.067); the keyword/vector inversion between the two sets, explained by my questions reusing filing wording; and the winner's-curse risk, since the default is the best cell of the weakest chunking strategy on average and the configuration I debugged on. Then the candidate to re-test: fixed256-hybrid-rr (FinanceBench 0.393 vs 0.286, golden 0.712, n.s.).

**If they push — level 2.** *"Why not just switch to the FinanceBench winner?"* Vector-only 510 scores 0.500 there, but finds exact figures only 12.5% of the time. Users quote figures.

**If they push — level 3.** *"Multiple comparisons?"* 57 tests at 0.05 would give about 3 false positives. 30 significantly-worse configurations is far beyond that, and zero better is the informative part.

**If they push — level 4.** *"What experiment settles it?"* 50 new questions written in users' own words, the top 5 configurations, and paired tests. Decide on that set, not on either existing one.

**Whiteboard it.**
```text
 golden best: base .769 = fixed256-kw-rr .769 (6/6, p 1.0)   none significantly better · 30 worse
 FinanceBench: vector-only best (.50), keyword worst (.14)    Spearman(golden, FB) = −0.53
 robust: hybrid + rerank   ·   candidate: fixed256-hybrid-rr (FB .393, golden .712 n.s.)
```

**Trap.** Reading the top row of the table as the answer.

**Bridge.** "Which is why the eval harness reports an external set at all."

---

### Q: Your own test set and FinanceBench disagree. Which do you trust?
**ID:** P12-02 · **Round:** ML screen · project deep-dive  **Difficulty:** 4/5

**30-second answer.** "Neither alone, because they measure different things. My golden questions copy the filings' wording, so keyword search, which matches words, scores 0.638 on average there but 0.183 on FinanceBench, whose analysts paraphrase. Vector search is the reverse: 0.453 vs 0.401. A choice that's only good on one set is tuned to its question style. Hybrid is mid-to-top on both, which is the property I want when I don't know the users' style."

**2-minute answer.** Name the general lesson as external validity: a benchmark's question-writing process is part of what it measures. Then the fix: diversify how questions are written (paraphrases of the golden questions, user logs), and report results per style rather than averaging them away.

**If they push — level 2.** *"Could you paraphrase your golden questions automatically?"* Yes, with an LLM, keeping the evidence labels. That's a cheap way to test wording sensitivity, and it would be reviewed by hand.

**If they push — level 3.** *"Is FinanceBench perfect?"* No: page-level labels and only 28 questions on these filings, and many need calculations across statements. It's a check, not ground truth.

**If they push — level 4.** *"Would this change your hybrid weighting?"* Possibly. A vector-heavier fusion might suit paraphrased questions. That's an ablation on the new question set, not a decision from these.

**Whiteboard it.**
```text
            golden (filing wording)   FinanceBench (paraphrase)
 vector          .453                       .401
 keyword         .638                       .183
 hybrid          .649                       .302   ← robust
```

**Trap.** "My test set says X, so X."

**Bridge.** "The same bias is why I'd never tune the reranker on the golden set alone."

---

### Q: What did the closed-book baseline show?
**ID:** P12-09 · **Round:** project deep-dive · ML screen  **Difficulty:** 3/5

**30-second answer.** "With retrieval, answers were judged correct on 72.1% of answerable questions; the same model with no documents got 6.7%. That's 37 questions won to 4 in a paired test. So the filings, not the model's memory, provide almost all the accuracy: the specific figures in a 10-K aren't memorised. And without sources, the model answered 3 unanswerable questions from memory or guesswork, including an AMD fiscal 2024 revenue figure. With sources and the refusal rule, it refused all 9."

**2-minute answer.** Explain why it matters for any RAG claim: a high RAG score means little if the model already knew the answers. Name what closed book could still answer (Boeing ending 747 production, partly the companies' total revenue), and that it refused 42% of answerable questions, where RAG refused 23%.

**If they push — level 2.** *"Is 0.067 a fair baseline?"* Same questions, same judge, same generator; only retrieval differs, plus a prompt that allows refusal. It's the fair comparison.

**If they push — level 3.** *"What about a bigger model closed-book?"* It would know more famous numbers, but segment shares and headcounts by year are unlikely. Measure it rather than assume.

**If they push — level 4.** *"Could memory leak into the RAG answers?"* Possibly. That's why faithfulness is checked against cited sources (0.923), and why correctness is checked separately.

**Whiteboard it.**
```text
                RAG     closed book
 correct        .721    .067     (37 vs 4, p < 1e-6)
 refused unans  9/9     6/9      (answered Apple, Tesla, AMD FY2024)
 false refusals 23%     42%
```

**Trap.** Reporting RAG accuracy without the no-retrieval number.

**Bridge.** "And the RAG failures that remain are mostly retrieval misses, which is where the next work goes."

---

### Q: The model sometimes wrote an explanation and then the refusal token. How did that affect your numbers?
**ID:** P12-10 · **Round:** ML screen · debugging  **Difficulty:** 2/5

**30-second answer.** "The prompt says to reply with exactly INSUFFICIENT_CONTEXT, but about 1 time in 15 the model explained first and appended the token, or put it in brackets: 4 of 61 RAG answers and 4 of 61 closed-book answers. My detector only accepted the bare token, so those refusals were scored as wrong answers, and faithfulness read 0.859 instead of 0.923. Now the token anywhere, in an answer with no citations, counts as a refusal, and a stray token beside a cited answer is stripped."

**2-minute answer.** The lesson: a model's format compliance is a measured rate, not an assumption, so parsers must tolerate drift. And the first pass of an evaluation is not the result: read the failures before reporting. Correctness was unaffected (0.721 both times), because these answers scored 0 either way.

**If they push — level 2.** *"Why not JSON output to force the format?"* It's possible, and it would make refusal a field. The cost is streaming and output tokens (card #29). A tolerant parser plus measurement was cheaper.

**If they push — level 3.** *"Streaming?"* The refusal gate holds text only while it could be the bare token. An explanation streams before the token arrives, but the final `answer` event marks it refused. The UI should replace the text then.

**If they push — level 4.** *"Could the new rule misfire?"* On a substring like "INSUFFICIENT_CONTEXTUAL": no, it requires a whole word (tested). On an answer that cites and also refuses: it's treated as an answer, with the token removed.

**Whiteboard it.**
```text
 '…none include an employee headcount.\n\nINSUFFICIENT_CONTEXT'  → was "answer", now refusal
 '[INSUFFICIENT_CONTEXT]'                                       → was "answer", now refusal
 faithfulness .859 → .923 · false refusals 15% → 23% · correctness .721 (unchanged)
```

**Trap.** Trusting that the model follows the exact output format.

**Bridge.** "Measured compliance belongs in the eval report next to quality."

---

## Phase 13 questions

### Q: How do you make sure caching doesn't distort your latency and cost numbers?
**ID:** P13-08 · **Round:** ML screen · project deep-dive  **Difficulty:** 2/5

**30-second answer.** "Every receipt records `cached`, and a cache hit has zero list and billed cost. Latency benchmarks use questions that aren't in the cache: the bench takes an `--offset` past questions answered before. /stats reports the cache hit rate (0.0 on the benchmark's fresh questions). An eval re-run from cache is labelled as such and its latency is never reported as model speed: the 61-question judged rerun took 26 s purely from cache."

**2-minute answer.** The general rule: measurement conditions must be part of the record. For latency, cold vs warm cache (and cold vs warm GPU, as Phase 13 found) changes the numbers by orders of magnitude.

**If they push — level 2.** *"Would you report cached latency anywhere?"* As user-perceived latency for repeat questions, labelled, separately.

**If they push — level 3.** *"Embedding cache?"* Also counted (`query_embedding_cache_hit`), because it removes a 17–226 ms stage.

**If they push — level 4.** *"Production?"* Report latency split by cache hit/miss, because the mix changes with traffic.

**Whiteboard it.**
```text
 receipt.cached → cost 0 · bench --offset past cached questions · /stats cache_hit_rate
 eval rerun from cache: 26 s, 0 tokens (labelled, not a latency number)
```

**Trap.** Celebrating a 26 s "61-question eval".

**Bridge.** "Every number in the docs says how it was measured."

---

## Phase 14 questions

---

### Q: How did you evaluate your prompt-injection defences?
**ID:** P14-08 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Seven attacks I wrote: override, forged source header, image exfiltration, forced refusal, fence escape, phishing link, and a paraphrase with no trigger words. For four questions each, the attack is inserted at rank 2 into the real retrieval results and sent to a real model under four configurations, with a no-poison control per question. On gpt-oss-20b: 6 of 28 succeeded on the old system, 3 with the new prompt only, 1 with everything."

**2-minute answer.** Report per layer, because they differ in kind: the screen and output policy are deterministic and unit-tested; the prompt is probabilistic. Name the limits: one model, n=28, self-written attacks, one position. The production generator's rerun waits on its daily quota. And the false-positive side: 0 of 69,176 real chunks flagged.

**If they push — level 2.** *"Why rank 2?"* A poison that repeats the question's words would rank high; not rank 1, so the result isn't just 'the top source wins'.

**If they push — level 3.** *"Adaptive attackers?"* They'd beat a fixed suite; the suite is a regression test, not a proof.

**If they push — level 4.** *"Why a separate model?"* Groq's per-model daily quota for qwen was exhausted; gpt-oss-20b has its own.

**Whiteboard it.**
```text
 7 attacks × 4 questions × {v1, v2, v2+out, full} + control
 successes: 6 · 3 · 3 · 1   laundered: 1 → 0   FP: 0 / 69,176
```

**Trap.** Claiming 'robust to prompt injection' from one suite.

**Bridge.** "The ablation discipline from Phase 12, applied to security."
