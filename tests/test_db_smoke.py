"""Phase 0 smoke tests: the database the whole project depends on exists and
behaves exactly as docs/03-environment-and-infra.md says it does.

Every expected value here was computed by hand first (see the comments), so a
pass means "Postgres agrees with arithmetic", not "Postgres agrees with itself".
"""

import math

import psycopg
import pytest

from app.config import get_settings

PINNED_PGVECTOR = "0.8.7"


def scalar(conn, sql: str):
    return conn.execute(sql).fetchone()[0]


def test_server_is_postgres_16(conn):
    assert scalar(conn, "SHOW server_version").startswith("16.")


def test_pgvector_is_installed_at_the_pinned_version(conn):
    version = scalar(conn, "SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    assert version == PINNED_PGVECTOR


def test_l2_distance_matches_hand_calculation(conn):
    # sqrt((4-1)² + (5-2)² + (6-3)²) = sqrt(9 + 9 + 9) = sqrt(27) ≈ 5.196
    assert scalar(conn, "SELECT '[1,2,3]'::vector <-> '[4,5,6]'::vector") == pytest.approx(math.sqrt(27))


def test_cosine_distance_matches_hand_calculation(conn):
    # Perpendicular vectors: cosine similarity 0, so cosine distance 1 - 0 = 1.
    assert scalar(conn, "SELECT '[1,0]'::vector <=> '[0,1]'::vector") == pytest.approx(1.0)
    # Same direction, different length: similarity 1, distance 0. Cosine ignores length.
    assert scalar(conn, "SELECT '[1,2,3]'::vector <=> '[2,4,6]'::vector") == pytest.approx(0.0, abs=1e-6)


def test_inner_product_operator_returns_the_negative_dot_product(conn):
    # 1·4 + 2·5 + 3·6 = 32. pgvector returns -32 so that ORDER BY ... ASC
    # (smallest first) puts the LARGEST dot product first, like the other operators.
    assert scalar(conn, "SELECT '[1,2,3]'::vector <#> '[4,5,6]'::vector") == pytest.approx(-32.0)


def test_vectors_of_different_dimensions_are_rejected(conn):
    with pytest.raises(psycopg.errors.DataException, match="different vector dimensions 3 and 2"):
        scalar(conn, "SELECT '[1,2,3]'::vector <-> '[1,2]'::vector")


def test_english_full_text_search_stems_and_drops_stop_words(conn):
    # "The" and "were" are stop words (dropped); "runners" -> runner, "running" -> run.
    # The numbers are word positions, which phrase search uses later (Phase 6).
    assert scalar(conn, "SELECT to_tsvector('english', 'The runners were running')::text") == "'run':4 'runner':2"
    assert scalar(conn, "SELECT to_tsvector('english', 'The runners were running') @@ to_tsquery('english', 'run')")


def test_connections_identify_themselves(conn):
    name = scalar(conn, "SELECT application_name FROM pg_stat_activity WHERE pid = pg_backend_pid()")
    assert name == "rag-assistant"


def test_wrong_password_is_rejected():
    # The image trusts connections from *inside* the container without a password,
    # but ours arrive via Docker's port forward from the bridge network (172.x),
    # which hits the scram-sha-256 rule. This proves the port is not open to anyone.
    s = get_settings()
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        psycopg.connect(
            host=s.postgres_host,
            port=s.postgres_port,
            dbname=s.postgres_db,
            user=s.postgres_user,
            password=s.postgres_password + "-wrong",
            connect_timeout=5,
        )
