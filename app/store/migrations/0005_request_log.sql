-- 0005: one row per answered request (POST /query and /query/stream), for GET /stats.
-- The question text is NOT stored (it can contain personal data): only its sha256
-- and length, enough to spot repeated questions and size outliers.

CREATE TABLE request_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts              timestamptz NOT NULL DEFAULT now(),
    request_id      text        NOT NULL,
    endpoint        text        NOT NULL,                  -- "/query" | "/query/stream"
    status          integer     NOT NULL,                  -- HTTP status (200, or the error's)
    error           text,                                  -- error code from the envelope, if any
    question_sha256 char(64),
    question_chars  integer,
    provider        text,
    model           text,
    input_tokens    integer     NOT NULL DEFAULT 0,
    output_tokens   integer     NOT NULL DEFAULT 0,
    cached          boolean     NOT NULL DEFAULT false,
    refused         boolean,
    truncated       boolean     NOT NULL DEFAULT false,
    list_usd        double precision NOT NULL DEFAULT 0,  -- at the provider's paid list price
    billed_usd      double precision NOT NULL DEFAULT 0,  -- actually billed (0 on a free tier)
    total_ms        double precision NOT NULL,
    timings_ms      jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- per stage: retrieve.vector, rerank, generate, …
    counters        jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX request_log_ts ON request_log (ts);
