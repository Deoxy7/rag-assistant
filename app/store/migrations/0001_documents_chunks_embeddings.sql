-- 0001: the core schema. Applied by app/store/migrate.py inside one transaction.
-- Every offset column indexes documents.canonical_text (see docs/08-database-schema.md).

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per filing. canonical_text is the parser's normalised text; every
-- page, block and chunk offset points into it.
CREATE TABLE documents (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_key         text        NOT NULL UNIQUE,          -- e.g. AMD_2021_10K
    company         text        NOT NULL,
    ticker          text        NOT NULL,
    fiscal_year     integer     NOT NULL,
    form            text        NOT NULL,
    source_sha256   char(64)    NOT NULL,                 -- hash of the PDF bytes
    parser_version  text        NOT NULL,
    page_count      integer     NOT NULL CHECK (page_count > 0),
    canonical_text  text        NOT NULL,
    ingested_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pages (
    document_id  bigint  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number  integer NOT NULL CHECK (page_number >= 1),
    char_start   integer NOT NULL,
    char_end     integer NOT NULL,
    width        real    NOT NULL,
    height       real    NOT NULL,
    region       text    NOT NULL CHECK (region IN ('body', 'after_signatures')),
    PRIMARY KEY (document_id, page_number),
    CHECK (char_start <= char_end)
);

-- Parser blocks, kept for citation highlighting (bbox) and section display.
CREATE TABLE blocks (
    document_id    bigint   NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    block_index    integer  NOT NULL,
    page_number    integer  NOT NULL,
    char_start     integer  NOT NULL,
    char_end       integer  NOT NULL,
    kind           text     NOT NULL CHECK (kind IN ('text', 'heading', 'table')),
    heading_level  smallint NOT NULL CHECK (heading_level BETWEEN 0 AND 3),
    section        text[]   NOT NULL,
    bbox           real[]   NOT NULL CHECK (cardinality(bbox) = 4),
    PRIMARY KEY (document_id, block_index),
    CHECK (char_start < char_end)
);

-- One row per chunking configuration, so every ablation configuration's
-- chunks can live side by side without re-ingesting.
CREATE TABLE chunk_sets (
    id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy       text    NOT NULL CHECK (strategy IN ('fixed', 'recursive', 'structure')),
    chunk_size     integer NOT NULL CHECK (chunk_size BETWEEN 1 AND 510),
    chunk_overlap  integer NOT NULL CHECK (chunk_overlap >= 0),
    tokenizer      text    NOT NULL,                     -- model@revision used to count tokens
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (strategy, chunk_size, chunk_overlap, tokenizer),
    CHECK (chunk_overlap < chunk_size)
);

CREATE TABLE chunks (
    id              bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_set_id    integer NOT NULL REFERENCES chunk_sets(id) ON DELETE CASCADE,
    document_id     bigint  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     integer NOT NULL,
    char_start      integer NOT NULL,
    char_end        integer NOT NULL,
    page_number     integer NOT NULL,
    page_end        integer NOT NULL,
    section         text[]  NOT NULL,
    token_count     integer NOT NULL CHECK (token_count BETWEEN 1 AND 510),
    text            text    NOT NULL,
    content_sha256  char(64) NOT NULL,                   -- hash of text: embedding cache key
    -- Postgres computes and stores this on every insert/update: the keyword index input.
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (chunk_set_id, document_id, chunk_index),
    CHECK (char_start < char_end),
    CHECK (page_number <= page_end)
);

-- GIN = inverted index over lexemes: lexeme → list of rows containing it.
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX chunks_set_document ON chunks (chunk_set_id, document_id);
CREATE INDEX chunks_content_sha256 ON chunks (content_sha256);

-- Vectors live in their own table, keyed by (chunk, model): one chunk can have
-- vectors from several embedding models (the dimension ablation) without
-- widening `chunks`. The column is an untyped `vector` so dimensions can differ;
-- HNSW indexes are created per (chunk_set, model) with a cast to the exact
-- dimension (see app/store/repository.py: ensure_hnsw_index).
CREATE TABLE embeddings (
    chunk_id      bigint  NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model         text    NOT NULL,                      -- model@revision
    chunk_set_id  integer NOT NULL,                      -- copied from chunks: lets a partial index target one set
    dims          integer NOT NULL CHECK (dims > 0),
    embedding     vector  NOT NULL,
    PRIMARY KEY (chunk_id, model),
    CHECK (vector_dims(embedding) = dims)
);
