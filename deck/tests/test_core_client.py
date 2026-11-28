"""fetch() - every failure mode becomes a message, never an exception.

An operator holding a handheld cannot read a stack trace and cannot restart a
crashed gateway. Anything fetch() fails to catch ends a shift.
"""
import io
import json
import urllib.error

import app


def _urlopen(monkeypatch, result):
    def fake(url, timeout=None):
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(result)

    monkeypatch.setattr(app.urllib.request, "urlopen", fake)


def test_returns_parsed_json(monkeypatch):
    _urlopen(monkeypatch, json.dumps({"shipments": [{"id": "SHP-1"}]}).encode())
    assert app.fetch("/shipments")["shipments"][0]["id"] == "SHP-1"


def test_http_error_reports_the_status(monkeypatch):
    _urlopen(monkeypatch, urllib.error.HTTPError("u", 503, "nope", {}, None))
    assert "503" in app.fetch("/shipments")["error"]


def test_connection_refused_is_a_message(monkeypatch):
    _urlopen(monkeypatch, urllib.error.URLError("connection refused"))
    assert "unreachable" in app.fetch("/shipments")["error"]


def test_timeout_is_a_message(monkeypatch):
    _urlopen(monkeypatch, TimeoutError())
    assert "unreachable" in app.fetch("/shipments")["error"]


def test_malformed_json_is_a_message_not_a_crash(monkeypatch):
    """Core returning HTML - a proxy error page, say - must not end the shift."""
    _urlopen(monkeypatch, b"<html>502 Bad Gateway</html>")
    assert "malformed" in app.fetch("/shipments")["error"]


def test_session_scan_reads_the_sku_catalogue(monkeypatch):
    """Scanning resolves against /skus, not against shipments.

    Until 28 Nov a scan looked a reference up in /shipments, because that was
    the only table Plimsoll had. A scanner reads a product barcode, so it
    resolves a SKU - and selecting one moves nothing, which is why this test
    asserts only on the reply.
    """
    _urlopen(monkeypatch, json.dumps(
        [{"sku": "HL-PAL-0001", "description": "Pallet wrap", "uom": "ROLL"}]
    ).encode())
    session = app.Session(peer=("10.0.0.1", 1))
    reply = session.scan("HL-PAL-0001")
    assert reply.startswith("OK")
    assert session.current_sku == "HL-PAL-0001"


def test_a_core_refusal_body_is_returned_rather_than_the_status_code(monkeypatch):
    """post() reads the body of a 409 instead of discarding it.

    Core explains WHY it refused - insufficient stock, over-receipt, order not
    picked. Throwing that away and reporting "core returned 409" turns an
    actionable message into a dead end for whoever is holding the scanner.
    """
    import urllib.error
    import io

    def raising(*a, **k):
        raise urllib.error.HTTPError(
            "http://core/putaway", 409, "Conflict", {},
            io.BytesIO(json.dumps({"error": "insufficient stock at source"}).encode()))

    monkeypatch.setattr(app.urllib.request, "urlopen", raising)
    assert app.post("/putaway", {})["error"] == "insufficient stock at source"
