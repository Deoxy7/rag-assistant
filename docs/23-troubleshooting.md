# 23 — Troubleshooting log

**Status:** started in Phase 0 (2026-10-02); every error hit during the build is appended the day it happens. This is a log, so it does not use the 13-section skeleton.

Only real errors go here. Each entry says whether it was **hit** (happened while building) or **reproduced** (triggered on purpose to document a failure mode), with the exact text, the cause and the fix.

---

## Phase 0

### T-001 · `docker pull` fails with a TLS handshake timeout — hit

```text
failed to do request: Get "https://registry-1.docker.io/v2/pgvector/pgvector/referrers/sha256:8549d023844392f0f25dfcfe9712714d2d6a8ad52eebe37b3b15ed7fbd564bfc": net/http: TLS handshake timeout
```

- **When:** first `docker pull pgvector/pgvector:0.8.7-pg16-bookworm`, after all layers had already downloaded (1 min 17 s in).
- **Cause:** a slow network. The request that timed out went to the registry's `referrers` endpoint, after the image layers. I'm not certain what Docker needs that endpoint for here; it appears to be the registry API for artefacts attached to an image, such as signatures or attestations.
- **Fix:** retry. The second pull reused the downloaded layers and succeeded (`Digest: sha256:7b822b0a…`).
- **Prevention:** in CI, pull through a registry mirror or cache and retry with backoff.

### T-002 · `mmdc` rejects `-w` — hit

```text
error: unknown option '-w'
```

- **When:** first `bash scripts/render_diagrams.sh`; all six PNG renders failed, all SVGs succeeded.
- **Cause:** the plan specified `-w 1800`, but mermaid-cli 12.0.0 removed `-w/--width`. `mmdc --help` lists `--size <size>` instead ("attempt to create a PNG with a maximum height or width equal to the given size").
- **Fix:** `--size 1800 -s 2` in `scripts/render_diagrams.sh`. The script failed loudly (exit 1, renderer output printed) instead of leaving half-rendered output — the behaviour it was built for.

### T-003 · Architecture diagram renders 3600 × 474 px and is unreadable — hit

- **When:** first successful render of `02-system-architecture.mmd`, written as `flowchart LR`.
- **Cause:** sixteen nodes in two left-to-right chains produced one very wide, very short image; at 50% zoom the labels were illegible. The legend also wrapped mid-phrase because Mermaid wraps labels at a default width.
- **Fix:** switched to `flowchart TB` (result 1488 × 3598 px, readable), set `"wrappingWidth": 320` in `scripts/mermaid-config.json`, and put explicit `<br/>` breaks in legend labels. Rule kept: look at every rendered PNG before embedding it.

### T-004 · Changed `POSTGRES_PASSWORD`, container healthy, every login fails — reproduced

```text
connection failed: connection to server at "127.0.0.1", port 5432 failed: FATAL:  password authentication failed for user "rag"
```

- **Cause:** the Postgres image applies `POSTGRES_PASSWORD` only when it initialises an empty volume. Afterwards the password lives in the database, so editing `.env` changes what the *client* sends but not what the *server* expects. Nothing warns you: the container still reports `(healthy)`.
- **Fix:** restore the old value in `.env`, or `make db-reset` (deletes all data) then `make up`, or `ALTER ROLE rag PASSWORD '…'` inside `make psql` and then update `.env`.

### T-005 · `InFailedSqlTransaction` after an expected error — reproduced

```text
first error : DataException - different vector dimensions 3 and 2
next query  : InFailedSqlTransaction - current transaction is aborted, commands ignored until end of transaction block
```

- **Cause:** with autocommit off, psycopg runs every statement inside one open transaction; after an error Postgres rejects the rest of that transaction.
- **Fix:** the shared test connection uses `autocommit=True` (`tests/conftest.py`). In application code, roll back after an error.

### T-006 · Port 5432 already in use — reproduced

```text
docker: Error response from daemon: failed to set up container networking: driver failed programming external connectivity on endpoint portclash (…): Bind for 127.0.0.1:5432 failed: port is already allocated
```

- **Cause:** something else is already listening on that address and port.
- **Fix:** find it with `lsof -nP -iTCP:5432 -sTCP:LISTEN` and stop it, or set `POSTGRES_PORT=5433` in `.env` (both Compose and the app read it).

### T-007 · Docker not running — reproduced

```text
Docker is not running. Start it with: colima start
make: *** [up] Error 1
```

Raw Docker message behind it:

```text
failed to connect to the docker API at unix:///var/run/docker.sock; check if the path is correct and if the daemon is running: dial unix /var/run/docker.sock: connect: no such file or directory
```

- **Cause:** the Colima VM (and so the Docker engine) was stopped — after a reboot, for example.
- **Fix:** `colima start` (44 s measured on a warm machine), then `make up`.

### T-008 · `colima start` appears to hang for 13 minutes — hit (not an error)

- **What happened:** the first `colima start` printed nothing for over ten minutes, because its output was piped through `tail`.
- **Cause:** it was downloading the VM image (`~/Library/Caches/colima` grew to 320 MB) over a slow connection. Total: 13 min 17 s. Later starts take 44 s.
- **How to tell it's working:** `du -sh ~/Library/Caches/colima` keeps growing, and `ps aux | grep colima` shows the process alive.

### T-009 · Card collector counts a marker mentioned in prose — hit

```text
ValueError: 03-environment-and-infra.md: 5 card:start marker(s) but 4 complete card(s)
```

- **When:** first `python scripts/collect_cards.py` after writing doc 03.
- **Cause:** doc 03 *mentions* the marker syntax inline (in backticks) while explaining the tooling, and the start-marker regex matched anywhere in a line.
- **Fix:** both regexes in `scripts/collect_cards.py` now match only a marker standing alone on its own line (`^…$` with `re.MULTILINE`); `tests/test_tooling.py::test_marker_mentioned_inline_is_not_a_card` locks it in. The count check that raised the error is what caught it — without it, the collector would have silently mis-paired cards.

### T-010 · Mirrored cards link to the wrong `PROGRESS.md` — hit

```text
AssertionError: 09-tradeoff-cards.md links to a missing file: ../PROGRESS.md
```

- **When:** first `make docs`.
- **Cause:** `rewrite_links` in `scripts/collect_cards.py` prefixed `../` to relative links when copying a card from `docs/` into `docs/interview/`, but skipped targets that *already* started with `../` — so `../PROGRESS.md` (repo root, seen from `docs/`) stayed `../PROGRESS.md`, which from `docs/interview/` points at a non-existent `docs/PROGRESS.md`.
- **Fix:** every relative target gets the extra `../`; only absolute URLs, `mailto:`, `#anchors` and `/`-rooted paths are left alone. Covered by `test_rewrite_links_prefixes_relative_targets_only_outside_code`.
- **Same run, second issue:** the 100-column check scanned *all* `<details>` content, so prose answers in "Check yourself" blocks failed it. The rule is about ASCII diagrams, so the test now checks only the `text` code blocks inside `<details>`.

## Phase 1

### T-011 · `CERTIFICATE_VERIFY_FAILED` downloading the corpus — hit

```text
urllib.error.URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1006)>
```

- **Cause:** the python.org build of Python 3.11 on macOS has no CA bundle: `ssl.get_default_verify_paths().openssl_cafile` is `/Library/Frameworks/Python.framework/Versions/3.11/etc/openssl/cert.pem`, which does not exist.
- **Fix:** `scripts/fetch_corpus.py` builds its SSL context from `certifi.where()` (certifi pinned in `requirements.txt`). Not chosen: running Python's "Install Certificates" script (changes the system install) or disabling verification (never).

### T-012 · Signature page detected on page 2 — hit

- **Symptom:** the first inspection run reported Boeing's signatures on p.2 and Verizon's on p.3, so almost all of Boeing looked like exhibits.
- **Cause:** the regex matched a line reading just "Signatures" — which is also an entry in the table of contents.
- **Fix:** match the legal sentence on the real page ("Pursuant to the requirements of Section 13…"). A first fix requiring "Section 13 or 15(d)" failed on Boeing, which omits "or 15(d)", so only the common prefix is matched. Synthetic test: `test_signature_page_uses_the_legal_statement_not_the_word`.

### T-013 · "After the signatures" is not "exhibits" — hit (analysis error caught before it mattered)

- **Symptom:** Corning 2021 showed 65 of 125 pages "after signatures" — implausible for exhibits alone.
- **Cause:** Corning places its financial statements after the signature page (income statement p.65, signatures p.60).
- **Fix:** the inspection reports `pages_after_signatures` and whether the income statement comes before or after; no page is ever dropped by position. Test: `test_corning_puts_financial_statements_after_the_signatures`.
