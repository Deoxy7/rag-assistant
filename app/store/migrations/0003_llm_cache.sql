-- 0003: cache of LLM responses (decision D). A response is stored under the
-- sha256 of everything that determines it: provider, model, instructions,
-- input and generation parameters. Re-running an eval with the same prompts
-- then costs nothing and returns identical text, so metric changes come from
-- code changes, not from sampling noise or a re-billed call.

CREATE TABLE llm_cache (
    key            text PRIMARY KEY CHECK (length(key) = 64),   -- sha256 hex
    provider       text        NOT NULL,                        -- "openai" | "fake"
    model          text        NOT NULL,
    response_text  text        NOT NULL,
    input_tokens   integer     NOT NULL CHECK (input_tokens >= 0),
    output_tokens  integer     NOT NULL CHECK (output_tokens >= 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    hits           integer     NOT NULL DEFAULT 0               -- times served from cache
);
