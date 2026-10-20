"""Integration tests for reports - real SQL, real aggregation."""


def test_summary_counts_by_status(client, shipments_table):
    r = client.get("/reports/summary")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 3
    assert body["by_status"] == {"delivered": 2, "in_transit": 1}


def test_carriers_counts_by_carrier(client, shipments_table):
    r = client.get("/reports/carriers")
    assert r.status_code == 200
    assert r.get_json()["by_carrier"] == {"DHL": 2, "Toll": 1}


def test_summary_total_equals_the_sum_of_its_parts(client, shipments_table):
    """Guards the aggregation itself, not just the connection.

    total is computed in Python from rows GROUP BY'd in SQL. If either side
    changes independently the two disagree, and nothing else would notice.
    """
    body = client.get("/reports/summary").get_json()
    assert body["total"] == sum(body["by_status"].values())
