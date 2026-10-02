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
