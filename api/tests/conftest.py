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
            # Text ids, because that is what the real schema declares. The
            # fixture used `id int` until 28 Nov while production used text -
            # a suite that passes against a database no deployment has. The
            # assertions did not change, because JSON object keys are strings
            # either way, which is exactly why the drift went unnoticed.
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
    """Apply the SAME schema file the cluster applies.

    Not a copy of it. A schema defined twice drifts, and the tests then prove
    something about a database that exists nowhere.
    """
    with open(SCHEMA_SQL, encoding="utf-8") as fh:
        cur.execute(fh.read())


@pytest.fixture
def wms(shipments_table):
    """A small, deterministic warehouse, rebuilt for every test.

    Function-scoped and truncated each time, because every test here MOVES
    stock. Sharing warehouse state between tests makes failures depend on
    execution order, which is the worst kind of flaky.

    The shape is deliberate: TEST-A has 10 units on the pick face and 100 in
    bulk, and the open order asks for 25. So a correct pick must take the pick
    face first and then fall back to bulk, and a test can assert the order
    rather than just the total.
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
            cur.execute(
                "INSERT INTO skus (sku, description, uom) VALUES "
                "('TEST-A', 'Test widget', 'EA'), ('TEST-B', 'Test gadget', 'EA')"
            )
            cur.execute(
                "INSERT INTO locations (code, zone, capacity) VALUES "
                "('RECV-01', 'RECV', 1000), ('BULK-1', 'BULK', 1000), "
                "('PICK-1', 'PICK', 100), ('DISP-01', 'DISP', 1000)"
            )
            cur.execute(
                "INSERT INTO stock (sku, location, qty) VALUES "
                "('TEST-A', 'PICK-1', 10), ('TEST-A', 'BULK-1', 100)"
            )
            # Opening balances are movements too, or the reconciliation report
            # shows a permanent discrepancy equal to the opening stock.
            cur.execute(
                "INSERT INTO movements (sku, to_location, qty, reason, actor) "
                "SELECT sku, location, qty, 'ADJUST', 'seed/opening-balance' FROM stock"
            )
            cur.execute(
                "INSERT INTO receipts (id, carrier) VALUES ('RCV-TEST', 'Test Carrier')"
            )
            cur.execute(
                "INSERT INTO receipt_lines (receipt_id, line_no, sku, qty_expected) "
                "VALUES ('RCV-TEST', 1, 'TEST-B', 50)"
            )
            cur.execute(
                "INSERT INTO orders (id, customer) VALUES ('ORD-TEST', 'Test Customer')"
            )
            cur.execute(
                "INSERT INTO order_lines (order_id, line_no, sku, qty) "
                "VALUES ('ORD-TEST', 1, 'TEST-A', 25)"
            )
        conn.commit()
    yield
