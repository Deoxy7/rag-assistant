"""Database connections.

Phase 0 needs one connection at a time (tests, scripts). A connection pool is
added in Phase 10, when the API serves concurrent requests.
"""

import psycopg

from app.config import get_settings


def connect(**kwargs) -> psycopg.Connection:
    """Open a new connection to the project database.

    Connection details are passed as keyword arguments rather than built into a
    postgresql:// URL: a password containing '@', ':' or '/' would silently break
    a URL unless percent-encoded, while keyword arguments need no escaping.
    """
    s = get_settings()
    return psycopg.connect(
        host=s.postgres_host,
        port=s.postgres_port,
        dbname=s.postgres_db,
        user=s.postgres_user,
        password=s.postgres_password,
        # Fail in 5 s instead of hanging when the container is down.
        connect_timeout=5,
        # Shows up in pg_stat_activity, so you can tell our sessions apart.
        application_name="rag-assistant",
        **kwargs,
    )
