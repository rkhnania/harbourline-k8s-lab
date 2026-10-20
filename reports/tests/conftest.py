"""Shared fixtures for the api tests.

IMPORT ORDER IS LOAD-BEARING. app.py reads every DB_* variable at module level,
so the environment has to be set BEFORE `import app` below. That is why the
import is not at the top of this file, and why a lint rule about import order
is suppressed on it. The proper fix is an application factory (create_app());
recorded as a recommendation rather than done here, because changing working
application code to suit its tests is a bigger decision than it looks.
"""
import os
import socket
import sys

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DB_HOST", os.getenv("TEST_DB_HOST", "localhost"))
os.environ.setdefault("DB_PORT", os.getenv("TEST_DB_PORT", "5432"))
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", os.getenv("TEST_DB_PASSWORD", "postgres"))
os.environ.setdefault("DB_NAME", "postgres")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as flask_app  # noqa: E402


@pytest.fixture
def client():
    flask_app.app.config.update(TESTING=True)
    return flask_app.app.test_client()


def _db_reachable() -> bool:
    try:
        with socket.create_connection(
            (os.environ["DB_HOST"], int(os.environ["DB_PORT"])), timeout=2
        ):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def shipments_table():
    """A real Postgres with a real schema and known rows.

    Deliberately NOT a mock. Mocking psycopg means the SQL in app.py never
    executes, so a renamed column or a typo'd query still passes - which is
    exactly the class of bug this suite exists to catch.

    Skips rather than fails when no database is reachable, so the unit tests
    still run on a laptop with nothing started.
    """
    if not _db_reachable():
        pytest.skip(f"no Postgres at {os.environ['DB_HOST']}:{os.environ['DB_PORT']}")

    import psycopg

    conninfo = (
        f"host={os.environ['DB_HOST']} port={os.environ['DB_PORT']} "
        f"user={os.environ['DB_USER']} password={os.environ['DB_PASSWORD']} "
        f"dbname={os.environ['DB_NAME']} connect_timeout=3"
    )
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS shipments "
                "(id int PRIMARY KEY, status text, carrier text)"
            )
            cur.execute("TRUNCATE shipments")
            cur.execute(
                "INSERT INTO shipments (id, status, carrier) VALUES "
                "(1, 'in_transit', 'DHL'), (2, 'delivered', 'DHL'), "
                "(3, 'delivered', 'Toll')"
            )
        conn.commit()
    yield
