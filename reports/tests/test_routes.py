"""Unit tests for reports - no database required."""


def test_health_returns_ok_and_version(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["env"] == "test"
    assert body["version"] == "2.0"


def test_unknown_route_is_404(client):
    assert client.get("/reports/nope").status_code == 404
