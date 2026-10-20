"""Integration tests - these run real SQL against a real Postgres."""


def test_dbcheck_reports_connected_with_a_row_count(client, shipments_table):
    r = client.get("/dbcheck")
    assert r.status_code == 200
    body = r.get_json()
    assert body["db"] == "connected"
    assert body["shipments"] == 3


def test_shipments_returns_every_row_keyed_by_id(client, shipments_table):
    r = client.get("/shipments")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"1", "2", "3"}
    assert body["1"]["status"] == "in_transit"
    assert body["2"]["status"] == "delivered"


def test_shipments_origin_and_destination_are_placeholders(client, shipments_table):
    """Characterisation test: records what the code DOES, not what it should do.

    /shipments hardcodes '-' for origin and destination because the shipments
    table has no such columns - only id, status and carrier. This is the bug
    behind the dashes in the web UI.

    When that is fixed by swapping the columns for Carrier, this test SHOULD
    fail. That is the point: it turns a known gap into something that announces
    itself when touched, instead of a note in a backlog nobody rereads.
    """
    body = client.get("/shipments").get_json()
    assert body["1"]["origin"] == "-"
    assert body["1"]["destination"] == "-"
