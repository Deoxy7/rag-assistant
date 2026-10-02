# 03 — Fundamentals

**Status:** started in Phase 0 (2026-10-02). Questions are appended each phase. Planned coverage: embeddings and why similar meaning gives nearby vectors; cosine vs dot vs Euclidean on 3-dim toy vectors (Phase 4); tokenisation; context windows; hallucination and grounding; temperature and sampling (Phase 9); embedding model vs reranker vs generator (Phase 8); what a transformer does, without overclaiming.

---

### Q: Why did you use RAG instead of fine-tuning the model on your documents?
**ID:** P0-01 · **Round:** project deep-dive · ML screen  **Difficulty:** 2/5

**30-second answer.** "Because the answers have to come from specific filings and cite the exact passage, and filings change. Fine-tuning changes a model's weights — good for teaching behaviour like format or tone, unreliable for storing exact figures, and it can't point back to a source. RAG looks the passage up at question time, so it's citable and updating a document means re-indexing, not retraining."

**2-minute answer.** Add: the distinction between **parametric memory** (in the weights) and **non-parametric memory** (an index you can search, update and cite), from the paper that named RAG (Lewis et al., 2020). Fine-tuning writes into parametric memory, which has three problems for this workload: no citations, unreliable recall of facts seen a few times (comparisons of the two approaches for adding new knowledge favour retrieval — Ovadia et al., 2023), and every corrected filing means another training run. The number that settles it for *this* system is the closed-book vs RAG comparison on the golden set: ⟨Phase 12⟩.

**If they push — level 2.** *"So is fine-tuning useless here?"* No — it's the wrong tool for *facts*, the right one for *behaviour*. If Phase 11 shows the model often breaks the citation format, a small fine-tune on correctly formatted answers (with RAG still supplying facts) is a legitimate fix. They're complementary.

**If they push — level 3.** *"Why exactly is fine-tuning bad at facts?"* Training adjusts weights with gradient updates spread across billions of parameters; a fact seen a handful of times shifts them only slightly, so recall is unreliable, and there's no record of *where* the fact came from. There's also research suggesting that fine-tuning on genuinely new knowledge can make a model more prone to hallucinate (Gekhman et al., 2024) — I'd cite that cautiously, as I haven't reproduced it.

**If they push — level 4.** *"Could you make fine-tuning cite sources?"* You could train it to emit document ids, but nothing guarantees the id corresponds to text that supports the claim — the model would be generating plausible ids. Verifiable citations need the source text in the prompt, which is retrieval again. That's the floor of my understanding; I haven't tried it.

**Whiteboard it.**
```text
 fine-tune:  docs ─▶ training ─▶ weights ─▶ answer         (no pointer back)
 RAG:        docs ─▶ index ──search──▶ chunks ─▶ LLM ─▶ answer + [chunk, page]
```

**Trap.** "Fine-tuning is more accurate because the model really learns the data." Learning *style* ≠ storing retrievable facts, and accuracy you can't verify is worth little for financial text.

**Bridge.** "…which is why I measure retrieval separately from generation — want me to show how the golden set records where each answer lives?"

---

### Q: Context windows are a million tokens now. Why not put all the documents in the prompt?
**ID:** P0-02 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Three reasons for this workload: cost, latency, and accuracy. Stuffing pays for the entire corpus in input tokens on *every* question; latency grows with prompt length; and models use information in the middle of long inputs worst. RAG sends a few relevant chunks instead. For two or three short documents queried rarely, I'd agree stuffing is simpler."

**2-minute answer.** Make the cost concrete with arithmetic (illustrative inputs; the real corpus size comes in Phase 1): a 1,000,000-token corpus × 1,000 questions = 1 billion input tokens; five 400-token chunks plus a 300-token question = 2.3 million — about 435× fewer. Stuffing cost scales with corpus size, RAG cost scales with k. On accuracy, cite "lost in the middle" (Liu et al., 2023): retrieval accuracy over long contexts was best when the relevant passage sat at the start or end and worst in the middle. And there's a hard wall: once the corpus exceeds the window, stuffing simply stops working.

**If they push — level 2.** *"Prompt caching makes repeated long prompts cheap. Doesn't that kill the cost argument?"* It weakens it — caching discounts re-sent prefixes, so the cost gap narrows. It doesn't fix the latency of attending over a huge context, the lost-in-the-middle accuracy problem, the window limit, or access control: with RAG you only send chunks the user may see. I haven't measured caching costs for this project; I'd need the provider's current prices to put numbers on it.

**If they push — level 3.** *"Where's the crossover?"* When *corpus tokens × queries × price per token* exceeds the cost of building and running retrieval — or when the corpus no longer fits. Phase 1 measures our corpus in tokens, which tells me which side we're on.

**If they push — level 4.** *"Could you combine them?"* Yes: retrieve to pick the 2–3 most relevant *documents*, then put those whole documents in a long context. That handles questions needing broad context within a document while keeping cost bounded. I haven't built it; it's the migration path in card #1.

**Whiteboard it.**
```text
 stuffing:  cost/question ∝ corpus tokens      (1,000,000)
 RAG:       cost/question ∝ k × chunk tokens   (5 × 400 + 300 = 2,300)
```

**Trap.** "Long context makes RAG obsolete." It changes the crossover point; it doesn't remove cost, latency, middle-of-context accuracy, or per-user access control.

**Bridge.** "That's also why chunk size and k are the levers I ablate — they set the token cost per question."

---

### Q: Does RAG stop the model from hallucinating?
**ID:** P0-03 · **Round:** ML screen · viva  **Difficulty:** 3/5

**30-second answer.** "No — it reduces hallucination, it doesn't eliminate it. With evidence in the prompt the model has something true to copy from, but it can still ignore the evidence, misread a table, or blend in a remembered figure; and if retrieval hands it the wrong passage, you get a confident wrong answer *with a citation*. So I measure faithfulness separately from retrieval."

**2-minute answer.** Explain *why* models hallucinate: training rewards plausible continuations, so when the fact is missing, the most plausible continuation of "revenue was" is still a number. RAG changes what's plausible by putting the true number in context. Then name the two residual failure modes: (1) **retrieval failure** — the right chunk isn't in the top-k, or a near-duplicate from the wrong year is; (2) **generation failure** — the right chunk is there but the answer doesn't follow from it. Each has its own metric: recall@k and MRR for the first, faithfulness for the second (Phase 11). And the system can **abstain** when evidence is weak, which removes a whole class of hallucinations on unanswerable questions.

**If they push — level 2.** *"How do you detect a generation failure automatically?"* An LLM judge checks whether each claim in the answer is supported by the cited chunks (faithfulness). It's itself imperfect, so I validate the judge against hand labels on a sample (Phase 11).

**If they push — level 3.** *"What about the wrong-year problem specifically?"* 10-K boilerplate repeats almost word for word each year, so two chunks can be near-identical except for the year. Mitigations: store the fiscal year as metadata and filter on it when the question names a year; dedupe or down-weight boilerplate; show the document and year in every citation so a human can spot it.

**If they push — level 4.** *"Can you guarantee no hallucination?"* No, and I wouldn't claim to. You can bound it — require every sentence to carry a citation, verify cited spans contain the quoted figures, and refuse otherwise — but verification of free-form reasoning remains imperfect. That's my honest floor.

**Whiteboard it.**
```text
 retrieval ok?  ──no──▶ wrong/missing evidence   → recall@k, MRR
     │yes
 answer follows from evidence? ──no──▶ unfaithful → faithfulness
     │yes
 correct, cited answer
```

**Trap.** "RAG solves hallucination." Interviewers set this to see whether you know the residual failure modes.

**Bridge.** "That two-stage failure tree is exactly how the eval harness is organised — retrieval metrics first, then faithfulness."

---

### Q: One of your documents costs 64% more tokens than expected for the same amount of text. How can that happen?
**ID:** P1-03 · **Round:** ML screen · viva  **Difficulty:** 3/5

**30-second answer.** "Tokens aren't characters or words — they're whatever pieces the tokenizer learned. Corning's 2021 PDF separates almost every word with a non-breaking space, U+00A0, instead of a normal space. Visually identical, but the tokenizer encodes it less efficiently: 2.64 characters per token against 4.34 for Corning 2022. So the same kind of text costs 164k tokens instead of the ~100k you'd expect."

**2-minute answer.** Explain BPE-style tokenizers: they merge frequent character sequences into tokens learned from training text, where " the" (space + word) is one very common token. Replace the normal space with U+00A0 and those merges no longer apply. The measured numbers: 65,886 non-breaking spaces; 433,032 characters → 163,836 tokens. Consequences: higher cost and smaller effective context; broken exact-string matching (a quote copied with normal spaces won't `find()` in the text); possibly different embeddings. Fix: Unicode-normalise extracted text (NFKC maps U+00A0 to a space) at parse time, once, before any offsets are computed.

**If they push — level 2.** *"Why normalise before computing offsets?"* Offsets index into one canonical text. If normalisation happened later, it could change lengths (some NFKC mappings expand one character into several) and every stored offset would point at the wrong place.

**If they push — level 3.** *"Did Postgres full-text search care?"* I checked: `to_tsvector('english', E'Table of Contents')` gives the same lexemes as with normal spaces, so keyword search wasn't affected. The LLM tokenizer and exact matching were.

**If they push — level 4.** *"Could normalisation ever be wrong?"* Yes — NFKC also folds things like "ﬁ" ligatures and full-width digits, which is usually what you want for search, but it changes characters, so a citation shown to the user should come from the normalised text consistently. I'd test it on a sample of pages; I haven't seen a harmful case yet.

**Whiteboard it.**
```text
 "Table of Contents"        → 4.34 chars/token (normal spaces)
 "Table\xa0of\xa0Contents"  → 2.64 chars/token (Corning 2021)
 fix at parse time: unicodedata.normalize("NFKC", text)  → then offsets
```

**Trap.** "A token is about four characters." It's a property of the tokenizer *and the text*; this corpus shows a 1.7× swing.

**Bridge.** "That's why chunk sizes are measured in the embedding model's own tokens, not characters."

---

### Q: How does a PDF actually store text? Why is extracting it hard?
**ID:** P2-01 · **Round:** viva · backend screen  **Difficulty:** 2/5

**30-second answer.** "A PDF page is a list of drawing instructions — 'use font F1 at 8 points, move to (24, 65), draw these glyphs'. There are no paragraphs, no reading order, often no space characters: a space is just a gap between two positioned strings. Extraction rebuilds words, lines and paragraphs from coordinates, and every heuristic in that rebuild — what's a paragraph, what order to read in, what's a header — can be wrong."

**2-minute answer.** Walk the hierarchy PyMuPDF reconstructs (span → line → block) and the concrete failures in this corpus: Corning 2021 put a whole section in one block separated by lines containing only a non-breaking space; Verizon's footer alternates between "5 Verizon…" and "…10-K 6"; AMD's headings are bold at body size, so font size can't identify them; table column headers sit outside the ruled table. Each became a tested rule.

**If they push — level 2.** *"Where does the Unicode come from if the PDF draws glyphs?"* A font can embed a mapping from glyph codes to Unicode (a ToUnicode table). If it's missing or wrong, extraction yields garbage characters even though the page looks fine — one reason to inspect extractability per page.

**If they push — level 3.** *"Why is reading order ambiguous?"* Content-stream order is whatever the generating program emitted — headers last, columns interleaved. Tools sort by position instead, which works for one column and breaks for two, hence gutter detection.

**If they push — level 4.** *"What about right-to-left or vertical text?"* My rules assume left-to-right horizontal Latin text. I'd need direction-aware ordering (PyMuPDF reports line direction) and haven't tested any of it.

**Whiteboard it.**
```text
 content stream:  BT /F1 8 Tf 24 65 Td (ITEM 8.) Tj ... ET
 extraction:      glyphs → spans → lines → blocks → (our rules) → paragraphs, order, headings
```

**Trap.** "PDF text is just there — call get_text()." It's reconstructed, and the reconstruction is where the bugs live.

**Bridge.** "Which is why the parser's output is checked by an offset invariant on every block."
