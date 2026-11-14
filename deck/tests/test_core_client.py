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


def test_session_scan_tolerates_a_list_response(monkeypatch):
    """The api returns a bare list; older builds returned {"shipments": [...]}.

    Deck accepts both rather than breaking on a response shape it did not
    choose.
    """
    _urlopen(monkeypatch, json.dumps([{"id": "SHP-7", "status": "PICKED"}]).encode())
    session = app.Session(peer=("10.0.0.1", 1))
    assert session.scan("SHP-7").startswith("OK")
