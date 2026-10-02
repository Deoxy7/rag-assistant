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

## Phase 2

### T-014 · PepsiCo running header not removed — hit

- **Symptom:** `make parse` reported 0 header/footer blocks removed for both PepsiCo filings, though every body page starts with "Table of Contents".
- **Cause:** threshold "repeats on ≥30% of pages". The header is on 129 body pages; the PDF has 503 pages including exhibits, and 30% of 503 = 150.
- **Fix:** `max(5 pages, 10% of pages)`. PepsiCo now removes 129 per filing.

### T-015 · Verizon footers survive on 10 pages — hit

```text
FAILED tests/test_pdf_parser.py::test_verizon_running_header_removed - assert not True
```

- **Cause:** the footer is "Verizon 2022 Annual Report on Form 10-K 6" on even pages but "5 Verizon 2022 Annual Report on Form 10-K" on odd ones, and on 10 pages PyMuPDF merged the leading number into the block, so its fingerprint ("# Verizon # …") differed and fell below the threshold.
- **Fix:** `edge_key` also strips a leading or trailing `#`. Verizon 2022 removals 160 → 171.

### T-016 · Corning 2021 has 18 headings in 125 pages — hit

- **Cause:** PyMuPDF merged whole sections (running header, Item headings, body) into one block; the paragraph breaks are lines containing only a non-breaking space.
- **Fix:** split blocks at line level on blank lines, bold/normal changes and PART/ITEM lines. Corning 2021: 509 blocks / 18 headings → 1,429 / 169. Test: `test_blank_lines_split_a_merged_block`.

### T-017 · Table captions classified as headings — hit

- **Symptom:** section paths like `… › (In millions, except per share amounts)`.
- **Fix:** level-3 headings may not contain digits or start with "(". AMD 2021 headings 256 → 218.

### Removed after measuring: pdfplumber page pre-filter

Not an error, but logged because it was a measured reversal: skipping pdfplumber on pages without drawn lines saved ~2% (AMD 14.9 s vs 15.2 s) for identical output, because 118/118 AMD pages and 213/215 Boeing pages draw something. The rule was deleted.

## Phase 3

### T-018 · A 256-token window measures 257 — hit

- **Cause:** windows were cut at arbitrary WordPiece tokens; one started at a `##` continuation piece, and the slice re-tokenized into different pieces.
- **Fix:** `word_groups` groups tokens with contiguous character spans into whole words; windows are cut only between words. Test: `test_windows_never_exceed_size_and_overlap_repeats_words`.

### T-019 · LangChain `start_index` = -1 — hit

```text
ValueError: AMD_2021_10K: LangChain start_index -1 does not match chunk 1
```

- **Cause:** langchain-text-splitters 1.1.2 computes `offset = index + previous_chunk_len - self._chunk_overlap` and `text.find(chunk, max(0, offset))`; `chunk_overlap` is in our length unit (tokens) but is subtracted from a character position, so the search starts after the true chunk start.
- **Fix:** don't use `add_start_index`; locate each chunk with `doc.text.find(text, previous_start + 1)` and verify. Test: `test_langchain_start_index_is_wrong_for_token_lengths_and_ours_is_right` (also fails if LangChain fixes it, prompting a review).

### T-020 · Size-512 chunks would be truncated — hit

- **Symptom:** corpus run at size 512 produced chunks of 511–512 content tokens (p95 512, max 512).
- **Cause:** bge-small's 512 includes `[CLS]` and `[SEP]`.
- **Fix:** `get_chunker` rejects sizes above `embedding_max_tokens - 2` (510); the ablation's top size is 510.

### T-021 · Structure chunks of 4–6 tokens — hit

- **Cause:** every heading started a new chunk, so "PART II" and "ITEM 5…" became chunks on their own.
- **Fix:** a heading or new section closes the current chunk only if it already holds body text. 5th-percentile chunk at 256: 5 → 19 tokens.

## Phase 4

### T-022 · Second chunk set got id 3 — hit

- **Cause:** `INSERT … ON CONFLICT DO NOTHING` on the idempotent re-run reserved identity value 2 before detecting the conflict; identity values are never returned.
- **Fix:** `get_or_create_chunk_set` selects first and inserts only if missing. Test: `test_chunk_set_ids_are_not_burned_by_reruns` (ids 1, 1, 1, 2).

### T-023 · Layering test caught store importing ingest — hit

```text
AssertionError: forbidden imports: app/store/repository.py: store -> ingest
```

- **Cause:** `repository.py` imported `Chunk` and `ParsedDocument` for type hints.
- **Fix:** the repository accepts objects by shape (documented fields) instead of importing the ingest layer's types. The Phase 0 architecture test did its job on the first real violation.

### T-024 · Store tests encoded wrong assumptions — hit

- **Symptoms:** `assert 12 == 24` (FTS matches), `assert 0 > 0` (cross-set reuse), `IndexError` in the test helper, `assert 7 == 12` (dedup).
- **Cause:** test expectations, not code: tail windows of split paragraphs don't contain "revenue"; recursive and structure chunks of the synthetic text never coincide; the helper assumed ≥4 paragraphs; and identical tail windows inside one document are deduplicated too.
- **Fix:** assertions compare against what the database actually contains (`count(*) FILTER (WHERE text ILIKE …)`, `count(DISTINCT content_sha256)`), and the reuse test uses an overlap-only change, which yields identical chunks by construction.

## Phase 5

### T-025 · HNSW settings leak between searches — hit

- **Symptom:** a "post-filter" benchmark returned 10 rows with recall 1.0; the same experiment in a fresh script returned 3.8 rows.
- **Cause:** `SET LOCAL` lasts until the end of the *top-level* transaction; psycopg's `conn.transaction()` inside an already-open transaction is only a savepoint. An earlier iterative search left `hnsw.iterative_scan = relaxed_order` on for later searches.
- **Fix:** `VectorRetriever.search` sets both `hnsw.ef_search` and `hnsw.iterative_scan` on every call. Test `test_settings_do_not_leak_between_searches` fails on the old code with `assert 'relaxed_order' == 'off'`.

### T-026 · Planner settings ignored by a cached plan — hit

- **Symptom:** after the leak fix, the benchmark still showed 10 rows; bisecting showed it flipped only after the retriever had run the same query 50 times.
- **Cause:** psycopg server-side-prepares a query after 5 executions (`prepare_threshold`); Postgres caches the plan, and planner settings like `enable_sort` don't re-plan it. (`pg_prepared_statements` showed 3 statements.)
- **Fix:** the forced-path experiment uses its own connection with `prepare_threshold = None`. Executor settings (`hnsw.ef_search`) are unaffected.

### T-027 · Quantisation benchmark inherited ef_search — hit

- **Symptom:** the float32 row showed recall 0.996 one run and 0.928 another.
- **Cause:** raw benchmark queries didn't set `hnsw.ef_search`, so they used whatever an earlier search left (T-025 again).
- **Fix:** each quantisation query sets `ef_search = 40` explicitly.

## Phase 6

### T-028 · Keyword search matches nothing for natural questions — hit

- **Symptom:** "What was AMD's net revenue in 2021?" → 1 match; a long FinanceBench question → 0.
- **Cause:** `plainto_tsquery` ANDs every lexeme.
- **Fix:** OR the lexemes (`replace(plainto_tsquery(...)::text, '&', '|')::tsquery`); 2,808 candidates, ranked.

### T-029 · FinanceBench evidence field name differs from its README — hit

```text
KeyError: 'evidence_doc_name'
```

- **Cause:** the README documents `evidence_doc_name`; the actual JSONL uses `doc_name` inside each evidence entry.
- **Fix:** read `e["doc_name"]`; note in `scripts/bench_keyword.py`.

### T-030 · Wrong attribution of a ranking failure — hit (in my own analysis)

- **What happened:** the subsidiary-list result for "goodwill impairment Corning" was first blamed on `ts_rank` lacking IDF, and BM25 was made the default to fix it.
- **Check that caught it:** running all three functions on the same query: `ts_rank` → goodwill note, `ts_rank_cd` → subsidiary list, BM25 → goodwill note. The first comparison had silently used `ts_rank_cd` (the early default).
- **Fix:** default changed to `ts_rank` (also better on FinanceBench 4 vs 2 of 28 and 2.3× faster); BM25 kept as an ablation option; test `test_cover_density_is_fooled_by_repetition_but_ts_rank_and_bm25_are_not` pins the behaviour.

### T-031 · Migration test hard-coded the migration list — hit (Phase 6)

- **Symptom:** after adding `0002_text_stats.sql`, `test_migrations_are_recorded_and_idempotent` failed: it expected exactly `['0001_documents_chunks_embeddings']`.
- **Cause:** the test listed migration names by hand, so every new migration broke it.
- **Fix:** the test compares `schema_migrations` against the `.sql` files on disk.

## Phase 7

### T-032 · Weighted fusion zeroed out single-hit lists — hit (my bug)

- **Symptom:** `make bench-hybrid` showed weighted fusion at α_vec = 0.3 finding 20 of 50 exact figures in the top 5, while keyword search alone found 50. The fusion was worse than one of its own inputs.
- **Cause:** min-max normalisation was written `(s - lo) / ((hi - lo) or 1.0)`. For a list with one hit, lo = hi, so the hit scored 0 / 1 = 0. Rare figures are usually matched by one keyword chunk.
- **Fix:** if `hi > lo` normalise, else every hit counts 1.0. Test `test_weighted_fusion_single_hit_list_counts_as_its_best`. After the fix, α_vec = 0.3 found 49 of 50. Doc 11 and card #22 were rewritten: weighted fusion at α = 0.5 is competitive with RRF, not "worse at every weight".

## Phase 8

### T-033 · Benchmark on CPU made no progress when run in the background — hit, cause not certain

- **Symptom:** `bench_rerank.py --device cpu`, started as a background job, printed its first line and then nothing for 25+ minutes. A faulthandler stack dump (`kill -ABRT`) showed it inside the cross-encoder's attention (`sdpa_attention`), computing, not deadlocked.
- **What I checked:** the same CPU scoring in a foreground script took ~165 ms per 10 pairs, including with the MPS embedder and a Postgres connection open in the same process, and over all 78 queries (p50 169 ms). The identical bench command in the foreground finished in about 2 minutes.
- **Cause:** I'm not sure. The likeliest explanation is that macOS ran the background process at a low quality-of-service level (efficiency cores, throttled), which hits CPU-bound work hardest.
- **Fix / rule:** run benchmarks in the foreground. Treat latency numbers from background runs as invalid.

### T-034 · bge-reranker-base download looked like a hang — not an error

- **Symptom:** the first `get_reranker("BAAI/bge-reranker-base", …)` took 66 s.
- **Cause:** a 1.1 GB first download into `data/models`. Later loads are local.
- **Note:** MiniLM is 91 MB; the default setup downloads only it.

## Phase 9

### T-035 · Claim flagged uncited although "[1]" follows it — hit (my bug)

- **Symptom:** the fake model's first answer, "…$16.4 billion. [1]", was reported with 1 uncited sentence.
- **Cause:** the sentence splitter cuts after ". ", so "[1]" became the start of the next fragment. My first fix (merge marker-only fragments into the previous sentence) handled "[1]" alone but not "[1] Margin was…".
- **Fix:** before splitting, move markers that follow a full stop to before it (`TRAILING_MARKERS`). Test `test_marker_after_the_period_belongs_to_the_sentence` covers both forms.

### T-036 · Mocked OpenAI stream raised "content event … before receiving its output item" — hit (test fixture)

```text
RuntimeError: Received a content event for output index 0 before receiving its output item
```

- **Cause:** my SSE mock sent `response.created` then text deltas directly. The SDK's stream accumulator needs `response.output_item.added` and `response.content_part.added` first, as the real API sends.
- **Fix:** the mock sends the full event sequence. Lesson: mocks must follow the real protocol, or they test nothing.

### T-037 · No OPENAI_API_KEY during Phase 9 — expected, not an error

- **Symptom:** `make ask` → `error: LLM_PROVIDER=openai but OPENAI_API_KEY is empty…`
- **Fix:** add the key to `.env` (never commit it), or `ARGS="--provider fake"` for the labelled offline fake. Real-model numbers in docs 13 and up say *not yet measured* until then.

## Phase 10

### T-038 · Valid API key, but every generation fails with 429 — hit

```text
openai.RateLimitError: Error code: 429 - {'error': {'message': 'You have no credits remaining. Add credits to continue
using the API at https://platform.openai.com/settings/organization/billing/.', 'type': 'insufficient_quota',
'param': None, 'code': 'credit_balance_exhausted'}}
```

- **Context:** an `OPENAI_API_KEY` appeared in `.env` during Phase 10. The free models endpoint accepted it and listed `gpt-6-luna`.
- **Cause:** the account had no credits. OpenAI uses HTTP 429 for both rate limits and an empty balance.
- **Bug it exposed:** the API mapped every 429 to `llm_rate_limited` ("retry later"), which never helps an empty balance.
- **Fix:** `quota_exhausted()` checks the body's code/type, so an empty balance gives `503 llm_quota_exhausted` ("add credits"). `scripts/ask.py` prints the error code instead of a traceback. Test: `test_empty_balance_is_not_reported_as_a_rate_limit`.
- **Still needed:** credits on the OpenAI account (only the account owner can add them). Real-model numbers stay *not yet measured* until then.

### T-039 · `TypeError: 'EventSourceResponse' object is not iterable` — hit

- **Cause:** the route was declared with `response_class=EventSourceResponse`. FastAPI then treats the endpoint as a `yield` generator and iterates its return value, but it returned a ready `EventSourceResponse`.
- **Fix:** declare `response_class=StreamingResponse` (with `text/event-stream` documented under `responses`) and return the response. That keeps pre-stream checks as normal JSON errors.

### T-040 · Expected 503 also logged as "Exception in ASGI application" — hit

- **Symptom:** in tests, the missing-key request raised although the handler had produced the right 503 body.
- **Cause:** handlers registered for the base `Exception` run in Starlette's outermost `ServerErrorMiddleware`, which re-raises after responding (so servers log a crash).
- **Fix:** register handlers for the expected types (`MissingAPIKey`, `openai.APIError`, `psycopg.OperationalError`). The catch-all stays only for genuinely unexpected errors.

### T-041 · `/health` showed `gpt-6-luna` while the fake model answered — hit

- **Cause:** health reported the configured `llm_model` setting, not the active client.
- **Fix:** report `get_llm().model` when the client is ready.

## Phase 11

### T-042 · Keyword search returned nothing for a question containing a figure — hit (my bug, Phase 6 code)

- **Symptom:** golden question G038, "What does the figure $404,381 represent in Boeing's FY2022 10-K?", got 0 keyword hits; the hybrid list was vector-only.
- **Cause:** `tsquery = phrases && (any other word)`. The backlog table contains `404 <-> 381` but none of figur / repres / boe / fy2022.
- **Fix:** match on the phrases alone; rank with `phrases || words`. Test `test_a_required_figure_matches_even_when_no_other_question_word_does`. Golden hit@5 0.692 → 0.731. The Phase 6/7 benches were re-run and are unchanged (bare-figure queries). Doc 10 §5 corrected.

### T-043 · Label-edit script crashed with IndexError — hit (my mistake)

- **Symptom:** `IndexError: list index out of range` while adding alternatives; a misleadingly named result (`baseline-labels-audited`, run on unchanged labels) had already been written.
- **Cause:** I misremembered two question ids (117,100 is G043/G052, not G052/G053; G053 is unanswerable).
- **Fix:** deleted that just-created result pair, and re-ran the edit with an assertion that each id's question text contains an expected phrase. Lesson: check identity, not position, before editing labels.

### T-044 · Accuracy-optimal refusal threshold refuses nothing — not a bug

- **Symptom:** the first summary's "best threshold" had 0 refusals.
- **Cause:** 52 answerable vs 9 unanswerable: never refusing is 85% accurate.
- **Fix:** report operating points (catch ≥ ⅓, ⅔, all) with their false-refusal rates.

## Provider switch to Gemini (2026-10-02, between Phases 11 and 12)

### T-045 · Responses API returns 404 on Gemini's OpenAI-compatible endpoint — hit

```text
responses API: NotFoundError 404 Error code: 404
```

- **Cause:** `https://generativelanguage.googleapis.com/v1beta/openai/` serves Chat Completions, models and embeddings, but not OpenAI's Responses API, which the Phase 9 client used.
- **Fix:** the client (`ChatClient`) uses `chat.completions`, which works on both providers.

### T-046 · Answer cut to "1": thinking tokens used up max_tokens — hit

```text
gemini-3.5-flash  effort=None  finish=length  text='1'  completion=1  total=68
gemini-3.5-flash  effort=none  finish=stop    text='1, 2, 3, 4, 5'  completion=13  total=25
```

- **Cause:** Gemini 3.x Flash spends hidden "thinking" tokens out of `max_tokens` (prompt 12 + completion 1 = 13 of a total of 68). The usage object doesn't break the thinking tokens out separately.
- **Fix:** `LLM_MAX_OUTPUT_TOKENS=2048`, `LLM_REASONING_EFFORT` as a setting, and `finish_reason` kept on every result (and in the cache, migration 0004), so a `"length"` stop is flagged `truncated` in the API and counted by the eval runner.

### T-047 · Listed models that don't answer: 503 "high demand" and 404 "no longer available" — hit

- **Symptom:** `gemini-3.8-flash` and `gemini-3.7-flash` → `InternalServerError 503 'This model is currently experiencing high demand'`; `gemini-2.5-flash` / `-lite` → `NotFoundError 404 'no longer available to new users'`. All appeared in `models.list()`. The first probe also hit a 60 s read timeout on `gemini-3.8-flash`.
- **Fix:** probe before choosing (`gemini-3.5-flash` and `-flash-lite` answered); retries with backoff for transient 5xx. A later single call to `gemini-3.8-flash` succeeded after 17 s, so its 503s were transient.

### T-048 · Flash-Lite rejects reasoning_effort="none" — hit

```text
gemini-3.5-flash-lite effort=none BadRequestError 400 Error code: 400 - [{'error': {'code': 400, 'message': 'Request contains an invalid argument.', 'status': 'INVALID_ARGUMENT'…
```

- **Fix:** the judge sends no reasoning parameter (`LLM_JUDGE_REASONING_EFFORT` unset). "OpenAI-compatible" covers the common subset, not every parameter value.

### T-049 · `.env.example` had been reduced to one line, and I committed it — hit (found late)

- **Symptom:** while adding the Gemini settings, `.env.example` contained only `OPENAI_API_KEY=`. The Phase 0 template (Postgres settings that `make up` copies to `.env`) was gone.
- **Cause:** the file was overwritten outside my edits before Phase 9. My Phase 9 script saw the key already present, skipped its edit, and I committed the shrunken file without reading it.
- **Fix:** restored the Phase 0 block from git history (`git show 316087f:.env.example`) and added the LLM section. A fresh clone would otherwise have started without database settings.

### T-050 · Test saw another test's cached LLM response — hit

- **Cause:** the `db` fixture truncated documents and chunk sets, but not `llm_cache`, so two tests using the same (provider, model, prompt) shared a cached answer.
- **Fix:** the fixture also truncates `llm_cache`.

### T-051 · `LLM_BASE_URL=` (empty) parsed as the URL "" — hit

- **Cause:** pydantic keeps empty strings, and the OpenAI SDK only falls back to its default URL for `None`.
- **Fix:** a validator turns blank optional LLM settings into `None` (`test_blank_optional_llm_settings_mean_unset`).

## Phase 12

### T-052 · Judged eval stalled on 429 retries: Gemini free-tier *daily* quota — hit

```text
LLM call failed (RateLimitError 429); retry 5/6 in …
429 RESOURCE_EXHAUSTED: Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests,
limit: 20, model: gemini-3.5-flash … Please retry in 5h49m5.47s.
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

- **Symptom:** the first 20-question batch of the full judged run did 3 questions in 10 minutes, with 59 retries logged.
- **Cause:** the free tier allows 20 `gemini-3.5-flash` requests per day per model (Flash-Lite has its own quota and kept working). My retry policy treated every non-balance 429 as transient.
- **Fix:** `quota_exhausted()` recognises `PerDay` quota violations; `with_retries` gives up when the server's requested delay (RetryInfo, Retry-After or "retry in 5h49m") exceeds the 30 s cap; `eval.run` stops calling the LLM after a quota error and marks the rest `skipped`; the API's message names the reset time. Tests use the real error body.
- **Still needed:** a full 61-question judged run needs 61 Flash requests. That means billing on the Google AI project (only the account owner can enable it), or about 4 days of free quota.

### T-053 · `pipeline.py: error: argument --size: expected one argument` — hit

- **Cause:** a zsh loop did `set -- $cfg` to split "structure 128 16". zsh doesn't word-split unquoted variables, so `--size` got nothing.
- **Fix:** a shell function with explicit positional arguments (`ing structure 128 16`).

### T-054 · Every Gemini model returned HTTP 402 "prepayment credits are depleted" — hit

```text
APIStatusError: Error code: 402 - [{'error': {'code': 402, 'message': 'Your prepayment credits are depleted. Please go to AI Studio at https://ai.studio/projects to manage your project and billing.…
```

- **Context:** after switching the generator to `gemini-3.5-flash-lite`, all Gemini models (3.5 Flash, 3.5 Flash-Lite, 3.1 Flash-Lite) returned 402. A billing state on the AI Studio project; only the account owner can change it.
- **Bug it exposed:** 402 wasn't treated as a quota, so the runner called Gemini once per question and recorded six errors.
- **Fix:** `quota_exhausted()` treats HTTP 402 as exhausted (the run stops, the API answers `503 llm_quota_exhausted`). Following the user's decision, generation moved to Groq (`qwen/qwen3.8-27b`) with the judge on a separate provider setting (`openai/gpt-oss-120b`).

### T-055 · Refusals counted as wrong answers: the token wasn't alone — hit (measurement bug)

```text
'…none include an employee headcount.\n\nINSUFFICIENT_CONTEXT'      '[INSUFFICIENT_CONTEXT]'
```

- **Symptom:** in the first full judged run, 4 RAG answers and 4 closed-book answers explained first and then wrote the token, or bracketed it. `is_refusal` only accepted the bare token, so they were scored as answers (correctness 0, faithfulness 0).
- **Effect:** before the fix, RAG faithfulness was 0.859 and false refusals 15%; after it, 0.923 and 23%. Correctness was unchanged at 0.721, since these were 0 either way.
- **Fix:** the token anywhere as a whole word, in a response with no citation markers, is a refusal; a stray token next to a cited answer is removed from the displayed text. Tests cover both forms and the near-miss "INSUFFICIENT_CONTEXTUAL".
