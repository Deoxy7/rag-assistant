-- Runs ONCE, only when the database volume is empty (the very first `make up`,
-- or the first `make up` after `make db-reset`). Postgres' official image runs
-- every *.sql file in /docker-entrypoint-initdb.d at initialisation time and
-- never again — so editing this file later does nothing to an existing volume.
--
-- pgvector ships inside the image but, like every Postgres extension, it must be
-- switched on per database before the `vector` type and its operators exist.
CREATE EXTENSION IF NOT EXISTS vector;
