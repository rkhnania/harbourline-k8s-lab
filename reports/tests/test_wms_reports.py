"""Plimsoll Insight - the warehouse reports.

The one that earns its place is /reports/reconciliation. Every stock change is
written as a balance update AND a ledger entry inside one transaction, so the
two must agree. These tests prove the report can tell when they don't - which
is the only way to know the report is worth running.
"""


def test_stock_report_cuts_the_same_number_two_ways(client, warehouse):
    body = client.get("/reports/stock").get_json()

    assert body["by_sku"]["TEST-A"]["qty"] == 120
    assert body["by_sku"]["TEST-A"]["locations"] == 2
    assert body["by_sku"]["TEST-B"]["qty"] == 5

    # Per SKU answers "can we ship it". Per zone answers "is the pick face
    # starving". Same units, different question.
    assert body["by_zone"]["PICK"] == 30
    assert body["by_zone"]["BULK"] == 95
    assert body["by_zone"]["DISP"] == 0

    assert body["on_hand"] == sum(v["qty"] for v in body["by_sku"].values())


def test_throughput_attributes_work_to_the_operator(client, warehouse):
    """Only possible because Deck writes the actor into the ledger.

    The session that performed the putaway is long gone; the attribution
    survives because it was written in the same transaction as the stock move.
    """
    body = client.get("/reports/throughput").get_json()
    assert body["by_reason"]["PUTAWAY"]["units"] == 10
    assert body["by_actor"]["deck/pod-1/jmartin"]["movements"] == 1
    assert "seed/opening-balance" in body["by_actor"]


def test_reconciliation_is_balanced_when_the_ledger_is_complete(client, warehouse):
    body = client.get("/reports/reconciliation").get_json()
    assert body["balanced"] is True
    assert body["discrepancies"] == []
    assert body["verdict"] == "IN-BALANCE"


def test_the_verdict_tokens_cannot_be_confused_by_a_substring_match(client, warehouse, db):
    """The smoke test greps this response, so the two verdicts must not overlap.

    If the failing verdict contained the passing one, a broken warehouse would
    pass the deployment check - the worst possible failure mode for a gate.
    """
    assert "IN-BALANCE" not in "OUT-OF-BALANCE"

    with db.cursor() as cur:
        cur.execute("UPDATE stock SET qty = qty + 1 WHERE sku = 'TEST-B'")
    db.commit()

    body = client.get("/reports/reconciliation").get_json()
    assert body["verdict"] == "OUT-OF-BALANCE"
    assert body["discrepancy_count"] == 1


def test_reconciliation_catches_a_write_that_skipped_the_ledger(client, warehouse, db):
    """The failure this report exists for.

    Someone updates stock directly - a manual fix, a migration, a service that
    forgot to write the movement. The balance table now says something the
    ledger cannot account for, and every number on every dashboard is quietly
    wrong. The report names the SKU and location to go and count.
    """
    with db.cursor() as cur:
        cur.execute("UPDATE stock SET qty = qty + 7 "
                    "WHERE sku = 'TEST-A' AND location = 'BULK-1'")
    db.commit()

    body = client.get("/reports/reconciliation").get_json()
    assert body["balanced"] is False
    assert len(body["discrepancies"]) == 1

    found = body["discrepancies"][0]
    assert found["sku"] == "TEST-A"
    assert found["location"] == "BULK-1"
    assert found["difference"] == 7


def test_reconciliation_catches_stock_that_vanished(client, warehouse, db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM stock WHERE sku = 'TEST-B'")
    db.commit()

    body = client.get("/reports/reconciliation").get_json()
    assert body["balanced"] is False
    # Balance says nothing is there; the ledger still says five arrived.
    assert body["discrepancies"][0] == {
        "sku": "TEST-B", "location": "BULK-1",
        "balance": 0, "ledger": 5, "difference": -5,
    }


def test_open_orders_reports_a_fill_rate(client, warehouse):
    body = client.get("/reports/open-orders").get_json()
    assert body["count"] == 1
    order = body["open_orders"][0]
    assert order["id"] == "ORD-OPEN"
    assert order["ordered"] == 40
    assert order["picked"] == 10
    assert order["fill_rate"] == 0.25


def test_an_order_with_no_lines_does_not_divide_by_zero(client, warehouse, db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO orders (id, customer) VALUES ('ORD-EMPTY', 'Nobody')")
    db.commit()

    body = client.get("/reports/open-orders").get_json()
    empty = [o for o in body["open_orders"] if o["id"] == "ORD-EMPTY"][0]
    assert empty["fill_rate"] == 0.0


def test_the_shipments_summary_is_unchanged(client, warehouse):
    """Contract the smoke test has asserted since October. Do not move it."""
    body = client.get("/reports/summary").get_json()
    assert body["total"] == 3
    assert body["by_status"]["delivered"] == 2
