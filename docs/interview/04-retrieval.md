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

---

## Phase 5 questions

### Q: What is the recall cliff in filtered vector search, and how did you measure it?
**ID:** P5-01 · **Round:** ML screen · project deep-dive  **Difficulty:** 4/5

**30-second answer.** "An approximate index returns its best few dozen candidates; if a metadata filter runs *after* that, most candidates can be thrown away and you get fewer than k results — sometimes none. With a filter matching 6.9% of rows and the HNSW path forced, post-filtering averaged 3.8 of 10 results and returned nothing for 31 of 150 questions. pgvector's iterative scan keeps walking the graph until enough rows pass: 10 results, recall 0.973."

**2-minute answer.** Explain the arithmetic: ef_search 40 candidates × 6.9% ≈ 2.8 survivors expected. Then the twist: without forcing, Postgres pre-filtered by itself — B-tree for the 514 matching rows, exact distances, sort — so all modes scored recall 1.0. The cliff only appears when the index is chosen, which on a big table it would be. I forced it with `enable_sort = off` on a connection with auto-prepare disabled.

**If they push — level 2.** *"Why not always pre-filter?"* Exact over the filtered subset costs one distance per matching row; for a broad filter on millions of rows that's millions of distances per query.

**If they push — level 3.** *"What about multi-tenant systems?"* Tenant filters are on every query, so partitioning or a partial index per tenant is better than relying on iterative scans.

**If they push — level 4.** *"Worst case for iterative scans?"* A filter matching almost nothing: the walk continues until `hnsw.max_scan_tuples`, doing lots of work for few results. Route tiny filters to exact search after a cardinality check. Not measured.

**Whiteboard it.**
```text
 HNSW top-40 ──filter 6.9%──▶ ~2.8 rows   (post: avg 3.8, 31/150 zero)
 HNSW walk until 10 pass ───▶ 10 rows     (iterative: recall 0.973)
 B-tree 514 rows → exact ───▶ 10 rows     (exact: 1.000)
```

**Trap.** "Just add WHERE company = …". Where the filter runs decides whether results exist.

**Bridge.** "The same filter matters for the wrong-year problem — identical boilerplate across years."

---

### Q: How did you tune HNSW, and is an index even necessary at your size?
**ID:** P5-02 · **Round:** ML screen · backend screen  **Difficulty:** 3/5

**30-second answer.** "I measured recall against exact search on 150 real financial questions: ef_search 10 gives 0.742, 40 (pgvector's default) 0.928, 160 gives 0.996 — for 3.35 instead of 2.81 ms median. So 160 is the default. Honestly, an exact scan is only 11.4 ms on 7,411 vectors, so the index isn't necessary yet; it's there because the same design must work at a million vectors."

**2-minute answer.** Explain tuning order: `ef_search` first (query time, no rebuild), then `m`/`ef_construction` only if recall plateaus too low (rebuild needed). Show the curve (doc 09 chart). Note the measurement method: exact ground truth via an ORDER BY the index can't serve (`+ 0`), verified against numpy in tests.

**If they push — level 2.** *"How does latency scale?"* Exact grows linearly with rows; HNSW roughly logarithmically plus ef_search work. At 10× the rows exact would be ~110 ms; HNSW a few ms more.

**If they push — level 3.** *"Why measure on FinanceBench questions rather than random vectors?"* Recall depends on the query distribution; real questions cluster in parts of the space differently from random points.

**If they push — level 4.** *"Is recall vs exact the metric that matters?"* No — it measures the index, not relevance. Retrieval quality against labelled evidence is Phase 11; an index at 0.93 recall vs exact might cost nothing if the missed neighbours weren't relevant anyway.

**Whiteboard it.**
```text
 ef_search: 10    20    40    80    160   320  | exact
 recall:    .742  .849  .928  .976  .996  .998 | 1.0
 p50 ms:    2.77  2.82  2.81  3.02  3.35  3.90 | 11.4
```

**Trap.** Tuning `m` and rebuilding before trying `ef_search`.

**Bridge.** "Recall vs exact is index quality; relevance is what the eval harness measures."

---

### Q: Would you quantise your vectors?
**ID:** P5-03 · **Round:** ML screen · system design  **Difficulty:** 3/5

**30-second answer.** "Not at this size — but I measured it. A half-precision index was 7.93 MB instead of 13.87 with recall 0.925 vs 0.928. Binary quantisation shrank it to 2.37 MB but recall fell to 0.572 even after reranking 40 candidates with full vectors — one bit per dimension is too little for 384 dimensions. At ~100 M vectors, halfvec would be my first lever."

**2-minute answer.** Mechanism: float16 halves memory; binary keeps the sign of each dimension and compares by Hamming distance, then a full-precision rerank fixes the order of a candidate pool. Why latency didn't change: at 7,411 vectors fixed overhead dominates; quantisation pays when the index stops fitting in memory.

**If they push — level 2.** *"How would you make binary work?"* Larger rerank pool (200+), or a higher-dimensional model where signs carry more information.

**If they push — level 3.** *"Store halfvec or index halfvec?"* Expression index on `::halfvec` keeps float32 in the table for reranking; storing halfvec also halves table size but loses precision permanently.

**If they push — level 4.** *"Product quantisation?"* Codebook compression of sub-vectors; much smaller; not in pgvector — a reason to move to FAISS/Milvus at billion scale.

**Whiteboard it.**
```text
 float32 13.87 MB  .928 | float16 7.93 MB .925 | 1-bit+rerank40 2.37 MB .572
```

**Trap.** "Quantisation makes it faster" — not when the index already fits in RAM.

**Bridge.** "Memory is the first wall at scale — the system-design answer for 10 M documents starts there."

---

## Phase 6 questions

### Q: Give me queries where keyword search beats vector search, and the reverse.
**ID:** P6-01 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Keyword wins on exact tokens: '16,434' found AMD's revenue tables while vector search returned unrelated number tables; 'MI250X' found the one chunk containing that product code. Vector wins on paraphrase: for 'What was AMD's net revenue in 2021?' it found 'Computing and Graphics net revenue of $9.3 billion in 2021' without needing matching words. On 28 FinanceBench questions, vector found the evidence page for 10, keyword for 2–4, and keyword found nothing vector missed."

**2-minute answer.** Explain the mechanism: embeddings encode meaning of natural language; numbers fragment into WordPiece pieces with little semantic signal, and rare codes may never have been seen in training. Keyword matches lexemes exactly but needs vocabulary overlap ("FY22" doesn't match "fiscal 2022"). That's why they're fused — and why the golden set deliberately includes exact-token questions.

**If they push — level 2.** *"Why was keyword so weak on FinanceBench?"* Long instruction tails add matching-but-irrelevant words; "FY22"-style tokens don't appear in filings; most questions need tables that both methods miss.

**If they push — level 3.** *"How would you fix 'FY22' vs 'fiscal 2022'?"* Query rewriting (expand FY22 → fiscal 2022), a synonym dictionary in Postgres, or learned sparse retrieval (SPLADE).

**If they push — level 4.** *"Can fusion hurt?"* Yes — if one retriever is much worse, its noise can push good results down. Phase 7/12 measures it.

**Whiteboard it.**
```text
 "16,434"  keyword ✓ (phrase 16<->434)   vector ✗ (number soup)
 "MI250X"  keyword ✓ (rare token)        vector ~ (related family)
 "AMD net revenue 2021" vector ✓         keyword ~ (OR noise)
 FinanceBench hit@10: vector 10/28, keyword 2–4/28
```

**Trap.** "Hybrid is always better." Measure it.

**Bridge.** "That's the motivation for RRF — fusing two lists that fail differently."

---

### Q: Explain BM25 and compute one term's contribution.
**ID:** P6-02 · **Round:** ML screen · DSA  **Difficulty:** 4/5

**30-second answer.** "BM25 scores a document by summing, over query terms, idf × saturated term frequency normalised by length: idf(t) · tf·(k1+1) / (tf + k1·(1 − b + b·len/avg_len)), with k1 = 1.2 and b = 0.75. For 'corn' in my top Corning chunk: df 459 of 7,411 gives idf ln(16.131) = 2.781; tf 2, length 24 vs average 52.7; contribution 4.515."

**2-minute answer.** Walk the three ideas: rare terms matter more (IDF), repeating a term has diminishing returns (saturation via k1), long documents shouldn't win just by containing more words (b). Then the twist from my measurement: on this corpus Postgres's ts_rank with length normalisation matched BM25 and was twice as fast, so it's the default.

**If they push — level 2.** *"Why +0.5 in the idf?"* Smoothing from the probabilistic derivation (Robertson–Spärck Jones); the `1 +` inside the log keeps idf positive for terms in more than half the documents.

**If they push — level 3.** *"How do search engines make BM25 fast?"* Precompute per-term impact scores in the posting lists and use top-k algorithms (WAND, block-max) that skip documents that can't make the top k. My SQL version scores every candidate.

**If they push — level 4.** *"What's my length measure?"* Distinct lexemes (`length(tsvector)`), not word count — an approximation I chose because it's available without unnesting; it changes length normalisation slightly.

**Whiteboard it.**
```text
 idf = ln(1 + (N − df + .5)/(df + .5)) = ln(1 + 6952.5/459.5) = 2.781
 tf part = 2·2.2 / (2 + 1.2·(0.25 + 0.75·24/52.7)) = 4.4/2.71 = 1.624
 contribution = 2.781 · 1.624 = 4.515
```

**Trap.** Forgetting IDF, or thinking BM25 is a neural method.

**Bridge.** "And measuring it against the built-in ranking changed my default."

---

## Phase 7 questions

### Q: Derive Reciprocal Rank Fusion on a small example.
**ID:** P7-01 · **Round:** ML screen · whiteboard  **Difficulty:** 3/5

**30-second answer.** "Each chunk scores the sum, over the lists it appears in, of 1/(k + rank), with k = 60. Vector returns A, B, C, D and keyword returns C, E, B. C gets 1/63 + 1/61 = 0.032266 and B gets 1/62 + 1/63 = 0.032002. A was vector's #1 but only gets 1/61 = 0.016393, so it's third. Agreement between lists beats a single top rank. Raw scores never enter the formula, which is the point: a cosine and a ts_rank aren't comparable."

**2-minute answer.** Walk the table term by term, then the three things it shows. First, a chunk in both lists earns two terms. Second, at k = 60 rank 1 and rank 4 differ by only 5% (0.016393 vs 0.015625). Third, k decides the trade: at k = 0, A scores 1.0 and B 0.833, so A overtakes B. Mention the explicit tie-break (best single rank, then chunk id), because ties between the two lists' #1s are common. The numbers are asserted in `tests/test_hybrid.py`.

**If they push — level 2.** *"What's the complexity?"* O(total hits) to accumulate in a hash map, plus O(u log u) to sort the u distinct chunks. With two lists of 50, that's microseconds.

**If they push — level 3.** *"What happens when the lists don't overlap at all?"* It becomes a zipper: vector #1, keyword #1, vector #2… Equal ranks give equal scores, so the tie-break decides who goes first.

**If they push — level 4.** *"What if one list is much longer?"* Long lists only add low-weight tail terms. A chunk at rank 50 earns 1/110 ≈ 0.009, and appearing at rank 50 in *both* lists (0.018) beats rank 1 in one (0.016). Depth sets how deep agreement can come from.

**Whiteboard it.**
```text
 vector: A B C D      keyword: C E B          k = 60
 C = 1/63 + 1/61 = .032266   1
 B = 1/62 + 1/63 = .032002   2
 A = 1/61        = .016393   3     (k = 0: A = 1.0 > B = .833)
 E = 1/62        = .016129   4
 D = 1/64        = .015625   5
```

**Trap.** Adding or averaging raw scores, or forgetting that a chunk missing from a list contributes 0 from it.

**Bridge.** "That arithmetic also explains the one place hybrid hurt us."

---

### Q: Your hybrid search scored worse than vector search on FinanceBench. Why ship it?
**ID:** P7-02 · **Round:** project deep-dive · ML screen  **Difficulty:** 4/5

**30-second answer.** "At top-10, hybrid found the evidence for 8 of 28 FinanceBench questions and vector alone for 10. But on 50 exact-figure queries, vector found 0 in its top 5 and hybrid found all 50. Two questions out of 28 is within noise, and 50 of 50 isn't. From Phase 8, a reranker re-sorts the fused top 20. At 20, the gap is one question (0.393 vs 0.429), against a 0.02 → 1.00 gain on figures. The golden-set ablation decides finally."

**2-minute answer.** Give the per-question breakdown: hybrid gained 2 questions and lost 4. The gains were questions where both lists ranked the evidence mediocre (13 and 7 → fused 6). The losses were questions where keyword search had nothing relevant in its top 50, and its noise interleaved with vector's list. Vector's rank 4 became fused 14 or 16, and rank 1 became 20. So the cost is a ranking problem, not a recall problem, and a cross-encoder fixes ranking problems by reading the text.

**If they push — level 2.** *"So why not route queries — figures to keyword, the rest to vector?"* It's valid, but it needs a classifier that can be wrong. I'd try it only if rerank can't recover the loss.

**If they push — level 3.** *"How do you know 2 of 28 is noise?"* One question is 3.6 points. The two methods disagree on only 6 questions, 4–2. A paired sign test on 6 discordant pairs gives p ≈ 0.69 two-sided, nowhere near significant.

**If they push — level 4.** *"What would make you switch the default to vector-only?"* If the golden set, which includes exact-token, table and multi-hop questions, shows hybrid + rerank no better than vector + rerank. That would mean exact-token queries are rare or the reranker recovers them anyway.

**Whiteboard it.**
```text
                FB hit@10  FB hit@20  figures hit@5
 vector           10/28      12/28        0/50
 keyword           4/28       6/28       50/50
 hybrid RRF60      8/28      11/28       50/50
 lost: vector rank 4 → fused 16 (keyword noise interleaves)
```

**Trap.** Hiding the regression, or claiming "hybrid is always better".

**Bridge.** "The fix for interleaving is the reranker, which is the next stage."

---

### Q: What does the k in RRF actually control? How did you choose it?
**ID:** P7-03 · **Round:** ML screen  **Difficulty:** 3/5

**30-second answer.** "k sets how steeply a top rank outweighs a lower one. The weight ratio of rank 1 to rank 10 is (k + 10)/(k + 1): 10× at k = 0, 1.82× at k = 10, 1.15× at k = 60. Small k trusts each list's top hit, and large k rewards appearing in both lists. I swept 1, 10, 60 and 100. FinanceBench hit@10 ranged from 0.357 to 0.286, which is two questions of 28, and hit@20 was identical, so I kept the paper's 60."

**2-minute answer.** Show it flip the toy example: at k = 0, vector's #1 (A = 1.0) overtakes a chunk both lists liked (B = 0.833); at k = 60 it doesn't. Then the exact-figure bench, where every k gave identical results. The lists didn't overlap, so each chunk's score depended on one rank, and the order was the same for any k. k only matters when there's agreement to weigh against a top rank.

**If they push — level 2.** *"Why not choose k = 1, since it scored best?"* That's choosing the best of four on the same 28 questions I report, which is fitting noise. Tuning belongs on a held-out set.

**If they push — level 3.** *"Interpret k = 60 intuitively."* It's as if 60 imaginary results sat ahead of every real one in each list, which dampens differences among the top few positions.

**If they push — level 4.** *"Does k interact with depth?"* Yes. With large k, two deep appearances (rank 50 in both lists: 2/110) beat one top appearance (1/61), so depth bounds how much agreement can be found.

**Whiteboard it.**
```text
 weight(rank 1) / weight(rank 10) = (k+10)/(k+1)
 k=0 → 10×    k=10 → 1.82×    k=60 → 1.15×
 FB hit@10: k=1 .357  k=10 .321  k=60 .286  k=100 .286   (hit@20 all .393)
```

**Trap.** Calling 60 a magic number, or tuning it on the test set.

**Bridge.** "The bigger lever wasn't k, it was what's downstream: a reranker."

---

## Phase 8 questions

### Q: Bi-encoder vs cross-encoder: what's the difference, and why use both?
**ID:** P8-01 · **Round:** ML screen  **Difficulty:** 2/5

**30-second answer.** "A bi-encoder encodes question and chunk separately into vectors and compares them with a dot product. Chunk vectors are precomputed, so search over 7,411 chunks takes milliseconds. A cross-encoder reads question and chunk together through every layer and outputs one relevance score. It's more accurate, but nothing can be precomputed: about 7.7 ms per pair here. So the bi-encoder finds candidates and the cross-encoder re-sorts the top 10."

**2-minute answer.** Explain the accuracy difference through attention: in a cross-encoder each question token attends to each chunk token, so it can see that this table row contains the figure asked about. A bi-encoder has compressed the chunk into 384 numbers before it ever saw the question. Then give the measured effect: exact-figure top-1 went from 0.46 to 0.82 with reranking.

**If they push — level 2.** *"Where does ColBERT fit?"* It keeps one vector per token on both sides and scores with MaxSim, the sum of each question token's best match. Chunk tokens are precomputable, and the interaction is late but fine-grained.

**If they push — level 3.** *"Can you distil a cross-encoder into a bi-encoder?"* Yes. Train the bi-encoder on the cross-encoder's scores (knowledge distillation). Several strong embedding models are trained this way.

**If they push — level 4.** *"Why are cross-encoder scores not comparable across models?"* MiniLM outputs unbounded logits (−11 to +11 here), while bge-reranker applies a sigmoid. Only the ranking within one model is meaningful.

**Whiteboard it.**
```text
 bi:    q → enc → v_q ┐
        c → enc → v_c ┴→ v_q·v_c        (v_c stored at ingest)
 cross: [CLS] q [SEP] c [SEP] → transformer → score   (per pair, per query)
 cost:  bi ≈ 4 ms for all 7,411 · cross ≈ 77 ms for 10
```

**Trap.** Saying a cross-encoder "embeds" the chunk.

**Bridge.** "The interesting part was what the cross-encoder still got wrong."

---

### Q: You reranked deeper and quality went down. Explain.
**ID:** P8-02 · **Round:** project deep-dive · ML screen  **Difficulty:** 4/5

**30-second answer.** "I measured two curves. The share of questions whose evidence was anywhere in the reranker's input rose from 29% at N = 10 to 71% at N = 100. But reranked top-10 accuracy fell from 0.286 to 0.250, and at N = 50 to 0.214. The extra candidates were same-topic passages from the wrong company or year, which this corpus is full of, and a reranker trained on web search prefers a well-matched topic over the right entity. So N = 10."

**2-minute answer.** Show the per-question evidence. For a PepsiCo capex question, the reranked #1 was Corning's capital expenditures paragraph. For AMD FY22 revenue drivers, it was an AMD 2021 chunk. Then the control experiment: restricting the search to the right filing doubled top-10 accuracy to 0.607. The bottleneck is entity and year disambiguation, not ranking skill on topical relevance.

**If they push — level 2.** *"Did a bigger reranker fix it?"* No. bge-reranker-base, 12× larger, was 6× slower and no better on FinanceBench. In a smoke test it gave Corning's net sales 0.96 for an AMD revenue question.

**If they push — level 3.** *"How would you fix it without filters?"* Extract company and year from the question and filter or boost. Or add an LLM final stage that reads constraints. Or fine-tune the cross-encoder on in-domain hard negatives (pairs from the same topic, wrong filing).

**If they push — level 4.** *"Is the oracle filter a fair number?"* It's an upper bound: it assumes the right filing is known. It's realistic when a user picks the filing in the UI. An automatic extractor will land below it, and that's what Phase 12 measures.

**Whiteboard it.**
```text
 N        10     20     50     100
 ceiling .286   .393   .500   .714   evidence in the pool
 reranked .286  .286   .214   .250   evidence in top 10
 oracle filter (right filing): top 10 = .607 without any reranker
```

**Trap.** "More candidates always helps the reranker."

**Bridge.** "That's why the API exposes company and year filters, and why auto-filters are an ablation."

---

### Q: How did you choose the reranker model?
**ID:** P8-03 · **Round:** ML screen · system design  **Difficulty:** 3/5

**30-second answer.** "I benchmarked two pinned cross-encoders on the same fused candidates. MiniLM-L6 (22 M parameters, 91 MB) took 77 ms for 10 pairs on the M1 GPU. bge-reranker-base (278 M, 1.1 GB) took 435 ms. bge was 3 queries better on exact-figure top-1, 1 question worse on FinanceBench top-5, and 1 query worse on figure top-5. Not worth 6×, so MiniLM is the default, and swapping is two settings."

**2-minute answer.** Add the CPU result (153 ms for MiniLM: still usable without a GPU) and the deployment view. A 1.1 GB model is a 12× bigger download and image, more start-up time and more memory on an 8 GB laptop. Then the rule: the bigger model must win on the golden set by more than noise before it earns its cost.

**If they push — level 2.** *"Why pin the model revision?"* Model repos can be updated in place. A pinned commit makes scores reproducible, and the revision is part of the settings.

**If they push — level 3.** *"How would you speed MiniLM up?"* ONNX or quantised int8 export (the repo ships an int8 OpenVINO file of 23 MB), shorter max_length, or fewer pairs.

**If they push — level 4.** *"When would you pay for an LLM reranker?"* For few, high-value queries where entity constraints matter, with caching. Only after filters, because filters fixed most of the same failures for free.

**Whiteboard it.**
```text
               params  size    p50 (N=10, MPS)  FB@5   fig@1  fig@5
 MiniLM-L6      22 M   91 MB    76.5 ms         .179   .82    1.00
 bge-base      278 M   1.1 GB  434.7 ms         .143   .88     .98
```

**Trap.** Picking the leaderboard winner without measuring on your data.

**Bridge.** "The latency numbers feed the end-to-end budget in Phase 13."

---

## Phase 9 questions

### Q: How do you turn retrieved chunks into a prompt? What's your token budget strategy?
**ID:** P9-02 · **Round:** ML screen · system design  **Difficulty:** 3/5

**30-second answer.** "Whole chunks, best-first, until a 3,000-token budget. Each gets a header line: number, company, fiscal year, PDF page, section path. Measured on 28 FinanceBench questions, ten chunks need 2,144 tokens at p50 and 2,596 at most, so nothing is dropped and k decides the size. I never truncate a chunk, because the citation's character span must cover exactly what the model saw."

**2-minute answer.** Mention what a real prompt revealed. Headers cost 37–62 tokens each (18% of the context). Three of ten sources repeated the same revenue figures (652 tokens). The section path was sometimes wrong, and an exhibit list slipped through. Each is an ablation candidate: shorter headers, near-duplicate removal, section filters. Then the lost-in-the-middle option: a "sandwich" layout is implemented, used only if it measurably helps.

**If they push — level 2.** *"How do you count tokens for a model tiktoken doesn't know?"* o200k_base as an estimate for budgeting. Billing uses the API's reported usage.

**If they push — level 3.** *"Why skip a long chunk instead of stopping?"* One long table shouldn't block smaller, lower-ranked sources that still fit.

**If they push — level 4.** *"What would you change for a 100-page context?"* Compression or summarisation per source, hierarchical retrieval (section first, then chunks), and caching the static prefix (prompt caching).

**Whiteboard it.**
```text
 hits (rank) → fits budget? → keep / drop whole → order (rank|sandwich) → [n] header + text
 k=10: 2,144 tokens p50 · headers ≈ 440 · dup tables 652 · budget 3,000 · dropped 0/280
```

**Trap.** Truncating sources to fill the budget exactly.

**Bridge.** "Numbering by position is what lets citations map back exactly."

---

## Phase 11 questions

### Q: Where does your retrieval fail, by question type, and what would you do about each?
**ID:** P11-07 · **Round:** project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Single facts in prose: 91% in the top 5; the two misses are 'how many employees did AMD have', where same-topic paragraphs from the other year win. Tables: found in the top 10 for 69%, but first only once in 13, because prose about the same topic outranks the row. Multi-hop: only a third of the needed facts in the top 5, because one query retrieves one company well and the other badly. Fixes, in order: company/year filters, query decomposition for multi-entity questions, BM25 or table-aware chunk headers for tables."

**2-minute answer.** Use G045 as the example: 'Which had higher revenue in 2022, Boeing or Corning?' Corning's table is found at rank 3; Boeing's revenue line is nowhere in the top 10, though 9 relevant chunks exist. Decomposition, meaning one retrieval per entity with the results merged, is the standard fix. Phase 12 measures what's cheap to measure first.

**If they push — level 2.** *"Why do tables rank badly?"* Table chunks are numbers with short row labels. Their embeddings carry little meaning, and question words like 'revenue' appear more often in prose.

**If they push — level 3.** *"Exact tokens?"* 87.5% in the top 5 after the keyword fix. The remaining MI250X miss is ts_rank's lack of IDF in a long OR query.

**If they push — level 4.** *"What does this say about the reranker?"* It reorders the top 10. It can't recover a Boeing row that isn't in the pool. Recall per entity is a first-stage problem.

**Whiteboard it.**
```text
 type        hit@5  recall@5  MRR
 factual      .91     .91     .74   miss: AMD headcount (other-year paragraph wins)
 exact        .88     .88     .62   miss: MI250X (no IDF in ts_rank)
 table        .62     .62     .27   row ranked below same-topic prose
 multi-hop    .56     .33     .34   one entity found, the other not → decompose
```

**Trap.** Quoting only the overall average.

**Bridge.** "That ordering of fixes is the plan for the ablations."
