"""Plimsoll Deck - the command grammar.

dispatch() has no I/O in it, so every one of these runs in microseconds with no
network and no database. That separation is the reason this tier has tests at
all: asyncio.start_server is not ours to test, the grammar is ours and it is
the part that will be wrong.

Core is replaced with a fake throughout. These tests are about what the
scanner is TOLD - an operator holding a handheld cannot read a stack trace,
cannot scroll, and cannot restart a gateway. Every failure has to arrive as a
line of text they can act on.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


SKUS = [
    {"sku": "HL-PAL-0001", "description": "Pallet wrap", "uom": "ROLL",
     "hazard_class": None},
    {"sku": "HL-BAT-0003", "description": "Cell pack", "uom": "EA",
     "hazard_class": "UN3480"},
]


@pytest.fixture
def session():
    return app.Session(("10.244.0.9", 51234))


@pytest.fixture
def core(monkeypatch):
    """A fake Core that records what was POSTed to it."""
    sent = []

    def fake_fetch(path):
        if path.startswith("/skus"):
            return SKUS
        if path.startswith("/stock"):
            return {"lines": [{"location": "B-01-01", "zone": "PICK", "qty": 36}],
                    "on_hand": 36}
        return {"error": "unexpected path"}

    def fake_post(path, payload):
        sent.append((path, payload))
        if path == "/putaway":
            return {"moved": payload["qty"], "sku": payload["sku"],
                    "from": payload["from"], "to": payload["to"]}
        if path.endswith("/pick"):
            return {"picked": payload.get("qty", 25), "sku": "HL-PAL-0001",
                    "allocation": [{"location": "B-01-01", "qty": 10},
                                   {"location": "A-01-01", "qty": 15}],
                    "order_status": "PICKED"}
        return {"error": "unexpected path"}

    monkeypatch.setattr(app, "fetch", fake_fetch)
    monkeypatch.setattr(app, "post", fake_post)
    return sent


# ------------------------------------------------------------------- grammar


def test_blank_line_is_ignored(session):
    reply, close = app.dispatch(session, "   ")
    assert reply == ""
    assert close is False


def test_unknown_command_names_what_it_got(session):
    reply, _ = app.dispatch(session, "SHIP SHP-1")
    assert "unknown command" in reply
    assert "SHIP" in reply


def test_commands_are_case_insensitive(session):
    assert app.dispatch(session, "help")[0] == app.dispatch(session, "HELP")[0]


def test_quit_closes_and_reports_the_session_total(session):
    session.scans = ["a", "b"]
    session.picked = 40
    reply, close = app.dispatch(session, "QUIT")
    assert close is True
    assert "2 scans" in reply
    assert "40 picked" in reply


# -------------------------------------------------------------------- actor


def test_login_sets_the_actor_recorded_in_the_ledger(session):
    app.dispatch(session, "LOGIN jmartin")
    assert session.operator == "jmartin"
    assert session.actor == f"deck/{app.HOST}/jmartin"


def test_an_anonymous_session_still_has_an_actor(session):
    """NOT NULL in the schema, so there is no "nobody did it" option.

    An unattributed stock movement is the thing a stock-discrepancy
    investigation cannot work with, so the gateway always names itself.
    """
    assert session.actor.endswith("/anon")
    assert app.HOST in session.actor


def test_the_actor_travels_with_every_write(session, core):
    app.dispatch(session, "LOGIN jmartin")
    app.dispatch(session, "SCAN HL-PAL-0001")
    app.dispatch(session, "MOVE A-01-01 B-01-01 12")
    app.dispatch(session, "PICK ORD-7001 1 5")
    assert all(payload["actor"] == f"deck/{app.HOST}/jmartin"
               for _, payload in core)


# ------------------------------------------------------------------ scanning


def test_scan_selects_a_sku_without_moving_anything(session, core):
    reply, _ = app.dispatch(session, "SCAN HL-PAL-0001")
    assert reply.startswith("OK")
    assert "Pallet wrap" in reply
    assert session.current_sku == "HL-PAL-0001"
    assert core == []          # nothing was written


def test_scan_surfaces_a_hazard_class(session, core):
    """Dangerous goods are the most common reason a putaway is refused.

    Showing it at scan time is the difference between a rejected movement and
    a rejected movement the operator saw coming.
    """
    reply, _ = app.dispatch(session, "SCAN HL-BAT-0003")
    assert "HAZARD=UN3480" in reply


def test_scan_rejects_an_unknown_sku_without_recording_it(session, core):
    reply, _ = app.dispatch(session, "SCAN NOPE-9999")
    assert reply.startswith("ERR")
    assert session.scans == []
    assert session.current_sku is None


def test_scan_without_a_reference_is_an_error_not_a_crash(session):
    reply, close = app.dispatch(session, "SCAN")
    assert reply.startswith("ERR")
    assert close is False


# ------------------------------------------------------------------- moving


def test_move_uses_the_scanned_sku_not_a_typed_one(session, core):
    """The barcode in the operator's hand beats a value typed on a 12-key pad."""
    app.dispatch(session, "SCAN HL-PAL-0001")
    reply, _ = app.dispatch(session, "MOVE A-01-01 B-01-01 12")
    assert reply.startswith("OK")
    path, payload = core[-1]
    assert path == "/putaway"
    assert payload["sku"] == "HL-PAL-0001"
    assert payload["qty"] == 12


def test_move_before_a_scan_is_refused(session, core):
    reply, _ = app.dispatch(session, "MOVE A-01-01 B-01-01 12")
    assert reply.startswith("ERR")
    assert core == []


def test_a_non_numeric_quantity_is_a_message_not_a_traceback(session, core):
    app.dispatch(session, "SCAN HL-PAL-0001")
    reply, close = app.dispatch(session, "MOVE A-01-01 B-01-01 twelve")
    assert reply.startswith("ERR")
    assert "twelve" in reply
    assert close is False
    assert core == []


# ------------------------------------------------------------------- picking


def test_pick_reports_where_the_stock_came_from(session, core):
    """The allocation is the useful part: it tells the operator where to walk."""
    reply, _ = app.dispatch(session, "PICK ORD-7001 1")
    assert reply.startswith("OK")
    assert "B-01-01x10" in reply
    assert "A-01-01x15" in reply
    assert "order=PICKED" in reply


def test_pick_accumulates_into_the_session_total(session, core):
    app.dispatch(session, "PICK ORD-7001 1 5")
    app.dispatch(session, "PICK ORD-7001 1 5")
    assert session.picked == 10


def test_pick_with_the_wrong_argument_count_is_refused(session, core):
    reply, _ = app.dispatch(session, "PICK ORD-7001")
    assert reply.startswith("ERR")
    assert core == []


def test_a_refusal_from_core_is_shown_verbatim(session, monkeypatch):
    """Core answers a refused movement with the reason. Pass it through.

    "core returned 409" teaches an operator nothing. "insufficient stock at
    source" sends them to a different bay.
    """
    monkeypatch.setattr(app, "post",
                        lambda p, b: {"error": "insufficient stock at source"})
    reply, _ = app.dispatch(session, "PICK ORD-7001 1")
    assert "insufficient stock at source" in reply


# --------------------------------------------------------------- resilience


def test_core_being_down_is_a_message_not_an_exception(session, monkeypatch):
    monkeypatch.setattr(app, "fetch",
                        lambda path: {"error": "core unreachable: refused"})
    reply, close = app.dispatch(session, "STOCK HL-PAL-0001")
    assert reply.startswith("ERR")
    assert "unreachable" in reply
    assert close is False


def test_status_reports_the_gateway_and_the_counters(session, core):
    app.dispatch(session, "SCAN HL-PAL-0001")
    reply, _ = app.dispatch(session, "STATUS")
    assert app.HOST in reply
    assert "scans=1" in reply
    assert "sku=HL-PAL-0001" in reply


def test_list_handles_an_empty_catalogue(session, monkeypatch):
    monkeypatch.setattr(app, "fetch", lambda path: [])
    reply, _ = app.dispatch(session, "LIST")
    assert "no skus" in reply


def test_list_is_capped_so_a_scanner_screen_is_not_flooded(session, monkeypatch):
    monkeypatch.setattr(app, "fetch", lambda path: [
        {"sku": f"SKU-{i}", "description": "x"} for i in range(50)])
    reply, _ = app.dispatch(session, "LIST")
    assert len(reply.splitlines()) == 20


def test_session_state_is_per_connection(core):
    """Why this tier needs sticky routing, in one assertion.

    Two sessions are two objects in one process. Nothing outside the process
    knows either exists - so a request routed to a different pod arrives with
    no idea the operator is mid-task, and a rolling update drops the lot.
    """
    a = app.Session(("10.244.0.9", 1))
    b = app.Session(("10.244.0.9", 2))

    app.dispatch(a, "LOGIN jmartin")
    app.dispatch(a, "SCAN HL-PAL-0001")

    assert a.scans == ["HL-PAL-0001"]
    assert a.current_sku == "HL-PAL-0001"
    assert b.scans == []
    assert b.current_sku is None
    assert b.operator is None
