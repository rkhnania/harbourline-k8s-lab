"""Unit tests - no database, no network, no server.

Flask's test_client() dispatches through the real routing table and the real
view functions, so these exercise the application rather than a stand-in.
"""


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["env"] == "test"
    assert body["host"]


def test_config_never_exposes_the_password(client):
    """A security property, asserted.

    /config exists to report effective configuration, which is exactly the kind
    of endpoint that grows a field someone regrets. This fails the build if
    DB_PASSWORD is ever added to it.

    NOTE ON THE ASSERTIONS: every one of them compares KEY NAMES, never values,
    and each carries its own message. pytest rewrites a bare assert to print
    both sides of the comparison - so `assert "db_password" not in body` prints
    the entire response body, password and all, straight into the CI log.
    A test that guards a secret must not leak it on failure.
    """
    body = client.get("/config").get_json()
    keys = sorted(body)

    assert "db_password" not in keys, f"/config exposes db_password; keys: {keys}"

    password_like_keys = [k for k in keys if "password" in k.lower() or "secret" in k.lower()]
    assert not password_like_keys, f"/config exposes credential-like keys: {password_like_keys}"

    # Checks the VALUES without ever printing one: report the key that carries
    # the offending value, never the value itself.
    leaking_keys = [k for k, v in body.items() if "password" in str(v).lower()]
    assert not leaking_keys, f"/config has a password-like value under: {leaking_keys}"


def test_unknown_route_is_404(client):
    assert client.get("/no-such-route").status_code == 404
