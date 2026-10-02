# 08 — Debugging scenarios

**Status:** started in Phase 0 (2026-10-02); scenarios are added each phase (target: 15+). Planned: retrieval metrics great but answers wrong; hybrid worse than dense alone; quality collapsed after an embedding-model upgrade; retrieval fails for one subset of documents; confidently cited the wrong document; p99 spiked after a deploy; index got slower as data grew; eval scores improved but users complain.

Every answer is a **diagnostic tree**: what to check first, second, third — and what each outcome rules out. Not a list of guesses.

---

### Q: Your tests pass on your laptop but fail on a teammate's. How do you debug it?
**ID:** P0-11 · **Round:** backend screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "I treat it as 'what differs between the two machines' and check the cheapest, most likely differences first: is the database even up and reachable; is it the same database (image digest, extension version); is it the same Python and the same packages; is it the same configuration. Each check either finds the difference or rules a whole layer out."

**2-minute answer — the tree.**
1. **Read the failure, not just the count.** All database tests *erroring* at setup with `Cannot reach Postgres at 127.0.0.1:5432` → environment, not code. Go to 2. A single assertion failing → go to 4.
2. **Is Docker running and the container healthy?** `make up` prints `Docker is not running. Start it with: colima start` if the VM is down; `docker compose ps` should show `(healthy)`. If healthy but connections fail → 3.
3. **Credentials and ports.** `password authentication failed` → the teammate's volume was initialised with a different password (it's baked in at first start). `port is already allocated` → a local Postgres holds 5432. Fixes: [03 §8](../03-environment-and-infra.md#8-failure-modes).
4. **Same database?** `docker compose ps` shows the image with its digest; `SELECT extversion FROM pg_extension WHERE extname='vector'` must be `0.8.7`. A test for exactly this exists, so a mismatch fails by name.
5. **Same Python and packages?** `.venv/bin/python --version` must be 3.11.x; `pip freeze` diffed against `requirements.txt`. A venv built with the wrong `python3` is the classic.
6. **Same config?** Diff `.env` against `.env.example` (never paste the real values into chat).
7. **Only now, the code.** If everything above matches, it's a genuine non-determinism or an ordering dependency between tests — rerun the failing test alone.

**If they push — level 2.** *"How do you prevent this class of problem?"* Pin everything (image digest, `==` versions, Python version in the Makefile), make setup one command, and have tests that check the environment itself — pgvector version, password enforcement — so a drifted machine fails with a message that names the cause.

**If they push — level 3.** *"What if it's flaky — passes sometimes?"* Suspect timing: was a test run before the database was ready? That's why `make up` uses `--wait` on a healthcheck. Then shared state: tests that depend on data another test wrote. Run the suite in random order to expose it.

**If they push — level 4.** *"And CI?"* CI is just another machine; the same tree applies. The fix is making CI run `make test` exactly as a developer does, from a clean checkout, so "works locally" and "works in CI" mean the same thing.

**Whiteboard it.**
```text
 errors at setup? ─yes─▶ docker up? ─▶ healthy? ─▶ password/port? 
       │no
 same image digest? ─▶ same python+pip freeze? ─▶ same .env? ─▶ then code
```

**Trap.** Starting with the code. Most "works on my machine" failures are environment differences, and the tree finds them in minutes.

**Bridge.** "That's why I pin the database image by digest — happy to explain tag vs digest."

---

### Q: The database container reports healthy, but every connection fails authentication. Walk me through it.
**ID:** P0-12 · **Round:** backend screen · viva  **Difficulty:** 3/5

**30-second answer.** "Healthy only means Postgres accepts connections — `pg_isready` doesn't check passwords. So the server is fine and the credentials disagree. The usual cause with the official image: `POSTGRES_PASSWORD` is applied only when an empty volume is first initialised. If someone changed it in `.env` afterwards, the client sends the new one while the server still holds the old one."

**2-minute answer — the tree.**
1. **Confirm it's authentication, not reachability.** The message is `FATAL: password authentication failed for user "rag"` — the server answered, so network and port are fine.
2. **Which password is the client sending?** `app/config.py` reads `.env`; check whether `.env` changed recently (`git` won't help — `.env` is ignored — so compare with `.env.example`).
3. **When was the volume created?** If before the change, the server has the old password. `docker volume inspect rag-assistant_pgdata` shows the creation time.
4. **Which auth rule applies?** `pg_hba.conf` trusts connections from *inside* the container but requires SCRAM for ours, which arrive from the Docker bridge network (`inet_client_addr()` = 172.18.0.1). So `make psql` (inside) works while the app (outside) fails — a strong clue for this exact cause.
5. **Fix:** restore the old password; or `ALTER ROLE rag PASSWORD '…'` via `make psql`; or `make db-reset` if the data is disposable.

**If they push — level 2.** *"Why does `make psql` work when the app doesn't?"* `psql` inside the container connects over the local socket, which `pg_hba.conf` marks `trust` — no password checked. The app connects via the published port and hits the `scram-sha-256` rule.

**If they push — level 3.** *"Is trusting local connections inside the container a security risk?"* Only someone who can already exec into the container — i.e., who controls Docker on this machine — benefits, and they could read the data files anyway. Network clients still need the password; `test_wrong_password_is_rejected` locks that in.

**If they push — level 4.** *"How would you handle this in production?"* Passwords don't live in a file that drifts: they come from a secrets manager, rotation is done with `ALTER ROLE` plus a coordinated config update (or two roles alternating), and connections use TLS.

**Whiteboard it.**
```text
 healthy? ─yes─▶ error = "password authentication failed"? ─yes─▶ server answered
   ─▶ .env changed after volume init? ─yes─▶ old pw in DB, new pw in client
   ─▶ psql inside works, app outside fails? → pg_hba trust vs scram ✔
```

**Trap.** "The database is broken, recreate it." Deleting the volume works but destroys data; the diagnosis takes two minutes and the fix can be one `ALTER ROLE`.

**Bridge.** "The general lesson — init-time configuration is applied once — shows up again with the init SQL scripts."

---

### Q: Your section detector says the signature page of a 215-page filing is page 2. Walk me through finding the bug.
**ID:** P1-05 · **Round:** project deep-dive · backend screen  **Difficulty:** 2/5

**30-second answer.** "Page 2 of a 10-K is the table of contents, which lists 'Signatures' as an entry — so a detector matching the word on its own line fires there first. The fix was to anchor on something only the real page has: the fixed legal sentence 'Pursuant to the requirements of Section 13…'. That moved Boeing from page 2 to page 145, which I confirmed by printing the page."

**2-minute answer — the tree.**
1. **Is the output plausible?** A signature page on p.2 of 215 isn't — sanity-check outputs against what you know about the document.
2. **Print what matched.** The match was on the TOC page, inside a list of section names.
3. **Find a more specific anchor.** The signature page always carries a legal sentence; the TOC never does.
4. **Check every document, not one.** The first "fixed" pattern still failed for Boeing, which writes "Section 13" without "or 15(d)" — so the pattern requires only the common prefix.
5. **Lock it in.** A synthetic test PDF has "Signatures" in its TOC and the statement on page 7; the test asserts 7.

**If they push — level 2.** *"Why did this matter?"* "Pages after the signatures" was the first idea for identifying exhibits. A wrong signature page would have labelled almost the whole Boeing filing as exhibits.

**If they push — level 3.** *"And was 'after the signatures = exhibits' right once fixed?"* No — Corning puts its financial statements after the signatures. So the label became "after signatures", never "exhibit", and nothing is dropped by position.

**If they push — level 4.** *"How do you make heuristics like this robust in general?"* Anchor on content a section must contain, not on its title; verify across every document; keep a test for each failure you've seen. Beyond that, layout-aware models exist, but I'd want evidence they beat a tested heuristic on this corpus.

**Whiteboard it.**
```text
 /^signatures$/        → p.2  (TOC entry)      ✗
 "pursuant to … section 13 or 15(d)" → Boeing: none  ✗
 "pursuant to … section 13"          → p.145   ✓  + synthetic test
```

**Trap.** Testing a heuristic on one document. Both bugs only showed up across all ten.

**Bridge.** "The same 'verify on every document' rule is why the inspection runs before any parsing code."

---

### Q: A download fails with CERTIFICATE_VERIFY_FAILED on macOS but works in your browser. Debug it.
**ID:** P1-06 · **Round:** backend screen  **Difficulty:** 2/5

**30-second answer.** "The browser uses the operating system's certificate store; Python's `ssl` module uses OpenSSL's CA file. The python.org build of Python on macOS ships without one — `ssl.get_default_verify_paths()` pointed at `/Library/Frameworks/…/etc/openssl/cert.pem`, which didn't exist. So Python couldn't verify any server. I fixed it inside the project by building the SSL context from `certifi`'s CA bundle."

**2-minute answer — the tree.**
1. **Is it the server or the client?** Browser and curl succeed → the server's certificate is fine; the client can't verify it.
2. **Which CA file is Python using?** `python -c "import ssl; print(ssl.get_default_verify_paths())"` → a path that doesn't exist.
3. **Options:** run the installer's "Install Certificates" script (changes the system Python), set `SSL_CERT_FILE` (fragile across shells), or pass `ssl.create_default_context(cafile=certifi.where())` (project-local, pinned).
4. **Never** disable verification (`verify=False`) — that removes protection against a man-in-the-middle.

**If they push — level 2.** *"Why did `tiktoken` work without the fix?"* It downloads through `requests`, which uses `certifi` automatically. Only the standard-library `urllib` call needed the explicit context.

**If they push — level 3.** *"What does certificate verification actually check?"* That the server's certificate chain leads to a trusted root CA, that it hasn't expired, and that the hostname matches. Without a CA bundle the first check can't pass.

**If they push — level 4.** *"Corporate proxy that intercepts TLS?"* Then you add the company's root CA to the bundle you trust; you still don't disable verification.

**Whiteboard it.**
```text
 browser → OS keychain ✓      python urllib → OpenSSL cafile (missing) ✗
 fix: ssl.create_default_context(cafile=certifi.where())   (pinned in requirements)
 never: verify=False
```

**Trap.** Disabling verification "just for the download".

**Bridge.** "Pinning `certifi` in requirements.txt keeps even the CA bundle reproducible."

---

### Q: Running headers were removed everywhere except your largest document. Debug it.
**ID:** P2-04 · **Round:** project deep-dive · backend screen  **Difficulty:** 3/5

**30-second answer.** "The rule was 'a line in the top or bottom band on at least 30% of pages'. PepsiCo's 'Table of Contents' header is on its 129 body pages, but the PDF has 503 pages because of exhibits — and 30% of 503 is 150. The threshold scaled with something that wasn't the population the header lives in. The fix was an absolute floor of 5 pages plus a 10% share."

**2-minute answer — the tree.**
1. **Is the line in the band?** Print the block's bbox: y1 = 17 on an 842-point page, well inside the top 8% — so detection, not geometry.
2. **What's its count vs the threshold?** 129 pages vs threshold 150 — found it.
3. **Why does only PepsiCo fail?** It's the only document where most pages (374–420) aren't body pages.
4. **Fix and side effects:** lowering the share risks removing real repeated content; the 5-page floor plus band restriction keeps that unlikely. Re-run all ten and compare removal counts (PepsiCo 0 → 129).
5. **Lock it in:** the synthetic test asserts exact removal counts.

**If they push — level 2.** *"Couldn't you count only body pages?"* Yes, if the signature page were reliable for every document — it isn't a clean boundary (Corning's financials are after it), so I kept a rule that doesn't depend on it.

**If they push — level 3.** *"What would a false positive look like?"* A genuine repeated line in the band, like a recurring table caption at the very top. It would vanish from the text; I'd see it as a drop in that phrase's frequency between raw and parsed text.

**If they push — level 4.** *"How do you catch this class of bug generally?"* Per-document summary stats after every parser change — a document whose removal count is zero while siblings remove hundreds is an outlier worth reading.

**Whiteboard it.**
```text
 pages 503 (129 body + 374 exhibits)   header on 129
 old: 129 ≥ 0.30×503 = 150?  no  → kept ✗
 new: 129 ≥ max(5, 0.10×503 = 50)? yes → removed ✓
```

**Trap.** Tuning the threshold until the one document works, without asking why it differed.

**Bridge.** "Per-document stats are also how I'll report eval metrics, so one company can't hide behind the average."

---

### Q: One company's section headings vanished after parsing. Walk me through it.
**ID:** P2-05 · **Round:** project deep-dive  **Difficulty:** 3/5

**30-second answer.** "Corning 2021 had 18 headings for 125 pages while its 2022 filing had over 200. Printing the raw PyMuPDF blocks showed whole sections — running header, two Item headings and body — merged into one block, separated only by lines containing a non-breaking space. Headings were inside long blocks, so 'short and bold' never matched. Splitting blocks at blank lines and bold changes fixed it: 1,429 blocks and 169 headings."

**2-minute answer — the tree.**
1. **Compare with a sibling.** Same company, next year: 213 headings. Same generator? No — Corning 2021 used "EDGAR PDF Generator", 2022 "EDGRpdf Service".
2. **Inspect raw blocks on one page.** p.21: five blocks; the first starts "Table of Contents Item 1B. Unresolved Staff Comments None. Item 2. Properties…".
3. **Inspect lines in that block.** Bold lines for the Item headings, separated by lines whose only character is `\xa0`.
4. **Fix at the right level.** Split at blank lines (lines with no visible spans), at bold/normal changes, and at lines starting PART/ITEM.
5. **Verify across all ten:** no document lost headings; Corning's running header now sits in its own block and gets removed too.

**If they push — level 2.** *"Why did the running header survive before?"* It was glued to the Item heading inside one block, whose box extended far below the header band.

**If they push — level 3.** *"Could splitting on bold changes over-split?"* Yes — a paragraph with one bold phrase in the middle becomes three blocks. Chunking re-joins small blocks, so the cost is low; I accepted it.

**If they push — level 4.** *"How would you detect this automatically next time?"* An alert on headings-per-page and median block length per document relative to the corpus — Corning 2021's median block was far longer than its peers.

**Whiteboard it.**
```text
 block: "Table of Contents" | "\xa0" | "Item 1B…"(bold) | "\xa0" | "None." | "\xa0" | "Item 2…"(bold)
 split at blank lines + bold changes → 5 paragraphs, 2 headings
 Corning 2021: 509 blocks / 18 headings → 1,429 / 169
```

**Trap.** Fixing heading detection thresholds instead of looking at the raw structure.

**Bridge.** "Section paths matter because the structure-aware chunker splits on them."

---

### Q: Your library's offsets come back as -1 for some chunks. Debug it.
**ID:** P3-04 · **Round:** project deep-dive · backend screen  **Difficulty:** 3/5

**30-second answer.** "LangChain's recursive splitter has `add_start_index=True`, and with a token-based length function it returned -1. Reading its source: it computes the search position as `index + previous_chunk_len - chunk_overlap` — subtracting the overlap as characters. My overlap is 32 tokens, about 150 characters, so the search starts past the real chunk start and `find` fails. I stopped trusting its offsets and locate each chunk myself from the previous chunk's start."

**2-minute answer — the tree.**
1. **Fail loudly first.** My wrapper compares `doc.text[start:end]` with the chunk text and raises on mismatch — that's how -1 surfaced instead of producing silently wrong citations.
2. **Reproduce minimal.** A synthetic text with token length and overlap 20 shows -1 deterministically.
3. **Read the library source** (`inspect.getsource`) rather than guess: unit mismatch between `chunk_overlap` (our tokens) and string positions (characters).
4. **Fix at the boundary I own:** `doc.text.find(chunk, previous_start + 1)` — correct because chunks are emitted in order and each starts after the previous.
5. **Pin it:** a test asserts LangChain still returns -1 (so I notice if they fix it) and that my offsets are exact.

**If they push — level 2.** *"Could `find` match the wrong occurrence of repeated boilerplate?"* Only an earlier one — and searching from the previous start excludes those. Identical text later in the document can't be matched first because the search moves forward monotonically.

**If they push — level 3.** *"Why not report it upstream?"* I would; the test documents the exact behaviour in a version-pinned way.

**If they push — level 4.** *"General lesson?"* Never trust derived metadata from a library on the critical path of correctness without an invariant check. Here the invariant is one line.

**Whiteboard it.**
```text
 LangChain: offset = index + prev_len − chunk_overlap   (overlap in tokens, used as chars)
 ours:      start  = text.find(chunk, prev_start + 1);  assert text[start:start+len] == chunk
```

**Trap.** Patching around -1 with a fallback search everywhere instead of understanding the unit bug.

**Bridge.** "The same invariant protects every chunker, which is why evaluation can compare them fairly."

---

### Q: A 256-token window measures 257 when you re-count it. What's going on?
**ID:** P3-05 · **Round:** ML screen · DSA  **Difficulty:** 3/5

**30-second answer.** "WordPiece splits words into pieces — '16,434' is `16 | , | 43 | ##4`. My first windows were cut at arbitrary tokens, so a window could start at `##4`. Re-tokenizing that slice alone treats '4' as a new word, so the pieces — and the count — change. Fix: group tokens into whole words using their character offsets (a token that starts where the previous ended continues the word) and cut only between words."

**2-minute answer.** Why it matters: at the 510 ceiling an off-by-one becomes silent truncation. Then the algorithm: one pass over offsets builds word groups (O(n)); windows accumulate whole words until adding the next would exceed the size; overlap steps back whole words.

**If they push — level 2.** *"Is 'contiguous offsets = same word' exactly right?"* It groups punctuation attached to a word too ("16,434" as one unit), which is fine — the goal is a boundary where re-tokenization is stable, and whitespace boundaries are.

**If they push — level 3.** *"Complexity of chunking a document?"* Tokenizing is linear in characters; grouping and windowing are linear in tokens; each window's count is re-verified, so O(n) overall with a constant factor for re-tokenizing slices.

**If they push — level 4.** *"What about a single 'word' longer than the window?"* The loop takes it anyway (`last == first` guard) so it can't stall; it would exceed the size. No such token run exists in this corpus; I'd split by characters if one did.

**Whiteboard it.**
```text
 tokens: net revenue $ 16 , 43 ##4      spans contiguous → one word "16,434"
 cut between words only → slice re-tokenizes identically
```

**Trap.** Counting tokens once and assuming any slice keeps the same count.

**Bridge.** "That's the kind of bug a property test catches — every chunk's count is re-measured."

---

### Q: Your vector query is slow and EXPLAIN shows a sequential scan, although an HNSW index exists. Why?
**ID:** P4-08 · **Round:** backend screen  **Difficulty:** 3/5

**30-second answer.** "The planner uses an index only if the query matches it exactly. My index is on the expression `embedding::vector(384)` with operator class `vector_cosine_ops` and a partial predicate on chunk set and model. Any mismatch — no cast, the `<->` operator instead of `<=>`, a different chunk set, or a predicate the planner can't prove at planning time — and it falls back to scanning every row."

**2-minute answer — the tree.**
1. **Expression match?** `ORDER BY embedding <=> $q` vs `ORDER BY embedding::vector(384) <=> $q` — only the second can use the index.
2. **Operator match?** A cosine index serves `<=>` only; `<#>` or `<->` won't use it.
3. **Predicate match?** `WHERE chunk_set_id = 1 AND model = '…'` must imply the index's WHERE. With bound parameters in a generic plan, the planner can't prove it.
4. **LIMIT present?** HNSW serves `ORDER BY … LIMIT k`; without LIMIT the planner may prefer a full sort.
5. **Statistics?** After a big load, `ANALYZE` so the planner knows row counts (the pipeline runs it).

**If they push — level 2.** *"How do you confirm it's the predicate?"* Run the same query with literal values; if that uses the index and the parameterised one doesn't, it's plan caching. `SET plan_cache_mode = force_custom_plan` is the diagnostic.

**If they push — level 3.** *"Fix?"* Interpolate the chunk-set id and model as SQL literals via `psycopg.sql.Literal` (they come from configuration, not user input), or force custom plans for that session.

**If they push — level 4.** *"Could the planner pick a seq scan on purpose?"* On a tiny table, yes — scanning a few rows is cheaper than the index. My test sets `enable_seqscan = off` to show the index *can* be used.

**Whiteboard it.**
```text
 index: hnsw((embedding::vector(384)) vector_cosine_ops) WHERE set=1 AND model='m'
 query: ORDER BY embedding::vector(384) <=> q  WHERE set=1 AND model='m'  LIMIT 5   ✓
        ORDER BY embedding <=> q                                               ✗ seq scan
```

**Trap.** Adding more indexes instead of reading the plan.

**Bridge.** "Phase 5 pins this with a test that checks the plan under prepared statements."

---

### Q: The same benchmark gives two different answers depending on what ran before it. Debug it.
**ID:** P5-05 · **Round:** backend screen · project deep-dive  **Difficulty:** 4/5

**30-second answer.** "That's hidden state on the connection. I found two layers. First, `SET LOCAL` lasts until the end of the top-level transaction, and psycopg's nested `conn.transaction()` is only a savepoint — so an iterative-scan setting from an earlier search leaked into later searches. Second, after the same query runs five times psycopg prepares it server-side, and the cached plan ignored my later `enable_sort = off`. I proved each by bisecting: fresh connection, then 'after 50 exact searches', then 'after 50 post searches'."

**2-minute answer — the tree.**
1. **Reproduce in isolation**: fresh connection → 3.8 rows; inside the benchmark → 10 rows. State, not data.
2. **Bisect the preceding work**: 50 exact searches → no change; 50 post searches → flips. So something those searches leave behind.
3. **Hypothesis A — settings leak**: check `SHOW hnsw.iterative_scan` after searches inside an open transaction → leaked. Fix: set every setting on every search; regression test.
4. **Still flips → Hypothesis B — plan cache**: `prepare_threshold = None` → 3.8 rows; default → 10. Confirmed: `pg_prepared_statements` showed 3 statements.
5. **Fix the experiment**, not just the result: dedicated connection with auto-prepare off; document both (T-025, T-026).

**If they push — level 2.** *"How would you have caught this without two disagreeing runs?"* A test that runs searches in different orders and asserts identical results, and asserting settings after each call.

**If they push — level 3.** *"Does it affect production?"* The leak would have: a post-mode search after an iterative one on a pooled connection. The plan-cache issue doesn't change correctness — only planner experiments.

**If they push — level 4.** *"Connection pools?"* Pools reuse connections across requests, so any session state (settings, prepared statements, temp tables) leaks between requests unless reset. That's why per-transaction `SET LOCAL`, set explicitly every time, is the right pattern.

**Whiteboard it.**
```text
 fresh conn: 3.8   after 50 exact: 3.8   after 50 post: 10   ← state
 SET LOCAL in savepoint → survives → leak (fix: always set both)
 auto-prepare after 5 → cached plan ignores enable_sort (fix: prepare_threshold=None)
```

**Trap.** Rerunning until the numbers look right.

**Bridge.** "Benchmarks are code too — they need the same tests."

---

### Q: Keyword search for a company's goodwill returns lists of its subsidiaries. Debug it.
**ID:** P6-04 · **Round:** ML screen · backend screen  **Difficulty:** 3/5

**30-second answer.** "The query was 'goodwill impairment Corning'. With ts_rank_cd the top hits were subsidiary lists that repeat 'Corning' dozens of times. Cover-density ranking rewards query terms close together, and a list of 'Corning Holding GmbH, Corning Hungary…' is a dense run of one query term. ts_rank with length normalisation and BM25 with IDF both ranked the goodwill note first; I wrote a test that pins all three behaviours."

**2-minute answer — the tree.**
1. **Is it the match or the rank?** The goodwill note is in the candidate set (GIN finds it) — so ranking.
2. **What does the winner have?** Repeated `corn` lexemes, few or no `goodwil`/`impair`.
3. **Which ranking property rewards that?** Cover density (proximity of query terms) without IDF.
4. **Compare functions on the same query**: ts_rank_cd → list; ts_rank → note; BM25 → note (score 16.90 = 4.515 corn + 6.580 goodwil + 5.800 impair).
5. **Check the aggregate**, not one query: FinanceBench 28 questions — ts_rank 4, BM25 2, ts_rank_cd 2 hits; pick ts_rank (also fastest).

**If they push — level 2.** *"Why is 'Corning' `corn`?"* The Snowball stemmer strips '-ing'. It also means Corning queries match PepsiCo's corn — a stemming false positive.

**If they push — level 3.** *"Fix for the stemmer?"* A custom dictionary (synonym or exception list) for company names, or the `simple` configuration for proper nouns, or rely on the company metadata filter.

**If they push — level 4.** *"Generalisable lesson?"* Look at what the top result *has*, then ask which property of the scoring function rewards it — instead of tuning weights blindly.

**Whiteboard it.**
```text
 ts_rank_cd: "Corning Holding GmbH Corning Hungary…"  (dense 'corn')  ✗
 ts_rank:    "Corning's gross goodwill … impairment losses"           ✓
 bm25:       same, 16.90 = 4.52 + 6.58 + 5.80                          ✓
```

**Trap.** "Add BM25 and it's fixed" — plain ts_rank fixed it too.

**Bridge.** "I built BM25 to test that claim and kept the simpler option."

---

## Phase 7 questions

### Q: A benchmark says weighted fusion finds only 20 of 50 exact figures, but keyword search alone finds 50. Debug it.
**ID:** P7-04 · **Round:** ML screen · backend screen  **Difficulty:** 3/5

**30-second answer.** "This happened to me. Weighted fusion min-max normalises each list: (s − min)/(max − min). I guarded the divide-by-zero with `(max − min) or 1`, so a list with a single hit normalised to 0/1 = 0. Rare figures are usually matched by one or two keyword chunks, so the correct hit contributed nothing, and vector's junk filled the top 5. The fix: if all scores are equal, every hit counts as 1.0. After the fix, 49 of 50, and weighted fusion at 0.5 became competitive with RRF."

**2-minute answer.** Walk the debugging. The fused result was worse than *both* inputs on one column, which is impossible for a sensible fusion. So print the normalised scores for one figure query. Keyword's list had length 1 and score 0.0. Then add a regression test (`test_weighted_fusion_single_hit_list_counts_as_its_best`), rerun the bench, and update the write-up. The original doc had concluded "weighted fusion is worse at every weight", and that conclusion came from the bug.

**If they push — level 2.** *"Is a list of two still a problem?"* Min-max always maps the lower of two hits to 0. That's inherent to min-max, not a bug, and it's one reason rank-based fusion is more robust.

**If they push — level 3.** *"What other normalisations exist?"* Z-score (subtract mean, divide by std; undefined for n = 1), dividing by the max, or calibration to probabilities with labelled data.

**If they push — level 4.** *"How do you stop this class of bug?"* Treat a fused result worse than both inputs as a red flag in the bench output, and unit-test edge cases: empty list, one hit, all-equal scores.

**Whiteboard it.**
```text
 keyword list: [ (chunk 812, ts_rank 0.016) ]       lo = hi = 0.016
 buggy:  (0.016 − 0.016) / ((0) or 1) = 0.0   → contributes 0
 fixed:  hi == lo → 1.0                        → contributes α_kw
 figures hit@5 at α_vec = 0.3: 0.40 → 0.98
```

**Trap.** Concluding "weighted fusion is bad" from a bench that's worse than its own inputs.

**Bridge.** "That's also why I re-check conclusions whenever a result looks too clean."

---

### Q: Hybrid search finds the right chunk for "16,434" at rank 2, not rank 1, although keyword search alone has it at rank 1. Why?
**ID:** P7-05 · **Round:** ML screen · project deep-dive  **Difficulty:** 3/5

**30-second answer.** "The two lists don't overlap. Vector's top hits are unrelated number tables, and keyword's is the AMD revenue table. RRF gives each list's #1 the same 1/61, so it's a tie. My tie-break is best single rank, then chunk id, and vector's junk had the lower id. Across 50 figure queries, hybrid hit@1 is 0.46 but hit@5 is 1.00. RRF can't know which list to trust for a given query; the reranker, which reads the text, can."

**2-minute answer.** Explain the zipper: with disjoint lists the fused order alternates between the two lists. Then the options. A reranker over the top-N (the plan). Query routing: detect a figure and trust keyword. A smarter tie rule: prefer the list whose match satisfied a required phrase. A smaller k doesn't help, because the tie is exact for any k.

**If they push — level 2.** *"Why have a deterministic tie-break at all?"* Without it, the order depends on dictionary insertion order, and runs or refactors give different answers. Reproducibility first.

**If they push — level 3.** *"Is chunk id a good tie-break?"* It's arbitrary but stable. That's fine as a last resort, but here it decided more than half the figure queries, and I report that rather than hide it.

**If they push — level 4.** *"Would weighted fusion fix it?"* At an even weight, no: both normalised 1.0s tie the same way. At a keyword-heavy weight, yes, but then FinanceBench drops to 0.214.

**Whiteboard it.**
```text
 vector:  #1 Corning p106 (junk)   keyword: #1 AMD p48 (contains 16,434)
 RRF:     1/61 = 1/61  → tie → best rank 1 = 1 → chunk id 4853 < 5759
 fused:   #1 junk, #2 correct      figures: hit@1 0.46, hit@5 1.00
```

**Trap.** Blaming k, or claiming RRF "knows" keyword is right for numbers.

**Bridge.** "Which is exactly what a cross-encoder reranker is for."

---

## Phase 8 questions

### Q: For "What is PepsiCo's FY2021 capex?", the reranked #1 is Corning's capital expenditures paragraph. Debug it.
**ID:** P8-06 · **Round:** ML screen · backend screen  **Difficulty:** 3/5

**30-second answer.** "First check where the evidence is: PepsiCo's 2021 cash-flow statement was at fused rank 14 and the reranker moved it to 7, so it's ranking, not recall. The #1 passage literally says 'Capital expenditures were $1.6 billion…', a perfect topical match from the wrong company. The cross-encoder was trained on web search, where topic is what matters. Fix with a company/year filter: with the right filing, top-10 accuracy across FinanceBench doubles, 0.286 → 0.607."

**2-minute answer.** Show the debugging steps: print the candidates with doc keys, the evidence rank before and after reranking, and the reranker's score for each. Notice that the evidence chunk is a cash-flow *table*, which a web-trained model scores lower than a prose paragraph. Options in order of cost: filters from the UI or API; automatic extraction of company and year from the question; boosting chunks whose company matches a name in the question; fine-tuning on in-domain hard negatives; an LLM final stage.

**If they push — level 2.** *"Why didn't keyword search save it? 'PepsiCo' is in the question."* Company names rarely appear inside a chunk's text. The filing's identity is metadata (`documents.company`), not chunk words. That's another argument for filters.

**If they push — level 3.** *"Could you prepend the company and year to every chunk?"* Yes. Contextual chunk headers ("PepsiCo FY2021 10-K, Item 8: …") give both the embedder and the reranker the entity. It's a re-ingest, so it's a Phase 12 ablation.

**If they push — level 4.** *"How do you stop this regressing?"* Golden-set questions that name a company and year, with an assertion that the top hit's filing matches.

**Whiteboard it.**
```text
 fused #14 PEPSICO_2021 p63 cash-flow table   → reranked #7  (score −5.34)
 reranked #1 CORNING_2022 p37 'Capital expenditures were $1.6 billion…' (−2.15)
 fix: filter company=PepsiCo, year=2021 → FinanceBench hit@10 .286 → .607
```

**Trap.** "Use a bigger reranker." The 12× bigger one made the same kind of mistake.

**Bridge.** "That's the hard-negative design of the corpus paying off: it exposed this."

---

## Phase 9 questions

### Q: The citation checker says a sentence is uncited, but the answer clearly has "[1]" right after it. Debug.
**ID:** P9-06 · **Round:** backend screen  **Difficulty:** 2/5

**30-second answer.** "This happened. The answer was '…$16.4 billion. [1]'. My sentence splitter cuts after a full stop followed by a space, so '[1]' was glued to the start of the next sentence. The revenue claim looked uncited, and the next sentence looked cited by a source it never used. The fix: before splitting, move markers that follow a full stop to before it ('billion [1].'). A regression test pins both placements."

**2-minute answer.** Walk through it: reproduce with the exact string, print `sentences(answer)`, and see `['… billion.', '[1] Margin …']`. My first fix merged marker-only fragments into the previous sentence, which handles '[1]' on its own line but not '[1] Margin…'. The test caught that, and the normalisation handles both. Lesson: models write citations in several styles, so the parser accepts `[1]`, `[1][3]`, `[1, 3]` and marker-after-period.

**If they push — level 2.** *"Why not ask for JSON?"* It would remove the ambiguity, but it streams badly and adds output tokens. Parsing three marker styles is cheap and tested.

**If they push — level 3.** *"Other splitter traps?"* Decimals ('19.5%') aren't split because a space must follow. Abbreviations like 'Inc. and' would be split; that's harmless here because both halves get checked.

**If they push — level 4.** *"How would you test the parser at scale?"* Property tests: generate answers with random marker placements and check every claim maps to the marker the generator attached.

**Whiteboard it.**
```text
 in : "Revenue was $23.6 billion. [1] Margin was 45%."
 bad: ["Revenue was $23.6 billion.", "[1] Margin was 45%."]   → claim 1 uncited
 fix: "…billion [1]. Margin…" → ["Revenue was $23.6 billion [1].", "Margin was 45%."]
```

**Trap.** Blaming the model for not citing.

**Bridge.** "Found by the fake model, before any money was spent."

---

## Phase 10 questions

### Q: Users with a valid API key get "rate limited, retry later" forever. Debug.
**ID:** P10-03 · **Round:** backend screen · behavioural  **Difficulty:** 2/5

**30-second answer.** "That was my first error mapping. OpenAI returns HTTP 429 for two different things: a rate limit, which waiting fixes, and an exhausted balance (code `insufficient_quota` / `credit_balance_exhausted`), which it doesn't. I mapped every 429 to 'retry later'. Now the body's code is checked: an empty balance gives `503 llm_quota_exhausted, add credits`, and a real rate limit gives `llm_rate_limited`. There's a test for each."

**2-minute answer.** It was found for real: the key was valid (the free models endpoint confirmed `gpt-6-luna` exists), but the first generation call came back `credit_balance_exhausted`. The lesson is to classify errors by what the *user* must do, not by status code. Retrying a quota error also wastes time: the SDK retries 429s twice before giving up.

**If they push — level 2.** *"How do you surface it to operators?"* Log the code at warning level with the request id, and alert on llm_quota_exhausted immediately. Every request will fail until someone pays.

**If they push — level 3.** *"Could you degrade instead?"* Serve retrieval-only results (sources without an answer) with a banner. The stream already sends `sources` before the LLM call.

**If they push — level 4.** *"How do you test it without an empty account?"* Construct the SDK's `RateLimitError` with the real response body, as `test_empty_balance_is_not_reported_as_a_rate_limit` does.

**Whiteboard it.**
```text
 429 {"code":"rate_limit_exceeded"}      → llm_rate_limited    (retry with backoff)
 429 {"code":"credit_balance_exhausted"} → llm_quota_exhausted (add credits; don't retry)
```

**Trap.** Treating HTTP status codes as the whole error.

**Bridge.** "Phase 13 counts errors by code, not just by status."

---

### Q: The model's answer contains a blank line and the client shows half an answer. Why?
**ID:** P10-04 · **Round:** backend screen  **Difficulty:** 2/5

**30-second answer.** "In SSE a blank line ends an event. If the server writes raw model text into `data:`, a paragraph break ends the frame early, and the rest can even be parsed as a forged `event:` line. I JSON-encode every payload, so a newline travels as `\n` inside a string and the frame stays intact. A test streams a delta containing '\n\nevent: answer\ndata: forged' and checks the client still sees exactly one delta."

**2-minute answer.** The general rule: never put untrusted text into a line-delimited protocol unescaped. The same bug shapes appear as header injection, log injection and CSV injection. Here the model's output is untrusted, and Phase 14 adds documents that try to steer it.

**If they push — level 2.** *"Alternative?"* SSE allows multi-line data as several `data:` lines that the client rejoins with newlines. That's correct too, but JSON also gives typed payloads for the other events.

**If they push — level 3.** *"How do you test a protocol?"* Parse the raw bytes like a client would: split frames on blank lines, check event names and decode data.

**If they push — level 4.** *"Other framing risks?"* Carriage returns (`\r`) also end lines in SSE. JSON escapes them too.

**Whiteboard it.**
```text
 raw : data: Line one.⏎⏎event: answer⏎data: forged   ← frame ends early, forged event
 json: data: "Line one.\n\nevent: answer\ndata: forged"  ← one frame
```

**Trap.** Assuming model output is plain, safe text.

**Bridge.** "Untrusted text is the theme of the security phase."

---

## Phase 11 questions

### Q: Your new eval shows a retrieval method returning nothing for one question. What do you do?
**ID:** P11-03 · **Round:** ML screen · backend screen  **Difficulty:** 3/5

**30-second answer.** "It happened on 'What does the figure $404,381 represent in Boeing's FY2022 10-K?': keyword search returned zero rows. The query required the figure as a phrase *and* at least one other question word, and the backlog table contains none of 'figure', 'represent', 'Boeing' or 'FY2022'. The fix: the required phrase alone decides the match, and the other words only rank. A regression test pins it. hit@5 went from 0.692 to 0.731, and the Phase 6 and 7 benches were re-run and are unchanged, because they queried bare figures."

**2-minute answer.** The method: isolate one failing question; run each retriever separately at depth 50 and find the relevant chunk's rank in each (vector had it at 41, keyword returned nothing); print the generated tsquery; test the hypothesis on the stored chunk. Then check blast radius: re-run every earlier bench that used the code, and say in the docs that a published description was incomplete.

**If they push — level 2.** *"Why didn't the earlier benches catch it?"* They queried bare figures, so the 'other words' part was empty and the bug never triggered. The golden set has figures inside sentences, like real users.

**If they push — level 3.** *"What about MI250X, which also failed?"* That's different: it matches, but ts_rank has no IDF, so a rare code is outweighed by common words in a long OR query. That's BM25's job, measured in Phase 12, not patched.

**If they push — level 4.** *"How do you keep this kind of bug from returning?"* Questions whose answer contains a token the question names are a test category (exact_token), and a unit test covers a figure plus unrelated words.

**Whiteboard it.**
```text
 before: match = phrase('404,381') AND (figur | repres | boe | fy2022 | …)  → 0 rows
 after : match = phrase('404,381');  rank = phrase OR words                → table found
 hit@5 .692 → .731 · Phase 6/7 benches unchanged (bare figures)
```

**Trap.** Tuning weights to "make the number go up" before understanding why it was zero.

**Bridge.** "The harness's first job turned out to be finding bugs, not ranking methods."

---

## Phase 12 questions

### Q: An overnight eval sweep made almost no progress, logging 429 retries for an hour. Debug.
**ID:** P12-06 · **Round:** backend screen  **Difficulty:** 3/5

**30-second answer.** "This happened. After 10 minutes, only 3 of 20 questions were done and 59 retries logged. Reading the 429 body showed a *daily* free-tier quota, GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit 20, 'retry in 5h49m'. My policy treated every 429 except an empty balance as transient. The fix: detect daily quotas and any server-requested delay longer than the 30 s cap as non-retryable, and make the runner stop calling the LLM once a quota is exhausted, marking the remaining questions skipped. Cached answers are kept, so a rerun after the reset resumes cheaply."

**2-minute answer.** The general lesson: a status code is a category, not a diagnosis. Read the body (`QuotaFailure.violations[].quotaId`, `RetryInfo.retryDelay`) and honour what the server says. Then the capacity point: 20 requests/day means a 61-question run is impossible on the free tier, which is a billing decision, not a code fix.

**If they push — level 2.** *"How do you tell per-minute from per-day limits?"* The quotaId names it ("PerMinute" / "PerDay"), and the retry delay is seconds vs hours.

**If they push — level 3.** *"Why stop the whole run?"* Every further call would fail the same way. Stopping saves time and keeps the result honest: those rows are skipped, not wrong.

**If they push — level 4.** *"Client-side protection?"* A request budget per run and a token bucket at the provider's rate, so you know before starting whether the run fits the quota.

**Whiteboard it.**
```text
 429 RESOURCE_EXHAUSTED · quotaId …PerDay…-FreeTier · limit 20 · retry in 5h49m
 before: retried ×6 per call (hopeless)   after: fail fast → runner stops LLM calls → rows skipped
 rerun after reset: cached answers reused, only the rest paid
```

**Trap.** Retrying every 429 with backoff.

**Bridge.** "That's also the quota the full judged run hit."

---

## Phase 13 questions

### Q: Your dashboard shows traffic from a model you don't run in production. Debug.
**ID:** P13-05 · **Round:** backend screen  **Difficulty:** 2/5

**30-second answer.** "This happened: /stats counted requests from 'fake-extractive-1' and 'script-1', my test doubles. The API tests use the app's default database connection, so once request logging existed, test requests wrote to the real request_log. My first fix covered only one fixture; two other tests still wrote. The robust fix is an autouse fixture that disables request logging in every test, with the one logging test pointed at the throwaway test database. The polluted rows were deleted by their test-only model names."

**2-minute answer.** The general rule: side effects to shared systems (databases, queues, external APIs) must be opt-in in tests, not opt-out per test. A default-deny fixture is safer than remembering each time. Also check what telemetry records about tests, since it can mislead capacity and cost decisions.

**If they push — level 2.** *"Why not a separate DB for all API tests?"* The end-to-end test needs the real ingested corpus. Isolating writes is cheaper than duplicating it.

**If they push — level 3.** *"How would you have caught it sooner?"* A test asserting the real request_log is unchanged by the suite, or tagging rows with an environment.

**If they push — level 4.** *"Production analogue?"* Synthetic monitoring traffic mixed into business metrics. Tag it and filter it.

**Whiteboard it.**
```text
 test → app.connect() → real DB → request_log rows (fake-extractive-1, script-1)
 fix: autouse fixture request_log_enabled=False · logging test → test DB · delete polluted rows
```

**Trap.** Fixing one test at a time.

**Bridge.** "Telemetry is only useful if it's trustworthy."

---

### Q: Latency looked like 20 s per answer. The model is fast. What's going on?
**ID:** P13-06 · **Round:** ML screen · backend screen  **Difficulty:** 2/5

**30-second answer.** "Retries. Groq's free tier allows 8k tokens per minute per model; one answer sends ~1.5–2.8k. After three answers in a minute, calls get 429 with a Retry-After of 12–27 s, and my client retried inside the timed call, so the sleep showed up as 'time to first token'. Now each wait is reported as stage `llm.retry_wait`: one answer spent 16,000 of 16,771 ms waiting, and its model time was ~590 ms."

**2-minute answer.** Throughput, not latency, is the binding constraint: about 3 answers per minute on the free tier. The fixes are budget-side: a paid tier, fewer input tokens (smaller k, shorter headers), or client-side pacing with a token bucket so requests queue instead of bouncing.

**If they push — level 2.** *"Why retry at all?"* For an eval sweep, waiting beats failing. The cache keeps completed work.

**If they push — level 3.** *"Interactive users?"* Fail fast with a clear 503 rather than make a user wait 20 s. Interactive and batch callers can have different retry budgets.

**If they push — level 4.** *"Fairness?"* A shared token bucket per provider and model in front of all requests.

**Whiteboard it.**
```text
 8k TPM ÷ ~2.7k tokens/answer ≈ 3 answers/min
 answer 6411bb78: first_token 16,591 = retry_wait 16,000 + model ~590
```

**Trap.** Profiling the code when the time is spent sleeping.

**Bridge.** "That's the case for reporting retries as their own stage."
