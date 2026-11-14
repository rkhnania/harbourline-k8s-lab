"""The command grammar.

dispatch() has no I/O in it, which is the point: the protocol is the part that
will be wrong, and it can be tested in microseconds without opening a socket.
asyncio.start_server is not ours to test.
"""
import app
import pytest


@pytest.fixture
def session():
    return app.Session(peer=("10.0.0.9", 51234))


@pytest.fixture
def core(monkeypatch):
    """Stand in for Plimsoll Core. Returns whatever the test sets."""
    state = {"response": {"shipments": []}}

    def fake_fetch(path):
        state["last_path"] = path
        return state["response"]

    monkeypatch.setattr(app, "fetch", fake_fetch)
    return state


def test_blank_line_is_ignored(session):
    reply, close = app.dispatch(session, "   \r\n")
    assert reply == ""
    assert close is False


def test_unknown_command_names_what_it_got(session):
    reply, _ = app.dispatch(session, "PICK 42\r\n")
    assert "unknown command" in reply
    assert "PICK" in reply


def test_commands_are_case_insensitive(session):
    assert app.dispatch(session, "help")[0] == app.dispatch(session, "HELP")[0]


def test_quit_closes_and_reports_the_session_total(session):
    session.scans.extend(["SHP-1", "SHP-2"])
    reply, close = app.dispatch(session, "QUIT\r\n")
    assert close is True
    assert "2 picks" in reply


def test_scan_without_a_reference_is_an_error_not_a_crash(session):
    reply, close = app.dispatch(session, "SCAN\r\n")
    assert reply.startswith("ERR")
    assert close is False


def test_scan_records_a_known_shipment(session, core):
    core["response"] = {"shipments": [{"id": "SHP-0001", "status": "IN_TRANSIT"}]}
    reply, _ = app.dispatch(session, "SCAN SHP-0001\r\n")
    assert reply.startswith("OK")
    assert "IN_TRANSIT" in reply
    assert session.scans == ["SHP-0001"]


def test_scan_rejects_an_unknown_shipment_without_recording_it(session, core):
    core["response"] = {"shipments": [{"id": "SHP-0001", "status": "IN_TRANSIT"}]}
    reply, _ = app.dispatch(session, "SCAN SHP-9999\r\n")
    assert reply.startswith("ERR")
    assert session.scans == []


def test_core_being_down_is_a_message_not_an_exception(session, core):
    """An operator holding a handheld cannot read a stack trace."""
    core["response"] = {"error": "core unreachable: timed out"}
    reply, close = app.dispatch(session, "SCAN SHP-0001\r\n")
    assert reply.startswith("ERR")
    assert "unreachable" in reply
    assert close is False


def test_status_reports_the_gateway_and_the_pick_count(session):
    session.scans.append("SHP-1")
    reply, _ = app.dispatch(session, "STATUS\r\n")
    assert app.HOST in reply
    assert "picks=1" in reply


def test_list_handles_an_empty_warehouse(session, core):
    core["response"] = {"shipments": []}
    reply, _ = app.dispatch(session, "LIST\r\n")
    assert "no shipments" in reply


def test_list_is_capped_so_a_scanner_screen_is_not_flooded(session, core):
    core["response"] = {"shipments": [{"id": i, "status": "NEW"} for i in range(50)]}
    reply, _ = app.dispatch(session, "LIST\r\n")
    assert len(reply.splitlines()) == 20


def test_session_state_is_per_connection(core):
    """The reason this tier needs sticky routing.

    Two sessions do not see each other's work, and nothing outside the process
    sees either of them. Move the connection to another pod and the count is
    gone.
    """
    core["response"] = {"shipments": [{"id": "SHP-1", "status": "NEW"}]}
    a, b = app.Session(peer=("10.0.0.1", 1)), app.Session(peer=("10.0.0.2", 2))
    app.dispatch(a, "SCAN SHP-1")
    assert a.scans == ["SHP-1"]
    assert b.scans == []
