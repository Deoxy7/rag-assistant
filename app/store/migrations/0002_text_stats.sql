-- 0002: corpus statistics for BM25 ranking (app/retrieve/keyword.py).
-- Postgres' ts_rank has no IDF (inverse document frequency): a word that
-- appears in every chunk counts as much as a rare one. BM25 needs, per chunk
-- set, how many chunks contain each lexeme (df), the number of chunks (n) and
-- the average chunk length. Refreshed by the ingest pipeline after inserting chunks.

CREATE TABLE lexeme_stats (
    chunk_set_id  integer NOT NULL REFERENCES chunk_sets(id) ON DELETE CASCADE,
    lexeme        text    NOT NULL,
    df            integer NOT NULL CHECK (df > 0),       -- chunks containing the lexeme
    PRIMARY KEY (chunk_set_id, lexeme)
);

CREATE TABLE chunk_set_stats (
    chunk_set_id  integer PRIMARY KEY REFERENCES chunk_sets(id) ON DELETE CASCADE,
    n_chunks      integer NOT NULL CHECK (n_chunks > 0),
    avg_length    real    NOT NULL CHECK (avg_length > 0) -- mean distinct lexemes per chunk
);
