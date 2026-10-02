# 06 — System design

**Status:** started in Phase 0 (2026-10-02). Questions are appended each phase. Planned coverage: 100 docs → 10M documents (what breaks first, in order); 1 → 1,000 QPS bottleneck analysis stage by stage; hitting a 400 ms retrieval budget; freshness, deletions and document versions; multi-tenancy and per-document ACLs; caching layers and invalidation; horizontal scaling, replicas, sharding the vector index; cost per 1,000 queries and its three biggest levers; production monitoring and alerts; a "design a RAG system for X" template. The scale answers need Phase 8 and Phase 13 latency numbers and are written then.

---

### Q: Before you design anything — what do you need to know about the workload?
**ID:** P0-07 · **Round:** system design · project deep-dive (senior)  **Difficulty:** 4/5

**30-second answer.** "Seven things: corpus size; how often documents change; query volume now and at peak; whether different users may see different documents; whether citations are required and how precise; what to do when evidence is inadequate; and whether first-token or complete-answer latency matters. For this project: about ten filings, rarely changing, one user, no per-user permissions, character-level citations, refuse when unsure, and first-token latency for the UI."

**2-minute answer.** Go row by row and attach a consequence to each: small static corpus → batch ingestion, one Postgres node, maybe exact search is fast enough; one user → no load balancer or caching layer yet; no ACLs → no per-user filter at retrieval time; character citations → offsets must be captured at parse time; refuse when unsure → needs an abstention rule and unanswerable golden questions; first-token latency → streaming over SSE. The point: every later design choice traces back to a row. (Table in [02 §6](../02-architecture-overview.md#the-workload-contract).)

**If they push — level 2.** *"Which row would change your design most if it changed?"* Permissions. Per-user access over a shared corpus means every retrieval must filter by what the user may see — and filtering inside approximate vector search is exactly where recall cliffs happen (card #18). It also rules out long-context stuffing of shared documents.

**If they push — level 3.** *"And if documents changed every minute?"* Batch re-ingestion becomes continuous: a queue of document events, idempotent upserts by document version, deletes that remove old chunks, and HNSW insert cost becomes a write-path concern. Freshness becomes a metric (time from publish to searchable).

**If they push — level 4.** *"How would you measure whether you met the contract?"* Each row becomes a metric or test: corpus size and ingest time logged; query p50/p95 and time-to-first-token per stage (Phase 13); refusal rate on unanswerable golden questions (Phase 11); citation accuracy — does the cited span contain the quoted figure (Phase 9). Some rows (peak QPS) I can't validate without real traffic, and I'd say so.

**Whiteboard it.**
```text
 size │ change rate │ QPS │ ACLs │ citations │ if unsure │ latency goal
 ~10  │ rare        │ 1   │ none │ char span │ refuse    │ first token
```

**Trap.** Jumping straight to boxes and arrows. Designing before asking the workload questions signals you design for an imaginary system.

**Bridge.** "Given that contract, the simplest shape is one service and one database — want me to draw it?"

---

### Q: Why a monolith? Wouldn't microservices scale better?
**ID:** P0-08 · **Round:** system design · backend screen  **Difficulty:** 3/5

**30-second answer.** "Scaling comes from statelessness and running more copies — a stateless monolith can run ten copies behind a load balancer too. What microservices buy is scaling *different stages differently* and letting different teams deploy independently. With one developer and one query per second, that buys nothing and costs network hops, partial failures and distributed tracing. So it's a modular monolith, with layer boundaries enforced by a test."

**2-minute answer.** Describe the enforcement: `tests/test_architecture.py` parses every import and fails the build if a lower layer imports a higher one (shown failing on a planted `store → api` import). Then the split criterion: split a component when it has a different scaling profile, hardware need, deploy cadence or owning team. Prediction: model inference (embedding the query, reranking) splits out first, because it's CPU/GPU-bound while the API is I/O-bound. (Card x-modular-monolith in [09](09-tradeoff-cards.md).)

**If they push — level 2.** *"What's the cost of a network hop between stages?"* A round trip inside one data centre is typically small next to model inference, but it adds serialisation, a new failure mode (the callee is down or slow), and a timeout and retry policy per call. I haven't measured it here because there are no hops.

**If they push — level 3.** *"How would you split the reranker out without touching callers?"* It already sits behind one function interface; I'd replace the in-process implementation with a client that calls a reranker service with the same signature, add a timeout and a fallback (skip reranking and return the fused order), and the layering test keeps callers unchanged.

**If they push — level 4.** *"What about the database as a bottleneck?"* Postgres is a single primary for writes; reads (searches) can go to replicas. Ingestion is the only writer and is rare. The first DB bottleneck under concurrent load is probably connections — one backend process each — which a pool (Phase 10) or PgBouncer addresses. I'll know after Phase 13 measures it.

**Whiteboard it.**
```text
 [ API │ retrieve │ rerank │ generate ]  ×N replicas  ──▶ Postgres primary (+ read replicas)
          split first ─▶ [ rerank service (GPU) ]
```

**Trap.** "Microservices because big companies use them." The interviewer wants the cost side of the ledger.

**Bridge.** "The measurement that will tell me when to split is the per-stage latency waterfall in Phase 13."

---

### Q: How would you run this in production? Is Docker Compose production-ready?
**ID:** P0-09 · **Round:** backend screen · system design  **Difficulty:** 3/5

**30-second answer.** "Compose on a laptop gives reproducibility, not reliability — no backups, no failover, no monitoring, and the data lives in a VM disk. In production I'd use managed Postgres with pgvector, run the app as a container on a platform like ECS or Cloud Run, keep secrets in a secrets manager instead of `.env`, and run schema migrations in CI before each deploy."

**2-minute answer.** Contrast what Compose gives today (exact image pinned by digest, one-command setup, disposable database, healthcheck-gated startup — card #39) with what production adds: automated backups and point-in-time recovery, a standby for failover, monitoring and alerts, TLS between app and database, least-privilege database roles, and checking that the managed provider ships a pgvector version with the features we use (iterative index scans need 0.8+). Here the data is re-derivable from the PDFs with `make ingest`, which is why no backups is acceptable *for development only*.

**If they push — level 2.** *"How do you roll out a schema change safely?"* Migrations applied in CI before the new app version deploys, written to be backward compatible (add a column, backfill, then switch reads, then drop the old one), so old and new app versions can run against the same schema during the rollout.

**If they push — level 3.** *"What would you monitor?"* Query p50/p95 per stage, error rate, refusal rate, LLM token spend per hour, database connections in use, index size and vacuum activity, and ingestion lag. Alerts on p95 latency, error rate and spend anomalies. (Phase 13 builds the metrics.)

**If they push — level 4.** *"What about upgrading the embedding model in production?"* Every vector must be recomputed — old and new vectors aren't comparable. Run both side by side: write new vectors to a new column or table, backfill, evaluate on the golden set, then switch queries over and drop the old ones. Card #14, Phase 4.

**Whiteboard it.**
```text
 dev:   laptop ─ Colima VM ─ Compose ─ Postgres (pinned digest)
 prod:  app containers ×N ─ managed Postgres + pgvector (backups, standby, TLS)
        secrets manager · migrations in CI · metrics + alerts
```

**Trap.** "It's in Docker, so it's production-ready." Containers solve packaging, not durability or availability.

**Bridge.** "Re-embedding during a model upgrade is the operational problem I find most interesting here — it's card #14."

---

### Q: Why didn't you just use LangChain?
**ID:** P0-10 · **Round:** project deep-dive · HR-technical  **Difficulty:** 2/5

**30-second answer.** "I did, for exactly one thing — its recursive text splitter, a solved problem, with tests proving its character offsets are exact. The rest — SQL retrieval, fusion, prompt assembly — is plain Python, because those are the steps the eval harness measures, and a framework would hide exactly the lines I tune and debug."

**2-minute answer.** Use the rule of thumb from card #34: frameworks pay off when integration breadth and speed to a demo matter more than visibility; plain code pays off when the pipeline steps *are* what you measure and defend. Name the concrete concern: as far as I know, LangChain's Postgres vector store keeps metadata in a JSON column in its own table layout, and I wanted typed, constrained `page_number`/`char_start`/`char_end` columns and direct control of HNSW parameters. Concede the counter-case: with ten data sources and tool-using agents, I'd adopt a framework.

**If they push — level 2.** *"How do you swap LLM providers without a framework?"* One interface — `generate(prompt) → token stream` — and one class per provider. That's the Strategy pattern; it's what frameworks do internally.

**If they push — level 3.** *"Isn't that reinventing the wheel?"* For the splitter, yes — so I didn't. For retrieval SQL, the "wheel" is about thirty lines, and owning them is the point: I `EXPLAIN ANALYZE` them in Phase 5.

**If they push — level 4.** *"What do you lose?"* Hosted tracing tools and a big catalogue of integrations. I replace tracing with structured logs carrying per-stage timings (Phase 13), which works but is less polished.

**Whiteboard it.**
```text
 framework:  chain(loader → splitter → store → retriever → llm)   steps hidden
 ours:       parse() → chunk()* → embed() → SQL → rrf() → rerank() → llm()
             *LangChain splitter, offsets tested
```

**Trap.** "LangChain is bad." Dismissing frameworks reads as inexperience; give the cost/benefit for this project.

**Bridge.** "Owning the retrieval SQL is what let me measure exact vs approximate search directly — that's Phase 5."

---

### Q: How do you version and reproduce a dataset you can't commit to git?
**ID:** P1-04 · **Round:** backend screen · system design  **Difficulty:** 3/5

**30-second answer.** "Commit a manifest instead of the data: every file's source URL, size and sha256. A script downloads whatever is missing and verifies every hash on every test run, so a fresh clone either gets byte-identical files or fails loudly. The PDFs themselves stay out of git — they're 21 MB and not mine to redistribute."

**2-minute answer.** Walk the mechanics: `.gitignore` has `data/*` and `!data/manifest.json`; `make corpus` downloads to a `.part` file and renames on completion so an interrupted download can't look complete; `tests/test_corpus.py` re-hashes every file. Changing the corpus is then a reviewed diff to the manifest, and every number in the docs can name the corpus version it came from. It's the dataset equivalent of pinning `requirements.txt`.

**If they push — level 2.** *"What if the upstream URL disappears?"* The hashes still tell you whether a replacement copy is identical. For anything long-lived I'd mirror the files to storage I control (an object-storage bucket) and point the manifest there.

**If they push — level 3.** *"Why not DVC or Git LFS?"* They do this with more features — remote storage, caching, lineage. For twelve files a 60-line script is enough; at hundreds of files or many dataset versions I'd adopt DVC.

**If they push — level 4.** *"How do derived artefacts — parsed text, embeddings — stay in sync?"* Record the source hash in every derived artefact and rebuild when it changes; Phase 4 stores each document's sha256 in the `documents` table so re-ingest can skip unchanged files and detect changed ones.

**Whiteboard it.**
```text
 git:  data/manifest.json  {path, url, bytes, sha256} × 12
 make corpus → download *.part → rename → verify sha256 (every test run)
 derived rows carry source sha256 → rebuild on change
```

**Trap.** "Just commit the PDFs." Licence, repo bloat, and no stronger guarantee than hashes give.

**Bridge.** "Carrying the source hash into the database is also how incremental re-ingestion works."

---

### Q: Parsing takes three minutes. How do you avoid redoing it — and how would you parse a million PDFs?
**ID:** P2-06 · **Round:** system design · backend screen  **Difficulty:** 3/5

**30-second answer.** "Cache each document's parse as JSON keyed by two things: the PDF's sha256 and the parser version. If either changes, it's rebuilt; otherwise it's reused instantly. For a million PDFs, parsing is embarrassingly parallel — each document is independent — so it becomes a queue of document ids consumed by many workers, with results in object storage under the same key."

**2-minute answer.** Explain why both parts of the key matter: the content hash catches a changed file; the parser version catches changed rules (it went 2.0 → 2.3 in this phase, each bump forcing a full re-parse). Numbers: about 0.08 s per page here (2,224 pages in 184 s, single process). A million 200-page PDFs at that rate is ~16.5 million CPU-seconds — about 190 CPU-days — so ~200 cores finish in about a day. Failures: some PDFs will crash the parser or take minutes; give each job a timeout and a dead-letter queue.

**If they push — level 2.** *"How do you roll out a parser change at that scale?"* Version the output path by parser version; parse into the new version in the background; evaluate on a sample (block counts, golden-set retrieval) before switching readers over.

**If they push — level 3.** *"What's the bottleneck?"* CPU in layout analysis (pdfplumber is the slow part), then memory for giant PDFs. Python's GIL means one process per core rather than threads.

**If they push — level 4.** *"Exactly-once processing?"* Not needed: parsing is deterministic and keyed by content hash, so re-processing a document produces the same output — idempotent writes make at-least-once delivery safe.

**Whiteboard it.**
```text
 key = (pdf_sha256, PARSER_VERSION) → data/parsed/KEY.json
 scale: queue(doc ids) → N workers (1 proc/core) → object store[key]
 0.083 s/page × 200 pages × 1M docs ≈ 190 CPU-days
```

**Trap.** Caching by filename. A changed file with the same name silently serves stale text.

**Bridge.** "The same idempotent, content-keyed idea drives incremental re-ingestion in Phase 4."

---

### Q: How does chunk size affect cost and storage at scale?
**ID:** P3-07 · **Round:** system design  **Difficulty:** 3/5

**30-second answer.** "Chunk count drives vector count, embedding time and index size; chunk size drives prompt tokens per question. Halving the size roughly doubles the vectors: structure chunks go 4,183 → 7,411 → 14,513 at 510 / 256 / 128 tokens. But each question's evidence budget shrinks: top-5 is about 1,700 tokens at 510 and 1,000 at 256 by median size."

**2-minute answer.** Translate to storage with arithmetic: 384-dim float32 = 1,536 bytes per vector, so 14,513 vectors ≈ 22 MB raw — trivial here; at 10 M documents of similar shape (~1,450 chunks per doc at 128 tokens) that's 14.5 billion vectors ≈ 22 TB raw, which changes every storage decision. LLM cost scales with k × chunk size × queries. The two levers pull against each other.

**If they push — level 2.** *"Which would you optimise first at scale?"* Usually prompt tokens, because they're paid per query forever, while embedding is paid once per chunk (and again on model upgrades).

**If they push — level 3.** *"What else does overlap cost?"* Fixed windows at 256 carry ~1.43 M tokens vs ~1.28 M of unique text — about 12% more vectors-worth of text to embed and store.

**If they push — level 4.** *"Can you shrink vectors?"* Half-precision or binary quantisation (card #19, Phase 5) trade recall for 2×–32× less memory.

**Whiteboard it.**
```text
 size  chunks  raw vectors   top-5 prompt
 510   4,183    6.4 MB        ~1,700 tok
 256   7,411   11.4 MB        ~1,000 tok
 128  14,513   22.3 MB          ~535 tok
```

**Trap.** Optimising only storage. Prompt tokens are the recurring cost.

**Bridge.** "That's why size is in the ablation with both quality and cost reported."

---

### Q: How would you design ingestion for thousands of new documents a day?
**ID:** P4-05 · **Round:** system design  **Difficulty:** 4/5

**30-second answer.** "Keep the same idempotent unit — one document per transaction, keyed by content hash and parser version — and parallelise around it: a queue of document ids, parse workers on CPU, embedding workers on GPU, and a writer that commits per document. Embedding is the bottleneck: here ~100 chunks per second on a laptop GPU, at ~740 chunks per filing."

**2-minute answer.** Do the arithmetic: 5,000 filings/day × 741 chunks ≈ 3.7 M chunks/day ≈ 43 chunks/s sustained — under one laptop GPU's rate, so a couple of real GPUs give comfortable headroom. Then the HNSW cost: inserting into a big graph is slower than batch-building; for bulk backfills build the index after loading, for steady-state insert continuously. Failure handling: dead-letter queue for PDFs that crash the parser; per-document timeouts.

**If they push — level 2.** *"How do you avoid re-embedding unchanged text?"* Content-hash reuse — already implemented: identical text reuses its vector (599 of 7,411 here).

**If they push — level 3.** *"Ordering between parse and embed?"* Write chunks without vectors first so keyword search sees them immediately; vectors arrive later. Or hold them until embedded if partial visibility is unacceptable.

**If they push — level 4.** *"Backpressure?"* Bound the queues between stages; if embedding falls behind, parsing pauses rather than piling chunks into memory.

**Whiteboard it.**
```text
 queue(doc ids) → parse workers (CPU) → embed workers (GPU, batch 64) → writer (1 txn/doc)
 5,000 docs/day × 741 chunks ≈ 43 chunks/s  vs  ~100/s per laptop GPU
```

**Trap.** Parallelising without idempotency — retries then create duplicates.

**Bridge.** "Idempotency is the same property that makes my eval runs reproducible."

---

### Q: How does vector search scale from 7,000 to 100 million chunks?
**ID:** P5-06 · **Round:** system design  **Difficulty:** 4/5

**30-second answer.** "Exact search is linear — 11.4 ms for 7,411 vectors would be ~150 s for 100 M, so an index is mandatory. HNSW search stays a few milliseconds, but its memory grows linearly: I measured ~1.9 KB per 384-d vector including links, so 100 M is ~190 GB of index, which must fit in RAM to stay fast. Levers in order: halfvec (measured −43% size, same recall), partitioning by tenant or time, read replicas for throughput, then a dedicated vector store."

**2-minute answer.** Add build time and inserts (HNSW builds ~1.4 s per 7k here; at scale builds take hours and need large `maintenance_work_mem`), filtered search (iterative scans become essential once the planner picks the index for selective filters), and QPS: each replica serves searches independently; writes go to the primary.

**If they push — level 2.** *"What's the arithmetic for halfvec?"* 190 GB × ~0.57 ≈ 110 GB — fits a large instance.

**If they push — level 3.** *"How would you shard?"* By a filter that's on every query (tenant, document set) so each query hits one shard; otherwise scatter-gather to all shards and merge top-k (a k-way merge).

**If they push — level 4.** *"When pgvector stops being right?"* When one node's RAM can't hold the hot index even quantised, or you need sharding built in — then a dedicated system with Postgres as source of truth (card #15).

**Whiteboard it.**
```text
 7,411 vec:  exact 11 ms · HNSW 3 ms · index 14 MB
 100 M vec:  exact ~150 s · HNSW ~ms · index ~190 GB (halfvec ~110 GB)
 levers: halfvec → partition → replicas → dedicated store
```

**Trap.** Extrapolating latency only; memory is the first wall.

**Bridge.** "That memory wall is why card #19 measured quantisation even though I don't need it."

---

### Q: Would you move keyword search to Elasticsearch? When?
**ID:** P6-06 · **Round:** system design  **Difficulty:** 3/5

**30-second answer.** "Not at this size: Postgres full-text search returns in ~30 ms, lives in the same database as the vectors and is updated in the same transaction. I'd move when I needed analyzers Postgres lacks (language-specific tokenisers, synonyms at scale, faceting), horizontal scale for keyword traffic, or when my SQL BM25 — which scores every OR-matched candidate — got too slow."

**2-minute answer.** Cost side of Elasticsearch: a second store kept consistent with Postgres (CDC or dual writes, reconciliation), JVM memory, and hybrid fusion across two systems with two network hops. Benefit side: precomputed BM25 impacts and skip algorithms (WAND) make top-k fast at billions of documents.

**If they push — level 2.** *"What breaks first in Postgres FTS at scale?"* Broad OR queries: candidates grow with the corpus, and ranking scans them all. Mitigation: pre-filter by metadata, cap candidates.

**If they push — level 3.** *"How would you keep ES consistent?"* Outbox table in the same Postgres transaction, a worker that ships changes to ES idempotently by chunk id, periodic reconciliation by counts/hashes.

**If they push — level 4.** *"Would you drop keyword search instead?"* Only if the eval showed fusion adds nothing; exact-token questions (figures, codes) are where it's measurably needed.

**Whiteboard it.**
```text
 now:   Postgres: chunks + tsv(GIN) + vectors(HNSW) — one txn, one hop
 later: Postgres ─outbox→ ES (BM25) ; query: vector@PG ∥ keyword@ES → fuse
```

**Trap.** "Postgres FTS doesn't scale" without saying what scales badly.

**Bridge.** "Either way the fusion step is the same — RRF on two ranked lists."

---

## Phase 7 questions

### Q: Design the retrieval layer so vector-only, keyword-only and hybrid are switchable, and make hybrid fast.
**ID:** P7-06 · **Round:** system design  **Difficulty:** 3/5

**30-second answer.** "One interface: `search(conn, query, k, filters) → list[Hit]`, implemented by a vector retriever, a keyword retriever and a hybrid retriever that holds the other two. A factory, `get_retriever(mode, …)`, maps the `retrieval_mode` setting to an object, so the API and the eval harness never branch on mode. Hybrid asks both at depth 50 and fuses with RRF. Measured, hybrid is 48.5 ms p50 against 3.6 ms for vector, mostly keyword search at depth 50."

**2-minute answer.** Cover what carries through: every Hit keeps page, char span and section, so citations don't care about mode. The eval harness gets ablations for free by constructing retrievers with different options. Then the speed levers. Run both searches concurrently on two connections; today they're sequential on one, so latency is the sum. Lower keyword depth. Cap OR terms for long questions: the slowest keyword query was the longest question (58 words, 69 tsquery nodes, 269 ms), against 12 ms for a 10-word question. Or move both into one SQL statement with two CTEs and fuse in SQL, which costs one round trip.

**If they push — level 2.** *"Why fuse in Python rather than SQL?"* Testability and clarity. Fusion is microseconds; the time is in the searches. One-statement fusion is an optimisation I'd take if round trips dominated.

**If they push — level 3.** *"How do you add a third retriever, say SPLADE?"* Implement `search`, add it to the list HybridRetriever fuses, and RRF takes any number of lists. Weighted fusion would need a new weight; RRF doesn't.

**If they push — level 4.** *"What happens under load?"* Keyword search's cost grows with OR-matched candidates, so the tail is driven by long questions. Put a timeout on each half and degrade to the other list if one times out. RRF of one list is that list.

**Whiteboard it.**
```text
 settings.retrieval_mode ─▶ get_retriever() ─▶ VectorRetriever | KeywordRetriever | HybridRetriever
                                                                    ├─ vector.search(depth 50)
                                                                    ├─ keyword.search(depth 50)
                                                                    └─ rrf(k=60)[:k]
 p50: 3.6 / 31.6 / 48.5 ms   (sequential; concurrent ≈ max of the two)
```

**Trap.** Mode `if`s scattered across the API and the eval code.

**Bridge.** "The same interface is what the reranker wraps in Phase 8."

---

## Phase 8 questions

### Q: Design the retrieve-then-rerank pipeline for 100× the traffic. Where does the time go?
**ID:** P8-04 · **Round:** system design  **Difficulty:** 4/5

**30-second answer.** "Today one query takes about 49 ms of first stage (vector 4 ms, keyword 32 ms at depth 50, sequential) plus 77 ms of reranking 10 pairs on the M1 GPU. The reranker dominates, and it's the only stage on a GPU. At 100× traffic I'd run reranking as a separate batched model service, run the two searches concurrently, cache by question hash, and keep N small. Measured, larger N didn't buy quality anyway."

**2-minute answer.** Explain batching: cross-encoder throughput rises with batch size, so a server collecting pairs from concurrent requests for a few milliseconds (dynamic batching) uses the GPU far better than one request at a time. Postgres scales with read replicas for the first stage. Then name the degradation path: if the reranker is slow or down, return the fused order. That's measured as worse but still useful (fig hit@1 0.46 instead of 0.82).

**If they push — level 2.** *"CPU-only deployment?"* MiniLM at N = 10 runs at 153 ms p50 on CPU, so it's feasible. Add replicas behind a queue; an int8 export would be faster.

**If they push — level 3.** *"What's the p95 story?"* Keyword search's tail (269 ms for the longest question) plus rerank p95 (91 ms). Cap OR terms and set per-stage timeouts.

**If they push — level 4.** *"Can you skip reranking for some queries?"* If the top fused hit is in both lists at rank 1, fusion is confident. A skip rule like that needs measurement on the golden set to show it doesn't lose accuracy.

**Whiteboard it.**
```text
 request → [vector 4 ms ∥ keyword 32 ms] → RRF <1 ms → rerank 10 pairs 77 ms → k=10
                 Postgres replicas                    GPU service, dynamic batching
 fallback: reranker timeout → fused order
```

**Trap.** Scaling the database when the reranker is the bottleneck.

**Bridge.** "Phase 13 measures the full budget, including the LLM, which will dwarf all of this."

---

## Phase 9 questions

### Q: Your app needs an API key that isn't available yet. How do you build and test it?
**ID:** P9-04 · **Round:** system design · behavioural  **Difficulty:** 2/5

**30-second answer.** "Put the provider behind a two-method interface, generate and stream, with three implementations: the real OpenAI client, a deterministic fake that quotes the best-matching source sentence with its citation, and a cache wrapper. The real client is tested by running the actual SDK against a mocked HTTP transport, which checks the request body, auth header, usage parsing, SSE streaming and 401 handling. No silent fallback: without a key, `LLM_PROVIDER=openai` fails loudly."

**2-minute answer.** Explain why the fake is useful but dangerous. It exercises packing, citation mapping and refusal end to end, so pipeline bugs surface early; the marker-after-period bug was found this way. But its answers aren't model quality, so every output line is labelled with the provider, and numbers that need the real model are written as "not yet measured".

**If they push — level 2.** *"Why mock HTTP rather than the SDK object?"* Mocking the transport runs the SDK's own request building and response parsing, so an SDK upgrade that changes behaviour breaks the test.

**If they push — level 3.** *"How do you keep the key safe?"* `.env` is git-ignored, the setting is a `SecretStr` (repr shows asterisks; tested), the key is never logged, and `store=False` on requests.

**If they push — level 4.** *"Contract drift between fake and real?"* The fake follows the same contract (cite with [n], refusal token), but a real model can break it. That's measured, not assumed, once the key exists.

**Whiteboard it.**
```text
 LLM interface: generate(instructions, user) · stream(...)
   ├─ OpenAIClient   (Responses API; tested via httpx.MockTransport)
   ├─ FakeLLM        (extractive, deterministic; opt-in, labelled)
   └─ CachedLLM(inner, conn)   (sha256 key → llm_cache)
 no key + provider=openai → MissingAPIKey (loud)
```

**Trap.** Falling back to the fake automatically, so a demo looks like it works.

**Bridge.** "Phase 10's API streams through the same interface."

---

## Phase 10 questions

### Q: Design the API for a streaming RAG answer. What are the endpoints and events?
**ID:** P10-01 · **Round:** system design · backend screen  **Difficulty:** 3/5

**30-second answer.** "Four endpoints: GET /health, GET /documents, POST /query returning one JSON object, and POST /query/stream returning Server-Sent Events. The stream sends `sources` first (about 100 ms, before the LLM has produced anything), then `delta` events with text, then a final `answer` with checked citations, usage and timings, or an `error` event. Validation, LLM configuration and filter checks all happen before the 200, so they're normal JSON errors."

**2-minute answer.** Explain each contract decision. Typed request model: 1–2,000 chars, k 1–20, plausible years, filter lists ≤ 10. Companies checked against the database. One error envelope with stable codes. A request id on every response. JSON-encoded SSE payloads so newlines can't break frames. A refusal gate so the raw refusal token never streams. The DB connection is released before the LLM call.

**If they push — level 2.** *"Why two endpoints instead of one with a flag?"* Different response media types (JSON vs event-stream) and different error semantics. Separate routes keep both contracts explicit in OpenAPI.

**If they push — level 3.** *"How would a browser consume a POST stream?"* `EventSource` only does GET, so use `fetch` with a streaming body reader and parse the frames. Streamlit does it server-side with httpx.

**If they push — level 4.** *"Versioning?"* Prefix routes (/v1) or a version field. Add fields freely, never remove or re-type one within a version. The request id ties client reports to logs.

**Whiteboard it.**
```text
 POST /query/stream {question, companies?, fiscal_years?, k?}
   pre-checks → 422 / 503 JSON
   200 text/event-stream
     event: sources  [{n, chunk_id, doc_key, page, section, score, text}]
     event: delta    "…"   (×n, JSON strings)
     event: answer   {answer, refused, citations[], usage, timings_ms}
     event: error    {error, message, status}   (only after the 200)
```

**Trap.** Validating inside the stream, after the 200.

**Bridge.** "The UI in Phase 15 is just a client of this contract."

---

### Q: Your service handles 2× the throughput with 4 clients, not 4×. Explain, and scale it.
**ID:** P10-02 · **Round:** system design  **Difficulty:** 4/5

**30-second answer.** "Measured: 6.8 req/s sequential, 13.7 req/s with 4 clients, latency p50 143 → 281 ms. Each request does Postgres work, which overlaps across threads, and model forward passes (embed the question, rerank 10 pairs), which are serialised by a lock because MPS isn't thread-safe. The GPU passes are the shared bottleneck. To scale: a separate model service with dynamic batching, concurrent vector and keyword searches, a connection pool, and horizontal API replicas."

**2-minute answer.** Do the arithmetic: with ~110 ms of retrieval of which ~80 ms is reranking, the serialised part bounds throughput near 1/0.08 ≈ 12 req/s for the model half, which matches the measured 13.7. Then the real-LLM view: generation adds seconds, but that's I/O wait in a thread, so the bottleneck shifts to thread-pool size (AnyIO default 40) for concurrent streams. That's when to move streaming to async.

**If they push — level 2.** *"Why not more uvicorn workers?"* Each process loads both models (224 MB of weights) and they'd contend for one GPU. It helps on CPU-only boxes with RAM to spare.

**If they push — level 3.** *"Cache?"* The exact-match LLM cache already makes repeats free. A retrieval cache keyed by (question, filters) would skip the model passes for repeated questions.

**If they push — level 4.** *"SLOs?"* Time to first event p95 < 300 ms, full answer p95 < N s (set once real-model latency is measured), error rate by code. Alert on llm_quota_exhausted immediately, since it's not transient.

**Whiteboard it.**
```text
 per request: [DB ‖ DB] + [embed → rerank]🔒 + LLM wait (thread)
 1 client 6.8 req/s · 4 clients 13.7 req/s (model lock ≈ 80 ms → ~12 req/s cap)
 scale: model service (batching) · pool · async streams · replicas
```

**Trap.** Scaling the web framework when the GPU lock is the limit.

**Bridge.** "Phase 13's per-stage timings make this breakdown visible per request."

---

## Phase 11 questions

### Q: Design an evaluation pipeline that a team can trust over months of changes.
**ID:** P11-05 · **Round:** system design  **Difficulty:** 3/5

**30-second answer.** "A versioned golden set with exact evidence labels, re-validated on every load; a runner that takes the full configuration as flags; deterministic retrieval and a response cache for LLM calls; and results written to new timestamped files, never overwritten, each recording the git commit, a dirty flag, the golden file's hash and every config value. Every metric gets a bootstrap interval, and comparisons use paired tests. My runner does all of this, and two identical runs produced identical rows for all 61 questions."

**2-minute answer.** Add the parts that keep it honest over time: an external set (FinanceBench) as a held-out check; a label-audit step with each change producing a new hash; a results history that shows step changes (bug fix +3.9 points, label audit +3.8 points) instead of one "latest" number; and judge validation against a human-labelled sample before trusting small judged differences.

**If they push — level 2.** *"CI integration?"* Run the retrieval eval (12 s, no API cost) on every PR and fail if hit@5 drops by more than the noise band. Run the judged eval nightly with the cache.

**If they push — level 3.** *"Online evaluation?"* Log real questions, sample them for labelling, track refusal and citation-click rates, and A/B test retrieval changes.

**If they push — level 4.** *"Cost control for judged evals?"* Cache keyed by the full request, a pinned judge model, and only re-judging rows whose answer changed.

**Whiteboard it.**
```text
 golden (sha) + config flags → runner → results/<time>_<name>.{json,csv} (mode x)
   meta: git commit · dirty · golden sha · python
   summary: metric means + 95% CI · by type · abstention · judge
 compare runs: paired sign test · history of step changes
```

**Trap.** One "latest score" in a spreadsheet, overwritten each run.

**Bridge.** "Phase 12 runs the ablation matrix through exactly this runner."

---

## Provider-switch questions (2026-10-02)

### Q: You switched LLM providers mid-project. What did it cost, and what's the real lock-in?
**ID:** P11-09 · **Round:** system design · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "The pipeline only knows a two-method client, generate and stream, behind settings for provider, base URL, models and key. Moving from OpenAI to Gemini meant rewriting that client from OpenAI's Responses API to Chat Completions, because Gemini's compatibility endpoint answers Responses with 404, plus four `.env` lines. Retrieval, embeddings and every retrieval number were untouched. The real lock-in is evaluation history: cached responses and judge scores are tied to one generator and judge, so after a switch every judged eval is re-run, and old and new numbers are never compared."

**2-minute answer.** List what 'compatible' didn't cover, all measured: no Responses API; `reasoning_effort="none"` rejected by Flash-Lite with a 400; Gemini's thinking tokens counting against `max_tokens` (an answer cut to '1'); errors wrapped in a list; different tokenizer (15% more tokens than o200k for the same prompt). Each became a setting, a flag or a test.

**If they push — level 2.** *"Why not the native Gemini SDK?"* It would buy Gemini-only features (thinking budgets, context caching) at the price of a second code path. Not needed yet.

**If they push — level 3.** *"How do you pick the model?"* List what the key can actually use, probe each candidate with a one-token call, and pin a dated name, not an alias. Here 3.8 and 3.7 Flash returned 503, and the 2.5 models 404.

**If they push — level 4.** *"What breaks if you switch back?"* Nothing in code. Cached answers miss (provider, endpoint and model are in the key), so the first eval re-pays, and the judge changes, so judged numbers restart.

**Whiteboard it.**
```text
 settings: LLM_PROVIDER · LLM_BASE_URL · LLM_MODEL · LLM_JUDGE_MODEL · <PROVIDER>_API_KEY
 ChatClient (OpenAI SDK, chat.completions) ── retries ── CachedLLM (key ∋ provider, url, model, params)
 not portable: Responses API · reasoning_effort values · tokenizer · error shapes · prices
```

**Trap.** "It's OpenAI-compatible, so it's a drop-in."

**Bridge.** "That's why every result file records provider, endpoint and model."

---

### Q: Design retries for an eval sweep of hundreds of LLM calls so it can't die halfway.
**ID:** P11-10 · **Round:** backend screen · system design  **Difficulty:** 3/5

**30-second answer.** "Three layers. Per call: retry 429 rate limits, 5xx, timeouts and dropped connections with exponential backoff (1 s · 2^attempt, capped at 30 s, jittered into [½, 1]), honour Retry-After, and don't retry 4xx or an empty balance, because waiting doesn't fix those. Per question: if a call still fails after six retries, record the error in the row and continue. Per run: every successful response is cached by a hash of the full request, so rerunning the sweep only pays for what failed."

**2-minute answer.** Explain why our own retries replace the SDK's (`max_retries=0` there): one policy, logged retries, and quota detection. Explain why a stream is retried only before its first token: text already shown can't be retracted. The measured cache effect: the 6-question smoke eval took 101 s and 16,572 input tokens the first time, and 13 s and 0 tokens on rerun.

**If they push — level 2.** *"Why jitter?"* Without it, every client that failed at the same moment retries at the same moment and collides again (a thundering herd).

**If they push — level 3.** *"How long can one call wait?"* 1+2+4+8+16+30 ≈ 61 s of backoff at most (times jitter), plus the 60 s timeout per attempt.

**If they push — level 4.** *"Rate limits across parallel workers?"* Add a client-side token bucket matched to the provider's limit, so 429s become rare rather than retried.

**Whiteboard it.**
```text
 retry: 429 (not quota) · 5xx · timeout · connection   no retry: 4xx · insufficient_quota
 wait = min(30, 1·2^n) · U(½,1), ≥ Retry-After
 run: question fails after retries → row.error, continue · rerun → cache hits, 0 tokens
```

**Trap.** Retrying everything, including auth errors and empty balances.

**Bridge.** "The cache is what makes reruns cheap; retries are what make them rare."

---

### Q: Your model's answer came back as just "1". What happened?
**ID:** P11-11 · **Round:** ML screen · debugging  **Difficulty:** 2/5

**30-second answer.** "Gemini 3.x Flash thinks before answering, and those hidden thinking tokens come out of `max_tokens`. With a 60-token cap it spent almost all of it thinking and returned '1' with `finish_reason` 'length'. With `reasoning_effort=none` the same request gave '1, 2, 3, 4, 5' and stopped normally. So the output cap is 2,048, reasoning effort is a setting, and every result keeps its finish reason. A 'length' stop is flagged `truncated` in the API and counted in evals, even when served from the cache."

**2-minute answer.** Generalise it: always check finish reasons. A truncated answer can still look plausible and even carry citations, so a silent cut becomes a silent quality bug. Thinking tokens are also billed as output, which changes cost estimates.

**If they push — level 2.** *"Why not disable thinking?"* Calculation questions (margins, differences) may benefit from it. It's an ablation, and the default is 'low'.

**If they push — level 3.** *"Can you see thinking tokens in usage?"* Not broken out on this endpoint: total minus prompt minus completion gives them indirectly (68 − 12 − 1 = 55).

**If they push — level 4.** *"Does the judge have the same issue?"* Flash-Lite didn't show it in the probe, but its results carry the same finish reason.

**Whiteboard it.**
```text
 max_tokens=60, effort default → finish=length, text '1', total 68 (prompt 12 + completion 1 + ~55 thinking)
 effort=none                   → finish=stop,   text '1, 2, 3, 4, 5'
 fix: cap 2048 · effort setting · truncated flag (cached too)
```

**Trap.** Treating every 200 response as a complete answer.

**Bridge.** "finish_reason is now a column in the cache and the eval rows."

---

## Phase 12 questions

### Q: Design an ablation that a reviewer would believe.
**ID:** P12-05 · **Round:** system design · ML screen  **Difficulty:** 3/5

**30-second answer.** "Vary a full grid, not one factor at a time, because factors interact. Keyword search scored 0.538 to 0.769 depending on chunking. Hold everything else fixed: same questions, embedding model, k, fusion constant, index settings. Run every cell through the same evaluation code. Compare each cell to the baseline with a paired test, and check every cell on an external set. Make it resumable and record the label hash, so reruns reuse results. Mine: 54 cells + 3 extras, 8 minutes, no LLM calls."

**2-minute answer.** Explain why each piece matters. The grid exposes interactions. Paired tests separate effects that overlapping CIs hide. The external set catches tuning to the test set's style (here, the −0.53 correlation). Multiple-comparisons awareness: act only on effects far beyond chance. And the embedding model stays fixed, because re-embedding would change everything at once.

**If they push — level 2.** *"Cost control?"* Retrieval-only cells cost nothing. Judged generation runs are limited to a few key configurations, with every LLM call cached.

**If they push — level 3.** *"How do you keep the ablation code honest?"* Each cell *is* an ordinary eval run with flags. No separate scoring path exists to drift.

**If they push — level 4.** *"Bigger grids?"* Fractional-factorial designs, or a sequential search (screen factors cheaply, refine around the robust region).

**Whiteboard it.**
```text
 grid 3 strategies × 3 sizes × 3 modes × 2 rerank = 54 (+3 extras)
 fixed: model · k · RRF k · depth · ef_search · labels (sha)
 per cell: eval.run → JSON · paired sign test vs base · FinanceBench check
```

**Trap.** One-factor-at-a-time on a single test set.

**Bridge.** "The external check is what turned this from a leaderboard into a finding."
