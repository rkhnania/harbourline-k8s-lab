"""Plimsoll Core - the warehouse verbs, against a real Postgres.

These tests exist to prove three things that cannot be proved by reading code:

  1. Stock is CONSERVED. Picking moves it to the despatch lane; only dispatch
     removes it from the building. If that breaks, the number on the screen
     stops matching the pallets on the floor, which is the only failure a
     warehouse manager actually cares about.
  2. The DATABASE refuses impossible state. Not the application. A test that
     asserts "the API returned 409" would still pass if the check moved into
     Python and a direct SQL write could then go negative.
  3. Allocation prefers the pick face. That is the entire reason a pick face
     exists, and it is invisible in a total-quantity assertion.
"""


def _on_hand(client, sku=None):
    r = client.get("/stock" + (f"?sku={sku}" if sku else ""))
    assert r.status_code == 200
    return r.get_json()["on_hand"]


def _qty_at(client, sku, location):
    body = client.get(f"/stock?sku={sku}&location={location}").get_json()
    return body["lines"][0]["qty"] if body["lines"] else 0


# ------------------------------------------------------------------ receiving


def test_receiving_adds_stock_and_writes_a_movement(client, wms):
    before = _on_hand(client)

    r = client.post("/receipts/RCV-TEST/receive",
                    json={"line_no": 1, "qty": 20, "actor": "deck/test-1"})
    assert r.status_code == 201
    assert r.get_json()["received"] == 20

    assert _qty_at(client, "TEST-B", "RECV-01") == 20
    assert _on_hand(client) == before + 20

    latest = client.get("/movements?limit=1").get_json()[0]
    assert latest["reason"] == "RECEIPT"
    assert latest["sku"] == "TEST-B"
    assert latest["from_location"] is None
    assert latest["to_location"] == "RECV-01"
    assert latest["actor"] == "deck/test-1"


def test_over_receipt_is_refused_by_the_database(client, wms):
    """50 expected; receiving 60 must fail, and fail at the constraint.

    The response names no_silent_over_receipt, which is the proof that the
    refusal came from Postgres and not from a Python `if`.
    """
    r = client.post("/receipts/RCV-TEST/receive", json={"line_no": 1, "qty": 60})
    assert r.status_code == 409
    assert r.get_json()["constraint"] == "no_silent_over_receipt"
    assert _qty_at(client, "TEST-B", "RECV-01") == 0


# -------------------------------------------------------------------- putaway


def test_putaway_moves_stock_without_changing_the_total(client, wms):
    before = _on_hand(client)

    r = client.post("/putaway", json={"sku": "TEST-A", "from": "BULK-1",
                                      "to": "PICK-1", "qty": 40,
                                      "actor": "deck/test-2"})
    assert r.status_code == 201

    assert _qty_at(client, "TEST-A", "BULK-1") == 60
    assert _qty_at(client, "TEST-A", "PICK-1") == 50
    assert _on_hand(client) == before          # conserved


def test_putaway_of_more_than_exists_is_refused(client, wms):
    r = client.post("/putaway", json={"sku": "TEST-A", "from": "PICK-1",
                                      "to": "BULK-1", "qty": 999})
    assert r.status_code == 409
    assert _qty_at(client, "TEST-A", "PICK-1") == 10   # untouched


def test_putaway_to_an_unknown_location_is_refused(client, wms):
    r = client.post("/putaway", json={"sku": "TEST-A", "from": "PICK-1",
                                      "to": "NOWHERE", "qty": 1})
    assert r.status_code == 400
    assert _qty_at(client, "TEST-A", "PICK-1") == 10


# --------------------------------------------------------------------- picking


def test_picking_empties_the_pick_face_before_touching_bulk(client, wms):
    """The order needs 25; the pick face holds 10 and bulk holds 100.

    A correct allocation is 10 from PICK-1 then 15 from BULK-1 - in that order.
    Asserting only the total would pass even if it took all 25 from bulk and
    sent a picker to the far end of the warehouse.
    """
    r = client.post("/orders/ORD-TEST/pick", json={"line_no": 1, "actor": "deck/gun-7"})
    assert r.status_code == 201
    body = r.get_json()

    assert [a["location"] for a in body["allocation"]] == ["PICK-1", "BULK-1"]
    assert [a["qty"] for a in body["allocation"]] == [10, 15]
    assert body["order_status"] == "PICKED"

    assert _qty_at(client, "TEST-A", "PICK-1") == 0
    assert _qty_at(client, "TEST-A", "BULK-1") == 85
    assert _qty_at(client, "TEST-A", "DISP-01") == 25


def test_picking_conserves_stock(client, wms):
    before = _on_hand(client)
    client.post("/orders/ORD-TEST/pick", json={"line_no": 1})
    assert _on_hand(client) == before


def test_picking_more_than_outstanding_is_refused(client, wms):
    r = client.post("/orders/ORD-TEST/pick", json={"line_no": 1, "qty": 26})
    assert r.status_code == 409
    assert r.get_json()["outstanding"] == 25


def test_picking_records_every_source_in_the_ledger(client, wms):
    client.post("/orders/ORD-TEST/pick", json={"line_no": 1, "actor": "deck/gun-7"})
    picks = [m for m in client.get("/movements").get_json() if m["reason"] == "PICK"]
    assert {m["from_location"] for m in picks} == {"PICK-1", "BULK-1"}
    assert all(m["to_location"] == "DISP-01" for m in picks)
    assert all(m["actor"] == "deck/gun-7" for m in picks)


# -------------------------------------------------------------------- dispatch


def test_dispatch_requires_a_fully_picked_order(client, wms):
    r = client.post("/orders/ORD-TEST/dispatch")
    assert r.status_code == 409
    assert r.get_json()["status"] == "NEW"


def test_dispatch_removes_stock_and_creates_a_shipment(client, wms):
    client.post("/orders/ORD-TEST/pick", json={"line_no": 1})
    before = _on_hand(client)

    r = client.post("/orders/ORD-TEST/dispatch", json={"carrier": "Test Carrier"})
    assert r.status_code == 201
    assert r.get_json()["shipment"] == "SHP-TEST"

    # The ONLY verb that reduces what is on site.
    assert _on_hand(client) == before - 25
    assert _qty_at(client, "TEST-A", "DISP-01") == 0

    assert client.get("/orders/ORD-TEST").get_json()["status"] == "DISPATCHED"
    assert "SHP-TEST" in client.get("/shipments").get_json()


def test_the_whole_loop_leaves_a_complete_audit_trail(client, wms):
    """Receive, put away, pick, dispatch - and the ledger explains all of it."""
    client.post("/receipts/RCV-TEST/receive", json={"line_no": 1, "qty": 50})
    client.post("/putaway", json={"sku": "TEST-B", "from": "RECV-01",
                                  "to": "BULK-1", "qty": 50})
    client.post("/orders/ORD-TEST/pick", json={"line_no": 1})
    client.post("/orders/ORD-TEST/dispatch")

    reasons = [m["reason"] for m in client.get("/movements").get_json()]
    assert set(reasons) == {"RECEIPT", "PUTAWAY", "PICK", "DISPATCH"}

    # 110 opening + 50 received - 25 dispatched
    assert _on_hand(client) == 135
