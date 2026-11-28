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
            _apply_schema(cur)
            cur.execute("TRUNCATE shipments")
            # Text ids: what the real schema declares. The fixture said `id int`
            # until 28 Nov, so the suite proved things about a database no
            # deployment had.
            cur.execute(
                "INSERT INTO shipments (id, status, carrier) VALUES "
                "('1', 'in_transit', 'DHL'), ('2', 'delivered', 'DHL'), "
                "('3', 'delivered', 'Toll')"
            )
        conn.commit()
    yield


SCHEMA_SQL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "k8s", "base", "sql", "schema.sql",
)


def _apply_schema(cur):
    """The same schema file the cluster applies. Not a copy of it."""
    with open(SCHEMA_SQL, encoding="utf-8") as fh:
        cur.execute(fh.read())


@pytest.fixture
def warehouse(shipments_table):
    """A warehouse with a complete ledger: every unit of stock has a movement.

    Deliberately includes the opening balance as an ADJUST movement, because
    /reports/reconciliation re-derives the balance from movements. Seeding
    stock without a matching movement would make the control report show a
    permanent discrepancy - and a control report that is always wrong is one
    nobody reads.
    """
    import psycopg

    conninfo = (
        f"host={os.environ['DB_HOST']} port={os.environ['DB_PORT']} "
        f"user={os.environ['DB_USER']} password={os.environ['DB_PASSWORD']} "
        f"dbname={os.environ['DB_NAME']} connect_timeout=3"
    )
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE movements, stock, order_lines, orders, "
                "receipt_lines, receipts, locations, skus RESTART IDENTITY CASCADE"
            )
            cur.execute("INSERT INTO skus (sku, description) VALUES "
                        "('TEST-A', 'Widget'), ('TEST-B', 'Gadget')")
            cur.execute("INSERT INTO locations (code, zone) VALUES "
                        "('BULK-1', 'BULK'), ('PICK-1', 'PICK'), ('DISP-01', 'DISP')")
            cur.execute("INSERT INTO stock (sku, location, qty) VALUES "
                        "('TEST-A', 'BULK-1', 100), ('TEST-A', 'PICK-1', 20), "
                        "('TEST-B', 'BULK-1', 5)")
            cur.execute(
                "INSERT INTO movements (sku, to_location, qty, reason, actor) "
                "SELECT sku, location, qty, 'ADJUST', 'seed/opening-balance' FROM stock")
            cur.execute(
                "INSERT INTO movements (sku, from_location, to_location, qty, reason, actor) "
                "VALUES ('TEST-A', 'BULK-1', 'PICK-1', 0 + 10, 'PUTAWAY', 'deck/pod-1/jmartin')")
            cur.execute("UPDATE stock SET qty = qty - 10 WHERE sku='TEST-A' AND location='BULK-1'")
            cur.execute("UPDATE stock SET qty = qty + 10 WHERE sku='TEST-A' AND location='PICK-1'")
            cur.execute("INSERT INTO orders (id, customer, status) VALUES "
                        "('ORD-OPEN', 'Austral', 'PICKING')")
            cur.execute("INSERT INTO order_lines (order_id, line_no, sku, qty, qty_picked) "
                        "VALUES ('ORD-OPEN', 1, 'TEST-A', 40, 10)")
        conn.commit()
    yield


@pytest.fixture
def db():
    """A raw connection, for tests that need to corrupt state deliberately.

    The reconciliation tests have to write stock WITHOUT a movement - which is
    exactly what the application is built to never do. There is no API for it,
    and there should not be, so the test reaches past the application to
    create the condition the report exists to detect.
    """
    import psycopg

    conninfo = (
        f"host={os.environ['DB_HOST']} port={os.environ['DB_PORT']} "
        f"user={os.environ['DB_USER']} password={os.environ['DB_PASSWORD']} "
        f"dbname={os.environ['DB_NAME']} connect_timeout=3"
    )
    conn = psycopg.connect(conninfo)
    yield conn
    conn.close()
