# 04 — Retrieval

**Status:** started in Phase 1 (2026-10-02); main coverage from Phase 5 onward.

What this file will contain: dense vs sparse retrieval with queries where each wins; ANN vs exact search; HNSW graph construction and search walked through visually; ef_search vs recall; inverted indexes and tsvector internals; BM25 intuition (term-frequency saturation, length normalisation); RRF derived by hand; reranking; multi-hop retrieval; query rewriting, HyDE and multi-query; where this implementation would fail. Over-prep question H3 lands here.

Every question added here uses the answer format in [02-question-map.md](02-question-map.md) (30-second answer, 2-minute answer, push levels 2–4, whiteboard, trap, bridge) and gets an `**ID:**` line so the map's completeness test can find it.

---

## Phase 1 questions

### Q: Why include two years of the same company? What does that test?
**ID:** P1-02 · **Round:** project deep-dive · ML screen  **Difficulty:** 3/5

**30-second answer.** "It creates the most realistic hard negative: a 2021 and a 2022 10-K share most of their wording, so the passage that *looks* right can come from the wrong year. A user asking about 2022 revenue who gets a confident answer with a 2021 citation is the worst failure a financial assistant can have. Including both years forces retrieval to handle it."

**2-minute answer.** A **hard negative** is a non-relevant passage that is very similar to the relevant one. Year-to-year 10-Ks are full of them: risk factors, business descriptions and accounting policies are often copied forward with small edits. Vector search, which matches meaning, can't easily tell PepsiCo 2022's "FLNA Net revenue grew 19%, primarily driven by effective net pricing…" from 2021's "FLNA Net revenue grew 8%, primarily driven by effective net pricing…" — real sentences from the two filings, nearly identical in meaning. The fixes: store `fiscal_year` as metadata and filter when the question names a year (Phase 5); show document and year in every citation; measure a "wrong-year" error rate in the eval.

**If they push — level 2.** *"What if the question doesn't name a year?"* Then either answer from the latest filing and say so, or retrieve from both and let the answer cite both. I'd make "latest unless specified" the explicit default and state it in the answer.

**If they push — level 3.** *"Can keyword search help?"* Yes — years and figures are exact tokens, which is where keyword search beats vectors; hybrid fusion (Phase 7) should rank the right year higher when the question contains it.

**If they push — level 4.** *"How do you measure it?"* For each golden question, check whether any retrieved chunk in the top-k comes from the other year of the same company, and whether the answer cites it. That's a custom metric I'll add in Phase 11; I have no number yet.

**Whiteboard it.**
```text
 Q: "How much did FLNA net revenue grow in 2022?"
 PEP 2022: "FLNA Net revenue grew 19%, primarily driven by…"  ← relevant
 PEP 2021: "FLNA Net revenue grew 8%, primarily driven by…"   ← hard negative
 fix: WHERE fiscal_year = 2022  +  show year in citation   (real sentences)
```

**Trap.** "Near-duplicates should just be deduplicated." They differ in exactly the facts users ask about.

**Bridge.** "Filtering by year inside approximate vector search has its own trap — the recall cliff."

---

### Q: Why does table parsing matter for retrieval, and what's the weakness in yours?
**ID:** P2-07 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Most financial questions are answered by a table cell. Extracted naively, a table becomes a stream of numbers with no row structure, so neither keyword nor vector search can tie '16,434' to 'Net revenue'. My parser turns ruled tables into rows like `Net revenue | $ 16,434 | $ 9,763 | $ 6,731`. The weakness: column headers above the ruled area come out as separate blocks, so a chunk can contain the row without knowing which column is 2021."

**2-minute answer.** Numbers: 1,073 tables across 2,224 pages. Explain why rows help both retrievers: keyword search finds "net revenue" and the figure in one block; an embedding of a row is about one line item, not a soup of numbers. Then quantify the weakness honestly: unknown until Phase 11's table-reading questions; mitigations ready — attach header blocks directly above a table, or prepend the column header to each row.

**If they push — level 2.** *"How would you embed a big table?"* Split by rows, repeating the header and the table title on each chunk, so each piece is self-describing. That's a Phase 3 option.

**If they push — level 3.** *"Unruled tables?"* pdfplumber's line strategy misses them; they come out as aligned text blocks. The text strategy (clustering by alignment) could find them at the cost of false positives on ordinary indented text.

**If they push — level 4.** *"Would you rather store tables in SQL?"* For numeric questions across many filings, yes — extracting line items into a table and answering with SQL beats text retrieval. That's a different system (text-to-SQL) and out of scope here.

**Whiteboard it.**
```text
 naive:  "Net revenue $ 16,434 $ 9,763 $ 6,731 Cost of sales 8,505 …"
 ours:   Net revenue | $ 16,434 | $ 9,763 | $ 6,731   (row per line)
 gap:    "Year Ended … 2021 | 2020 | 2019" sits outside the table block
```

**Trap.** "Embeddings handle tables fine." Embedding a number soup loses which number belongs to which label.

**Bridge.** "Which leads to how chunk boundaries interact with tables — the chunking ablation."

---

### Q: How did you choose your chunking strategy?
**ID:** P3-01 · **Round:** project deep-dive · ML screen  **Difficulty:** 3/5

**30-second answer.** "I didn't pick one blind. Three chunkers — fixed windows, LangChain's recursive splitter, and a structure-aware one that groups whole paragraphs within a 10-K section — sit behind one interface, all with exact character offsets. Structure-aware is the default because the filings have reliable headings, but the ablation decides."

**2-minute answer.** Show the measured shapes at 256 tokens: fixed 5,604 chunks always 256 tokens and cut mid-sentence; recursive 6,538 with median 223, ending at sentence breaks; structure 7,411 with median 196 and 1,061 tiny ones from short sections. Explain why offsets make the comparison fair: relevance is overlap with labelled evidence spans, independent of how chunks were cut.

**If they push — level 2.** *"What does structure-aware do with a 1,500-character paragraph?"* If it's bigger than the chunk size it's cut into overlapping word windows inside that block — page 44's "Inventory Valuation" block became two chunks overlapping by 161 characters.

**If they push — level 3.** *"Why might it lose?"* Its many tiny chunks ("Item 4 — Not applicable") are low-information but can still score highly on keyword matches, crowding the top-k. And it inherits every heading-detection error from the parser.

**If they push — level 4.** *"How would you know chunking is the problem rather than retrieval?"* Hold retrieval fixed and vary only the chunker — that's the ablation — and look at failure cases where the evidence span was split across two chunks.

**Whiteboard it.**
```text
 fixed      |256|256|256|   cuts anywhere
 recursive  |¶ ¶|¶|¶ ¶ |    natural breaks
 structure  |Item7: ¶¶|¶|Item8: ¶|   whole blocks, one section
```

**Trap.** "Semantic chunking is best." Not without evidence on your data.

**Bridge.** "The size axis matters as much as the strategy — want the 510-token story?"

---

### Q: What does chunk overlap do, and how much do you use?
**ID:** P3-02 · **Round:** ML screen · viva  **Difficulty:** 2/5

**30-second answer.** "Overlap repeats the end of one chunk at the start of the next, so a sentence cut by a boundary appears whole in at least one chunk if it's shorter than the overlap. I use an eighth of the chunk size — 32 tokens at 256 — and only where boundaries are arbitrary: every fixed window, recursive chunks, and inside oversized blocks for the structure chunker."

**2-minute answer.** The cost side: overlap increases chunk count and total tokens (fixed at 256: 1,431,386 tokens across chunks vs ~1.28 M for structure), and adjacent overlapping chunks are near-duplicates that can both land in the top-k, wasting slots. That's why it's kept small and why structure chunks, which end at block boundaries, don't overlap at all.

**If they push — level 2.** *"How do you implement it on token windows?"* Step back from the window's end one whole word at a time until ~32 tokens repeat, always advancing past the previous start so the loop can't stall.

**If they push — level 3.** *"Why whole words?"* Cutting mid-word (on a `##` WordPiece) changes how the slice re-tokenizes — one 256-token window measured 257, which at the 510 ceiling means truncation.

**If they push — level 4.** *"Would deduplicating overlapping results help?"* Yes — merging adjacent retrieved chunks from the same document before building the prompt saves tokens. Not built; noted for Phase 9.

**Whiteboard it.**
```text
 window 1: [w1 w2 … w60]
 window 2:          [w53 … w60 w61 … w115]   ← ~32 tokens repeated
```

**Trap.** "More overlap is always safer." It multiplies vectors and near-duplicate hits.

**Bridge.** "Near-duplicates are also what the reranker and RRF have to cope with."
