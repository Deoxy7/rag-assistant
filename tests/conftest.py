import psycopg
import pytest

from app.config import get_settings
from app.store.db import connect


@pytest.fixture(scope="session")
def conn():
    """One shared connection for the whole test session.

    autocommit=True: each statement is its own transaction, so a test that
    deliberately triggers an SQL error cannot leave the connection stuck in
    "current transaction is aborted" for every test that runs after it.

    If Postgres is unreachable we fail (not skip): a skipped DB test reads as
    green in CI while proving nothing.
    """
    s = get_settings()
    try:
        connection = connect(autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.fail(
            f"Cannot reach Postgres at {s.postgres_host}:{s.postgres_port}. "
            f"Start it with `make up`.\nDriver said: {exc}",
            pytrace=False,
        )
    yield connection
    connection.close()


TEST_DB = "rag_test"


@pytest.fixture(scope="session")
def test_db(conn):
    """A throwaway database with the schema applied, so tests never touch real data.

    Recreated once per test session (DROP … WITH (FORCE) disconnects stragglers).
    """
    from app.store.migrate import apply_migrations

    conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.execute(f"CREATE DATABASE {TEST_DB}")
    with connect(dbname=TEST_DB) as c:
        apply_migrations(c)
    return TEST_DB


@pytest.fixture
def db(test_db):
    """A fresh connection to the test database with every table emptied first (incl. the LLM cache)."""
    with connect(dbname=test_db) as c:
        c.execute("TRUNCATE documents, chunk_sets, llm_cache, request_log RESTART IDENTITY CASCADE")
        c.commit()
        yield c


@pytest.fixture(autouse=True)
def no_request_log_by_default(monkeypatch):
    """Tests never write to the real request_log (it feeds GET /stats); the one test that checks
    logging re-enables it and points it at the throwaway test database."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "request_log_enabled", False)
