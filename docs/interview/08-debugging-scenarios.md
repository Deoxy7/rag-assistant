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
