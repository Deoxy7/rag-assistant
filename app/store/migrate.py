"""Apply SQL migrations in order, each exactly once.

    python -m app.store.migrate

Migrations are numbered files in app/store/migrations/. Applied ones are
recorded in schema_migrations, so running this twice is harmless. Each file
runs in its own transaction: it either fully applies or leaves no trace.
"""

import sys
from pathlib import Path

import psycopg

from app.store.db import connect

MIGRATIONS = Path(__file__).parent / "migrations"


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations on an open (non-autocommit) connection; return their names."""
    with conn.transaction():
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                            name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())""")
    applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    done = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        done.append(path.name)
    return done


def main() -> int:
    with connect() as conn:
        done = apply_migrations(conn)
    print("applied: " + ", ".join(done) if done else "schema up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
