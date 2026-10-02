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
