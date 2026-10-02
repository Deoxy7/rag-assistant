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
