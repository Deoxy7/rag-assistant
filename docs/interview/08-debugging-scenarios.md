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
