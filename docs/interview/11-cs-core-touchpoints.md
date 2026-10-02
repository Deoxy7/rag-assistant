# 11 — CS core touchpoints

**Status:** started in Phase 0 (2026-10-02). Questions are appended each phase. Planned coverage: OS (processes vs threads, the GIL, async I/O, memory in embedding batches, page cache — Phases 4, 10); DBMS (ACID, indexes, query planning, deadlocks — Phases 4–6); networking (HTTP/1.1 vs 2, TCP, SSE over HTTP, timeouts, keep-alive — Phase 10); design patterns actually used in the repo with real class names (strategy for chunkers, repository for storage, factory for retrievers — Phases 3–7); complexity of each pipeline stage; DSA that naturally follows (top-k heaps, merging ranked lists, dedup, LRU cache).

---

### Q: What's the difference between a container and a VM? Why does Docker on a Mac need a VM?
**ID:** P0-13 · **Round:** viva · backend screen  **Difficulty:** 2/5

**30-second answer.** "A VM emulates a whole computer and runs its own operating-system kernel. A container is just ordinary processes on the host's kernel, isolated so they see their own files, network and process list, and limited in the CPU and memory they can use. Linux containers need a Linux kernel; macOS's kernel isn't Linux, so on a Mac a small Linux VM — Colima in my case — runs underneath, and the containers run inside it."

**2-minute answer.** Name the two Linux mechanisms: **namespaces** (what a process can *see*: its own mount table, network stack, process ids) and **cgroups** (what it can *use*: CPU, memory limits). That's why containers start in about a second — no OS to boot — and why they're lighter than VMs. Then the layering on this machine: macOS → Apple Virtualization framework → Colima's Linux VM (2 CPU, 2 GB) → Docker engine → the Postgres container. Measured: the VM's first start took 13 min 17 s (downloading its image), later starts 44 s; the container itself becomes healthy in about 6 s.

**If they push — level 2.** *"What's the security difference?"* A VM has a hard boundary — a separate kernel — so escaping it means breaking the hypervisor. Containers share the host kernel, so a kernel vulnerability can break isolation. That's why multi-tenant clouds often run containers *inside* VMs.

**If they push — level 3.** *"What is an image, really?"* A stack of read-only filesystem layers plus metadata (entry command, environment). Containers add a thin writable layer on top; deleting the container deletes that layer, which is why database files go in a volume.

**If they push — level 4.** *"How does the port forward from your Mac reach Postgres?"* The container's port 5432 is published by Docker inside the VM, and Colima forwards the VM's port to `127.0.0.1:5432` on the Mac. From Postgres's point of view, our connection arrives from the Docker bridge gateway (172.18.0.1). I know the observable behaviour; I haven't studied Colima's forwarding implementation.

**Whiteboard it.**
```text
 VM:         [ app | OS kernel ] on hypervisor          ← own kernel
 container:  [ app ] [ app ] on ONE shared Linux kernel ← namespaces + cgroups
 my Mac:     macOS → Colima Linux VM → Docker → Postgres container
```

**Trap.** "Containers are lightweight VMs." They aren't VMs at all — no separate kernel — and saying so suggests you've never had to explain why Docker on a Mac needs one.

**Bridge.** "Running the database in a container but the app on the host was a deliberate split — fast edit loop for the app, reproducibility for the database."

---

### Q: How do you make a Python project reproducible across machines?
**ID:** P0-14 · **Round:** backend screen · viva  **Difficulty:** 2/5

**30-second answer.** "Pin every layer. The database image by tag *and* digest; every Python package with `==`, including transitive dependencies; the Python version itself, named explicitly in the Makefile because this machine's default `python3` is 3.14; and setup reduced to one command. Then tests that check the environment — like the pgvector version — so drift fails loudly by name."

**2-minute answer.** Explain each piece and what breaks without it. Tag alone: the publisher can re-push it, so two pulls a month apart may differ; the digest is a content hash. Direct-only pins: transitive dependencies (pydantic under pydantic-settings) change underneath you. Unnamed Python: `python3 -m venv` silently builds a 3.14 venv. Then the Makefile's stamp file: requirements reinstall automatically when `requirements.txt` changes, because the stamp is older. And why it matters for *this* project specifically: the deliverable is numbers, and an environment change between two runs would be indistinguishable from a code change.

**If they push — level 2.** *"Why not a lock file tool like Poetry or uv?"* They generate the same thing — exact versions for everything, plus hashes — with better ergonomics. The plan pinned plain `requirements.txt`; a lock tool would add hash checking, which protects against a tampered package with the same version number. I'd adopt one in a team.

**If they push — level 3.** *"What does hash pinning add over version pinning?"* A version number is a name; a hash is the content. If a package index were compromised and a different file served under the same version, a hash check would refuse to install it.

**If they push — level 4.** *"Is anything still not reproducible?"* Yes: the host OS and CPU architecture (arm64 here — some wheels differ by platform), the Colima VM image, and anything downloaded at runtime later, such as model weights from a hub — those need pinning by revision in Phase 4. Model inference can also differ slightly between CPU and Apple's GPU, which I plan to measure.

**Whiteboard it.**
```text
 image:     tag + @sha256 digest         python: python3.11 (not python3)
 packages:  == for direct + transitive   setup:  make test (one command)
 verify:    tests assert pgvector == 0.8.7, password enforced
```

**Trap.** "Docker makes everything reproducible." Our app doesn't even run in Docker; reproducibility comes from pinning every layer, Docker being one of them.

**Bridge.** "The same idea is why the eval runner will write timestamped, never-overwritten results — reproducible numbers, not just reproducible installs."

---

### Q: How would you detect scanned pages in a PDF programmatically? What's the cost?
**ID:** P1-08 · **Round:** viva · backend screen  **Difficulty:** 2/5

**30-second answer.** "A scanned page is a picture of text: the PDF has an image and little or no extractable text. So for each page I count extractable characters and measure what fraction of the page images cover; a page is scanned-suspect only if it has fewer than 200 characters *and* images cover at least half of it. Both conditions are needed — low text alone also matches blank separator pages. On this corpus: 0 of 2,224 pages."

**2-minute answer.** Mechanism: PyMuPDF's `page.get_text()` returns text drawn with real font instructions; `page.get_image_info()` returns each image's bounding box. Coverage = sum of image areas ÷ page area (capped at 1). Cost: one pass over every page, linear in pages and in the text on each — the whole 2,224-page corpus took about 1–3 seconds per document for the PyMuPDF part (pdfplumber table detection dominated the 3-minute run). Validation: a synthetic test page that is only an image must be flagged, and a normal text page must not.

**If they push — level 2.** *"What would you do with scanned pages if there were some?"* OCR (optical character recognition), e.g. Tesseract, with its confidence scores stored so low-confidence text can be down-weighted; and offsets would then refer to OCR text. Card #4 discusses it.

**If they push — level 3.** *"What about a page with an image of a table plus a caption?"* Text count might exceed 200 while the table content is invisible to extraction. My heuristic would miss it; a stricter check would compare text area with image area. Zero such pages showed up, but I didn't verify that by eye on all 2,224.

**If they push — level 4.** *"Overlapping images could push coverage above 100%."* Yes — I sum areas and cap at 1.0, so overlaps can overstate coverage; computing the union area would be exact. For a binary ≥50% decision the cap was enough here.

**Whiteboard it.**
```text
 per page:  chars = len(text)          coverage = Σ image areas / page area
 scanned?   chars < 200  AND  coverage ≥ 0.5
 cost:      O(pages)   result: 0 / 2,224
```

**Trap.** "Check whether the page has an image." Most 10-K pages with images are logos on text pages.

**Bridge.** "Zero scanned pages is why the parser choice in Phase 2 doesn't need OCR."

---

### Q: Given a character offset into a document, how do you find its page? What's the complexity?
**ID:** P2-02 · **Round:** DSA · viva  **Difficulty:** 2/5

**30-second answer.** "Each page stores the offset where its text starts, in increasing order. Finding the page for an offset is 'the last page whose start is ≤ the offset' — a binary search, O(log P) for P pages, instead of a linear scan. `ParsedDocument.page_of` does exactly that, and a test checks it agrees with every block's stored page."

**2-minute answer.** Explain the loop: `lo, hi = 0, P-1`; `mid = (lo + hi + 1) // 2` (round *up*, otherwise `lo = mid` can loop forever when `hi = lo + 1`); if `start[mid] <= x`, `lo = mid`, else `hi = mid - 1`. Edge case: empty pages have `char_start == char_end` equal to the next page's start, and "last page with start ≤ x" correctly skips to the non-empty one. Python's `bisect.bisect_right(starts, x) - 1` is the library version.

**If they push — level 2.** *"Why half-open ranges?"* `[start, end)` makes length `end - start`, adjacent ranges touch without overlapping, and an empty range is `start == end`. Closed ranges need ±1 everywhere.

**If they push — level 3.** *"How would you find all chunks overlapping an evidence span?"* Chunks sorted by start: binary-search the first chunk with `end > span_start`, then walk while `start < span_end`. O(log n + matches). Overlap condition for half-open ranges: `a.start < b.end and b.start < a.end`.

**If they push — level 4.** *"And in SQL?"* Postgres range types (`int4range`) with a GiST index support `&&` (overlaps) efficiently; with plain integer columns a B-tree on `(doc_id, char_start)` plus the overlap predicate works at our scale.

**Whiteboard it.**
```text
 page starts: [0, 2810, 5622, 5622, 9101]   x = 5700
 last start ≤ 5700 → index 3 (page 4)   O(log P)
 overlap([a,b), [c,d))  ⇔  a < d and c < b
```

**Trap.** Rounding `mid` down in the "last ≤" variant — infinite loop on two elements.

**Bridge.** "The overlap test is the core of how the eval decides whether a retrieved chunk is relevant."

---

### Q: What is Unicode normalisation, and why do you normalise before computing offsets?
**ID:** P2-03 · **Round:** viva · backend screen  **Difficulty:** 3/5

**30-second answer.** "The same visible text can be encoded differently — a non-breaking space versus a space, the 'ﬁ' ligature versus 'f' + 'i'. NFKC normalisation rewrites those compatibility characters into plain forms. It can change string length, so if offsets were computed first and text normalised later, every offset after the first change would point at the wrong characters. So each block is normalised first; offsets index the normalised text."

**2-minute answer.** Distinguish the forms: NFC/NFD compose/decompose accents (é as one code point or e + combining accent); NFKC/NFKD additionally fold *compatibility* variants (full-width digits, ligatures, non-breaking space). For search, NFKC is right: users type plain characters. Corpus evidence: Corning 2021's 65,886 non-breaking spaces gone after normalisation, verified by a test that asserts no `\xa0` in any parsed document.

**If they push — level 2.** *"Any downside to NFKC?"* It's lossy: superscripts become plain digits ("10²" → "102"), which could change a figure's meaning. I haven't seen it in this corpus; it's on the honest-answers list.

**If they push — level 3.** *"Does Postgres normalise for full-text search?"* I tested that its English parser already treats U+00A0 as a separator, so FTS wasn't affected — exact matching and LLM token counts were.

**If they push — level 4.** *"How would you keep offsets into the original PDF text too?"* Store a mapping from normalised positions to raw positions while normalising (an array of raw offsets per output character). I chose block bounding boxes instead, which is enough for highlighting.

**Whiteboard it.**
```text
 raw:   "Table\xa0of\xa0Contents  ﬁnance"
 NFKC + collapse → "Table of Contents finance"
 order: normalise → assemble → offsets   (never the reverse)
```

**Trap.** "Normalisation is cosmetic." It changes lengths, which changes every offset.

**Bridge.** "That ordering rule is the reason the parser version is part of the cache key."

---

### Q: Which design patterns does your chunking code use, and why?
**ID:** P3-06 · **Round:** viva · backend screen (OOP)  **Difficulty:** 2/5

**30-second answer.** "Strategy and Factory. `Chunker` is a Protocol — anything with `name`, `size`, `overlap` and `chunk(doc)` qualifies — and `FixedSizeChunker`, `RecursiveChunker` and `StructureChunker` are interchangeable strategies. `get_chunker(strategy, size, overlap)` is the factory: the only place a config string becomes an object, and where invalid sizes are rejected."

**2-minute answer.** Why Protocol over an abstract base class: structural typing — implementations don't inherit anything, which keeps them simple and lets a test double satisfy the interface. Why it pays off: ingestion and the Phase 12 ablation loop over configurations without a single `if strategy == …`. Add the immutability point: `Chunk` is a frozen dataclass so offsets and text can't drift apart after creation.

**If they push — level 2.** *"How would you add semantic chunking?"* One new class with a `chunk` method and one dictionary entry in `CHUNKERS`; no caller changes (open/closed principle).

**If they push — level 3.** *"Protocol vs ABC — runtime behaviour?"* A Protocol is checked by type checkers, not at runtime, unless marked `@runtime_checkable`. An ABC refuses instantiation of incomplete subclasses at runtime. For a small internal interface, static checking was enough.

**If they push — level 4.** *"Where else will you use these?"* Retrievers (vector, keyword, hybrid) behind one interface with a factory driven by `retrieval_mode` (Phase 7), and LLM clients behind a `generate` interface (Phase 9).

**Whiteboard it.**
```text
 config(strategy,size,overlap) ─▶ get_chunker() ─▶ Chunker
                                     ├ FixedSizeChunker
                                     ├ RecursiveChunker
                                     └ StructureChunker      .chunk(doc) → [Chunk]
```

**Trap.** Calling any class a "pattern". Name what varies (the algorithm) and what's fixed (the interface).

**Bridge.** "That interface is what makes the ablation a loop instead of a rewrite."

---

### Q: Why is embedding 2.5× faster on the GPU, and is the output the same?
**ID:** P4-07 · **Round:** viva · ML screen  **Difficulty:** 2/5

**30-second answer.** "A transformer forward pass is mostly large matrix multiplications. Batching 64 chunks turns them into big matrices that the M1's GPU parallelises far better than four CPU cores: 116 chunks/s on MPS vs 46 on CPU, measured on 506 real chunks. The outputs differ by at most 3.3 × 10⁻⁷ — floating-point rounding — with cosine ≥ 0.99999988, so rankings are unaffected."

**2-minute answer.** Explain why results differ at all: different hardware executes floating-point additions in different orders, and float addition isn't associative, so tiny rounding differences appear. Batch size has the same effect (1.5 × 10⁻⁷). These are eight orders of magnitude below differences that change rankings. Then batching's limits: larger batches help until memory or padding waste dominates (batch 16 → 64 raised MPS throughput 94.5 → 116.4).

**If they push — level 2.** *"What's padding waste?"* A batch is padded to its longest text; mixing a 20-token and a 256-token chunk wastes compute on the short one. Sorting by length before batching reduces it — sentence-transformers does that internally.

**If they push — level 3.** *"Would threads help on CPU?"* PyTorch already uses multiple threads for matrix ops (4 here). Python-level threads wouldn't help because of the GIL, but the heavy work runs in C++ outside it.

**If they push — level 4.** *"Determinism guarantees?"* For bit-identical outputs you'd fix the device, batch composition and library versions. I pin versions and model revision; I accept 10⁻⁷ noise across devices.

**Whiteboard it.**
```text
 batch 64 × 256 tokens → big matmuls → GPU parallel
 CPU 45.7/s   MPS 116.4/s   max |Δ| 3.3e-7   (float add not associative)
```

**Trap.** "GPU results are approximate, so I avoid them." The difference is rounding noise; measure it.

**Bridge.** "That noise level is also why my eval reruns are stable."

---

### Q: Explain HNSW search as an algorithm. What's its complexity?
**ID:** P5-08 · **Round:** DSA · ML screen  **Difficulty:** 4/5

**30-second answer.** "HNSW is a layered proximity graph. Search starts at an entry node on the top layer and greedily moves to whichever neighbour is closer to the query until none is; then it drops a layer and repeats. On the bottom layer it keeps a priority queue of the best `ef_search` candidates, expanding their neighbours until the queue stops improving, and returns the top k. Expected cost is roughly logarithmic in the number of vectors times ef_search, each step costing a d-dimensional distance."

**2-minute answer.** Detail the data structures: a min-heap of candidates to expand and a max-heap (bounded at ef_search) of the best found; a visited set. Upper layers have exponentially fewer nodes (each node's top level drawn from a geometric distribution), giving the "express lanes". Approximate because greedy search can get stuck in a local region; larger ef_search widens the beam.

**If they push — level 2.** *"Insertion?"* Search for the new node's neighbours at each of its layers (beam ef_construction), connect to the best m, prune neighbours' lists to keep them at most m (2m on layer 0).

**If they push — level 3.** *"Memory?"* Vectors plus up to m links per layer per node — measured ~1.9 KB per 384-d vector here.

**If they push — level 4.** *"Deletions?"* Postgres marks rows dead; vacuum removes index entries. How pgvector repairs neighbours around removed nodes I'd need to read in its source — honest gap.

**Whiteboard it.**
```text
 L2: A ─greedy─▶ B
 L1:        B ─greedy─▶ D
 L0:                    D → beam(ef_search) with min/max heaps → top-k
 cost ≈ O(log N · ef_search · d)
```

**Trap.** Calling it a tree, or exact.

**Bridge.** "The beam width is ef_search — the knob I measured."

---

### Q: How does an inverted index answer an AND query and an OR query? Complexity?
**ID:** P6-08 · **Round:** DSA · backend screen  **Difficulty:** 3/5

**30-second answer.** "Each term maps to a sorted posting list of document ids. AND is the intersection of the lists — walk them in parallel like merging, O(sum of lengths), or skip ahead with galloping search when one list is short. OR is the union — a k-way merge, again linear in the total length. Ranking then scores only documents in the result; top-k uses a heap of size k: O(n log k)."

**2-minute answer.** Relate to Postgres: GIN stores posting lists (or posting trees for long lists) per lexeme; a bitmap index scan builds a bitmap of matching rows and the heap scan visits only those pages — 208 matches for 'goodwil & impair' in 0.066 ms. OR on a common term produces large bitmaps, which is why broad OR queries cost more to rank.

**If they push — level 2.** *"Why sorted posting lists?"* Sorted lists make intersection/union linear merges and allow compression with delta encoding.

**If they push — level 3.** *"How do engines avoid scoring every match?"* WAND / block-max WAND: keep per-term upper-bound scores and skip documents that can't beat the current k-th best.

**If they push — level 4.** *"Top-k heap details?"* Min-heap of size k: push each score; if the heap exceeds k, pop the smallest. Final heap holds the k largest. O(n log k) time, O(k) space.

**Whiteboard it.**
```text
 goodwil: [12, 88, 301, 977]      impair: [88, 301, 640]
 AND = merge-intersect → [88, 301]   OR = merge-union → [12, 88, 301, 640, 977]
 top-k: min-heap(k) over scores → O(n log k)
```

**Trap.** Saying "it scans the text for the words".

**Bridge.** "Merging ranked lists is also what RRF does — next phase."

---

## Phase 7 questions

### Q: RRF as an algorithm: data structures, complexity, determinism.
**ID:** P7-08 · **Round:** DSA  **Difficulty:** 2/5

**30-second answer.** "Iterate over every hit in every list and add 1/(k + rank) into a hash map keyed by chunk id. Also keep each chunk's best rank and the Hit object from that list. Then sort the distinct ids by (−score, best rank, id). That's O(N) for N total hits plus O(u log u) for u distinct chunks, so two lists of 50 cost microseconds. The sort key makes it deterministic: no dependence on dictionary order or on which list came first."

**2-minute answer.** Contrast with merging sorted lists. You can't k-way merge, because a chunk's final score depends on all lists, so you accumulate first. If only the top k is needed, a heap of size k gives O(u log k), which doesn't matter at u ≤ 100. Mention the immutability detail: Hit is a frozen dataclass, so the fused hit is a copy via `dataclasses.replace` with the new score and rank.

**If they push — level 2.** *"Floating-point concerns?"* Summing two reciprocals is exact enough for ordering. Exact ties (two lists' #1s both 1/61) are bitwise equal, which is why the tie-break matters.

**If they push — level 3.** *"Could you do it in SQL?"* Yes: UNION ALL the two ranked CTEs with `row_number()`, `GROUP BY chunk_id`, `SUM(1.0/(60 + rank))`, then ORDER BY. One round trip.

**If they push — level 4.** *"Streaming version?"* With lists arriving incrementally, you can bound unseen chunks' maximum possible score (the threshold algorithm, Fagin) and stop early once the top k can't change.

**Whiteboard it.**
```text
 for L in lists: for h in L: score[h.id] += 1/(k + h.rank); best[h.id] = min(best[h.id], h.rank)
 sort ids by (-score, best, id)        O(N + u log u)
```

**Trap.** Proposing a k-way merge of the input lists.

**Bridge.** "The expensive part is never fusion; it's the two searches and, next, the reranker."

---

## Phase 8 questions

### Q: Why is GPU reranking 2× faster than CPU at N = 10 but the gap grows at N = 50? What's batching doing?
**ID:** P8-07 · **Round:** viva · ML screen  **Difficulty:** 3/5

**30-second answer.** "A cross-encoder pass is mostly matrix multiplications over (pairs × tokens × hidden size). The GPU runs them in parallel, but each call has fixed launch and transfer overhead. At 10 pairs the overhead is a big share, so the GPU is only 2× faster (77 vs 153 ms). At 50 pairs there's more parallel work per call, and it's 2.3× (267 vs 622 ms). Batch size 32 means 50 pairs take two batches."

**2-minute answer.** Attention cost per pair is quadratic in sequence length (here ≤ 298 tokens), and the feed-forward layers are linear. Padding to the longest pair in a batch wastes work, so sorting by length helps. Larger batches amortise overhead until memory or latency limits. In a server, dynamic batching across requests does the same.

**If they push — level 2.** *"Why did torch report 4 CPU threads?"* That's PyTorch's default intra-op thread count on this machine. More threads help large matrix multiplications but contend with other processes.

**If they push — level 3.** *"Why does quantisation speed it up?"* int8 matrix multiplications move a quarter of the bytes of float32 and use faster integer units. Memory bandwidth is often the limit.

**If they push — level 4.** *"Complexity of reranking N candidates?"* O(N · L² · d) attention plus O(N · L · d²) feed-forward per layer: linear in N. That's why the measured latency is close to linear in N.

**Whiteboard it.**
```text
 N     10    20    50    100*      (* ≈51 pairs for figure queries)
 MPS   77   136   267   285   ms
 CPU  153   317   622   765   ms
```

**Trap.** "GPUs are always 10× faster": not for tiny batches.

**Bridge.** "Same lesson as the embedder in Phase 4, where MPS was 2.5× faster on large batches."

---

## Phase 9 questions

### Q: What is SSE, and how does the OpenAI SDK stream a response?
**ID:** P9-07 · **Round:** backend screen · viva  **Difficulty:** 2/5

**30-second answer.** "Server-Sent Events: one long HTTP response with content-type text/event-stream. The server writes 'event: name' and 'data: json' lines, each event ending with a blank line. The Responses API sends response.created, output_item.added, content_part.added, then many response.output_text.delta events with text pieces, and finally response.completed with usage. My client yields only the deltas and reads token usage from the final event."

**2-minute answer.** Explain why streaming matters: time to first token is what users perceive. A three-second answer that starts after 300 ms feels fast. Then a detail learned in testing: the SDK's stream accumulator requires the item and part events before any delta. My first mock skipped them and the SDK raised 'content event … before receiving its output item'. A mock has to follow the real event sequence.

**If they push — level 2.** *"SSE vs WebSockets?"* SSE is one-way server-to-client over plain HTTP, with automatic reconnect in browsers. WebSockets are bidirectional, which we don't need. Card #31 covers it in Phase 10.

**If they push — level 3.** *"What does buffering do to SSE?"* A proxy or framework that buffers the response defeats streaming. Disable buffering (e.g. nginx `X-Accel-Buffering: no`) and flush per event.

**If they push — level 4.** *"How does the client know the stream ended?"* The terminal event (response.completed), then the connection closes. Errors come as an error event or an HTTP status before the stream starts.

**Whiteboard it.**
```text
 event: response.output_text.delta
 data: {"type":"response.output_text.delta","delta":"Revenue was ",...}
 (blank line)
 … → event: response.completed  data: {..., "usage": {"input_tokens": 812, ...}}
```

**Trap.** Thinking SSE needs WebSockets, or a special protocol.

**Bridge.** "Phase 10 re-streams these deltas to the browser as our own SSE."

---

## Phase 10 questions

### Q: Event loop vs thread pool: why are your endpoints `def` and not `async def`?
**ID:** P10-05 · **Round:** viva · backend screen  **Difficulty:** 3/5

**30-second answer.** "An event loop runs async tasks on one thread and switches tasks only when one awaits. A blocking call (psycopg's sync driver, torch on the GPU, the sync OpenAI SDK) inside `async def` never awaits, so it holds the loop and every other request waits, health checks included. FastAPI runs plain `def` endpoints and sync generators in a thread pool instead, so blocking work happens in worker threads and the loop stays free."

**2-minute answer.** Then the cost of threads: each in-flight request holds one (AnyIO's default limit is 40), and the GIL is released during I/O and inside torch and numpy kernels, so threads do overlap. The models aren't thread-safe on MPS, hence a lock per model. Async end to end would scale idle streaming connections better, but only if every call in the chain is async.

**If they push — level 2.** *"Does the GIL make threads useless?"* No. It's released during socket I/O and inside C extensions like torch and numpy, which is where this code spends its time.

**If they push — level 3.** *"Where's the SSE generator running?"* Starlette iterates a sync iterator via `iterate_in_threadpool`, one `next()` per thread-pool call.

**If they push — level 4.** *"How would you prove the loop isn't blocked?"* Hit /health in a loop during a long /query and check its latency stays low, or use asyncio debug mode, which warns about slow callbacks.

**Whiteboard it.**
```text
 async def + blocking call:  loop ■■■■■■■■ (everyone waits)
 def (thread pool):          loop ─┬─ thread1 ■■■■
                                   └─ thread2 ■■■■   loop free for /health
```

**Trap.** "async is always faster."

**Bridge.** "That's why model inference is the thing to split out at scale."

---

## Phase 11 questions

### Q: What's a bootstrap confidence interval, and why do you report one?
**ID:** P11-06 · **Round:** viva · ML screen  **Difficulty:** 3/5

**30-second answer.** "Resample the 52 answerable questions with replacement, 2,000 times, compute the mean each time, and take the 2.5th and 97.5th percentiles. It estimates how much the score would move with a different sample of similar questions. hit@5 0.769 has a 95% interval of 0.65–0.88, so a configuration needs to move by roughly ten points before this set can distinguish it from noise."

**2-minute answer.** Contrast with a paired comparison: two configs answer the same questions, so the right test looks at the questions where they disagree. The sign test counts wins and losses; with 6 discordant questions split 4–2, p ≈ 0.69. The bootstrap is about one system's uncertainty; the paired test is about the difference between two.

**If they push — level 2.** *"Why not a normal approximation?"* Per-question scores are 0/1 or bounded, and n is small. The bootstrap needs no distributional assumption.

**If they push — level 3.** *"Seeded?"* Yes (seed 7), so the interval is reproducible run to run.

**If they push — level 4.** *"Limits?"* It can't fix a biased sample: it measures sampling noise, not author bias. That's why the external set exists.

**Whiteboard it.**
```text
 for b in 1..2000: sample 52 q with replacement → mean_b
 CI = [percentile 2.5, percentile 97.5] of mean_b     hit@5: .769 [.65, .88]
```

**Trap.** Treating overlapping intervals as proof of "no difference": use a paired test.

**Bridge.** "Phase 12 uses paired tests for every ablation comparison."

---

## Phase 12 questions

### Q: What's the winner's curse, and where did you see it?
**ID:** P12-07 · **Round:** viva · ML screen  **Difficulty:** 2/5

**30-second answer.** "When you pick the best of many noisy measurements, its score is on average an overestimate, because part of why it came first is luck. With 57 configurations on 52 questions, the top score is likely inflated. My default is the top cell of structure-aware chunking, which is the *weakest* strategy on average (0.542 vs 0.607 for fixed), and it's the configuration I debugged and audited labels on. So I expect its 0.769 to drop on fresh questions."

**2-minute answer.** Connect it to regression to the mean and to multiple comparisons. The remedy is re-measurement on new data: a held-out split, or new questions. Report the selection process, not just the winner.

**If they push — level 2.** *"How big is the inflation?"* Unknown here. A simulation would bootstrap the selection process: resample the questions, pick the best each time, and compare its score to its out-of-sample score.

**If they push — level 3.** *"Is the reranker effect also inflated?"* Much less: it's an average over 27 pairs, not a maximum, and consistent (23 better).

**If they push — level 4.** *"Bonferroni?"* 0.05 / 57 ≈ 0.0009. The 20 configurations worse at p ≤ 0.01 are not all below that, but the pattern (vector-only and 128-token structure) is consistent.

**Whiteboard it.**
```text
 pick max of 57 noisy scores → E[max] > true value of that config
 our max: structure256-hybrid-rr .769, but structure avg .542 (weakest)
 remedy: re-test top configs on fresh questions
```

**Trap.** Reporting the best configuration's score as its expected performance.

**Bridge.** "Which is why the next step is a fresh question set, not more tuning."

---

## Phase 13 questions

### Q: Why was embedding a short question slower on the GPU than the CPU in the server?
**ID:** P13-03 · **Round:** viva · ML screen  **Difficulty:** 3/5

**30-second answer.** "Measured: back to back, both take ~17 ms. But after the GPU sits idle 2–10 seconds, which happens between requests while the LLM answers, one embedding takes 84–226 ms on MPS and 21–38 ms on the CPU. The first MPS call from a new worker thread took 392 ms. I tested and ruled out a recompile per input length. The likely cause is the GPU lowering its clocks when idle, though I'm not certain of the mechanism. For batch ingest the GPU is still 2.5× faster."

**2-minute answer.** The general lesson: accelerators have warm-up and power-state costs that dominate tiny, infrequent workloads, while throughput benchmarks hide them. The design response is to split devices by workload (CPU for single queries, GPU for batches) or keep the GPU warm. Either needs an ablation that confirms the eval numbers don't move.

**If they push — level 2.** *"Why not just switch?"* CPU and MPS vectors differ by up to 3.3e-7, which could reorder near-ties. It's cheap to check, but it's a measured change, not a silent one.

**If they push — level 3.** *"Keep-warm?"* A background no-op embed every second costs power and complicates the process. Measure whether it beats the CPU path.

**If they push — level 4.** *"At high traffic?"* The GPU stays busy, so the effect disappears and batching wins. The right device depends on the request rate.

**Whiteboard it.**
```text
            warm    idle 2 s    idle 5–10 s   new thread
 MPS        17 ms   93 ms       84–226 ms     392 ms (once)
 CPU        15 ms   34 ms       21–38 ms
 ingest batch: MPS 116 vs CPU 46 chunks/s
```

**Trap.** "GPU is always faster."

**Bridge.** "Measuring each stage is what surfaced it at all."

---

## Phase 15 questions

---

### Q: What does 'time to first token' in your UI actually measure?
**ID:** P15-08 · **Round:** ML screen · backend  **Difficulty:** 2/5

**30-second answer.** "The client clock in ui/client.py: from sending POST /query/stream on the Streamlit server to the first delta event. It includes retrieval, the LLM's time to first token, the refusal gate holding back the first characters, and the stream filter holding text to a word boundary. It excludes the browser's render. Live, on gpt-oss-20b: 940 ms; sources arrived at 514 ms."

**2-minute answer.** Contrast with the server-side stages from doc 17 (first_token 402 ms on qwen, unthrottled). Two clocks answer two questions: where time goes (server stages) and what users feel (client clock). For a refusal, the UI shows no first token, because the gate never releases a refusal's characters.

**If they push — level 2.** *"Why is the first question slower?"* 2,178 ms vs 940: idle-GPU query embedding plus the cold first request (doc 17).

**If they push — level 3.** *"How would you measure the browser part?"* The Performance API in the browser, or a Playwright test timing DOM changes.

**If they push — level 4.** *"p95?"* Three samples aren't a distribution; /stats gives server-side p95 from request_log.

**Whiteboard it.**
```text
 t0=send → sources 514 ms → first delta 940 ms → answer 1,019 ms  (client clock)
 server: retrieve ~320 · first_token 402 · generate 862 (doc 17, qwen)
```

**Trap.** Quoting a server metric as user-perceived latency.

**Bridge.** "Same split as list vs billed cost: say which number you mean."
