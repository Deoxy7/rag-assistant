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
