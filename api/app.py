"""Plimsoll Core - the WMS middleware tier.

Every endpoint that changes stock does so in ONE transaction that writes both
the balance (stock) and the ledger (movements). A balance without a ledger
cannot answer "who moved it"; a ledger written in a separate transaction can
disagree with the balance, which is worse than having neither.

Two rules run through the whole file:

1. THE DATABASE REJECTS IMPOSSIBLE STATE, NOT THIS CODE.
   The naive way to pick stock is: SELECT the quantity, check it in Python,
   then UPDATE. Between those two statements another Deck pod can pick the same
   stock - a lost update, and the warehouse goes negative. Here the UPDATE is
   conditional and `CHECK (qty >= 0)` is the backstop, so a race produces a
   rejected request rather than inventory that cannot exist.

2. STOCK IS CONSERVED.
   Picking does not delete stock, it moves it to the despatch lane. Only
   dispatch removes it from the building. That way `SELECT sum(qty) FROM stock`
   always equals what is physically on site, which is the only version of the
   number anyone can act on.
"""

from flask import Flask, jsonify, request
import os
import socket

import psycopg
from psycopg.rows import dict_row
from psycopg import errors as pgerrors

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "postgres")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

RECEIVING_LOCATION = os.getenv("RECEIVING_LOCATION", "RECV-01")
DESPATCH_LOCATION = os.getenv("DESPATCH_LOCATION", "DISP-01")


def _conninfo():
    return (
        f"host={DB_HOST} port={DB_PORT} user={DB_USER} "
        f"password={DB_PASSWORD} dbname={DB_NAME} connect_timeout=3"
    )


def _connect():
    return psycopg.connect(_conninfo(), row_factory=dict_row)


def _actor():
    """Who performed the movement.

    Deck keeps session state in memory, so once a gun's pod is replaced there is
    no record of the session anywhere. The ledger's actor column is the only
    durable trace, which is why it is NOT NULL.
    """
    return (request.get_json(silent=True) or {}).get("actor") or request.headers.get(
        "X-Plimsoll-Actor", f"api/{socket.gethostname()}"
    )


def _body():
    return request.get_json(silent=True) or {}


# --------------------------------------------------------------------- errors


@app.errorhandler(pgerrors.CheckViolation)
def _check_violation(exc):
    """A constraint refusing a write is a 409, not a 500.

    The server did not fail - it correctly declined to put the warehouse into a
    state that cannot exist. Naming the constraint makes the refusal legible:
    stock_qty_non_negative means someone tried to pick more than is there.
    """
    name = getattr(getattr(exc, "diag", None), "constraint_name", None) or "unknown"
    return jsonify(error="rejected by database constraint", constraint=name), 409


@app.errorhandler(pgerrors.ForeignKeyViolation)
def _fk_violation(exc):
    name = getattr(getattr(exc, "diag", None), "constraint_name", None) or "unknown"
    return jsonify(error="unknown sku or location", constraint=name), 400


# ------------------------------------------------------------------ unchanged


@app.route("/health")
def health():
    return jsonify(status="ok", host=socket.gethostname(), env=ENVIRONMENT)


@app.route("/config")
def config():
    return jsonify(db_host=DB_HOST, db_port=DB_PORT, db_user=DB_USER,
                   db_name=DB_NAME, environment=ENVIRONMENT)


@app.route("/dbcheck")
def dbcheck():
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM shipments;")
            return jsonify(db="connected", shipments=cur.fetchone()["n"])
    except Exception as e:
        return jsonify(db="error", detail=str(e)), 500


@app.route("/shipments")
def shipments():
    # Contract unchanged since October, because the post-deployment smoke test
    # asserts it. Changing an interface and its verification together means the
    # verification proves nothing.
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, status FROM shipments ORDER BY id;")
            return jsonify({r["id"]: {"origin": "-", "destination": "-",
                                      "status": r["status"]}
                            for r in cur.fetchall()})
    except Exception as e:
        return jsonify(error=str(e)), 500


# ---------------------------------------------------------------------- reads


@app.route("/stock")
def stock():
    """Stock on hand, optionally filtered by ?sku= or ?location=."""
    sku = request.args.get("sku")
    location = request.args.get("location")
    sql = ("SELECT s.sku, s.location, l.zone, s.qty "
           "FROM stock s JOIN locations l ON l.code = s.location WHERE TRUE")
    params = []
    if sku:
        sql += " AND s.sku = %s"
        params.append(sku)
    if location:
        sql += " AND s.location = %s"
        params.append(location)
    sql += " ORDER BY s.sku, s.location;"
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return jsonify(lines=rows, on_hand=sum(r["qty"] for r in rows))


@app.route("/skus")
def skus():
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT sku, description, uom, hazard_class FROM skus ORDER BY sku;")
        return jsonify(cur.fetchall())


@app.route("/locations")
def locations():
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT code, zone, capacity FROM locations ORDER BY code;")
        return jsonify(cur.fetchall())


@app.route("/movements")
def movements():
    limit = min(int(request.args.get("limit", 50)), 500)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, occurred_at, sku, from_location, to_location, qty, "
            "reason, actor FROM movements ORDER BY id DESC LIMIT %s;", (limit,))
        return jsonify(cur.fetchall())


@app.route("/receipts/<receipt_id>")
def receipt(receipt_id):
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM receipts WHERE id = %s;", (receipt_id,))
        head = cur.fetchone()
        if head is None:
            return jsonify(error="no such receipt"), 404
        cur.execute("SELECT line_no, sku, qty_expected, qty_received "
                    "FROM receipt_lines WHERE receipt_id = %s ORDER BY line_no;",
                    (receipt_id,))
        head["lines"] = cur.fetchall()
    return jsonify(head)


@app.route("/orders/<order_id>")
def order(order_id):
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
        head = cur.fetchone()
        if head is None:
            return jsonify(error="no such order"), 404
        cur.execute("SELECT line_no, sku, qty, qty_picked FROM order_lines "
                    "WHERE order_id = %s ORDER BY line_no;", (order_id,))
        head["lines"] = cur.fetchall()
    return jsonify(head)


# --------------------------------------------------------------------- verbs


@app.route("/receipts/<receipt_id>/receive", methods=["POST"])
def receive(receipt_id):
    """Goods arrive against an expected receipt line."""
    body = _body()
    line_no, qty, actor = body.get("line_no"), body.get("qty"), _actor()
    if not isinstance(line_no, int) or not isinstance(qty, int) or qty <= 0:
        return jsonify(error="line_no (int) and qty (positive int) required"), 400

    with _connect() as conn:
        with conn.cursor() as cur:
            # FOR UPDATE: two receivers working the same load would otherwise
            # both read qty_received, both add, and the second write would
            # silently discard the first.
            cur.execute("SELECT sku, qty_expected, qty_received FROM receipt_lines "
                        "WHERE receipt_id = %s AND line_no = %s FOR UPDATE;",
                        (receipt_id, line_no))
            line = cur.fetchone()
            if line is None:
                return jsonify(error="no such receipt line"), 404

            # no_silent_over_receipt enforces this too; checking here only buys
            # a clearer message, it is not what makes it safe.
            cur.execute("UPDATE receipt_lines SET qty_received = qty_received + %s "
                        "WHERE receipt_id = %s AND line_no = %s;",
                        (qty, receipt_id, line_no))

            cur.execute(
                "INSERT INTO stock (sku, location, qty) VALUES (%s, %s, %s) "
                "ON CONFLICT (sku, location) DO UPDATE SET qty = stock.qty + EXCLUDED.qty;",
                (line["sku"], RECEIVING_LOCATION, qty))

            cur.execute(
                "INSERT INTO movements (sku, to_location, qty, reason, actor) "
                "VALUES (%s, %s, %s, 'RECEIPT', %s);",
                (line["sku"], RECEIVING_LOCATION, qty, actor))

            cur.execute(
                "UPDATE receipts SET status = 'ARRIVED', "
                "arrived_at = coalesce(arrived_at, now()) "
                "WHERE id = %s AND status = 'EXPECTED';", (receipt_id,))
        conn.commit()

    return jsonify(received=qty, sku=line["sku"], into=RECEIVING_LOCATION, actor=actor), 201


@app.route("/putaway", methods=["POST"])
def putaway():
    """Move stock from one location to another. The warehouse's only real verb."""
    body = _body()
    sku, src, dst, qty, actor = (body.get("sku"), body.get("from"),
                                 body.get("to"), body.get("qty"), _actor())
    if not all([sku, src, dst]) or not isinstance(qty, int) or qty <= 0:
        return jsonify(error="sku, from, to and positive int qty required"), 400
    if src == dst:
        return jsonify(error="from and to are the same location"), 400

    with _connect() as conn:
        with conn.cursor() as cur:
            # Conditional UPDATE, not read-then-write. If another pod took the
            # stock first this affects zero rows and we report a conflict,
            # instead of driving the balance negative.
            cur.execute("UPDATE stock SET qty = qty - %s "
                        "WHERE sku = %s AND location = %s AND qty >= %s;",
                        (qty, sku, src, qty))
            if cur.rowcount == 0:
                return jsonify(error="insufficient stock at source",
                               sku=sku, location=src, requested=qty), 409

            cur.execute(
                "INSERT INTO stock (sku, location, qty) VALUES (%s, %s, %s) "
                "ON CONFLICT (sku, location) DO UPDATE SET qty = stock.qty + EXCLUDED.qty;",
                (sku, dst, qty))
            cur.execute(
                "INSERT INTO movements (sku, from_location, to_location, qty, reason, actor) "
                "VALUES (%s, %s, %s, %s, 'PUTAWAY', %s);", (sku, src, dst, qty, actor))
        conn.commit()

    return jsonify(moved=qty, sku=sku, **{"from": src, "to": dst}, actor=actor), 201


@app.route("/orders/<order_id>/pick", methods=["POST"])
def pick(order_id):
    """Pick an order line, allocating across locations.

    Pick face first, then bulk. That ordering is the whole reason a pick face
    exists: it is replenished deliberately so that pickers walk short distances,
    and falling back to bulk is the exception worth recording.
    """
    body = _body()
    line_no, actor = body.get("line_no"), _actor()
    if not isinstance(line_no, int):
        return jsonify(error="line_no (int) required"), 400

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT sku, qty, qty_picked FROM order_lines "
                        "WHERE order_id = %s AND line_no = %s FOR UPDATE;",
                        (order_id, line_no))
            line = cur.fetchone()
            if line is None:
                return jsonify(error="no such order line"), 404

            outstanding = line["qty"] - line["qty_picked"]
            requested = body.get("qty", outstanding)
            if not isinstance(requested, int) or requested <= 0:
                return jsonify(error="qty must be a positive integer"), 400
            if requested > outstanding:
                return jsonify(error="exceeds outstanding quantity",
                               outstanding=outstanding), 409

            cur.execute(
                "SELECT s.location, s.qty, l.zone FROM stock s "
                "JOIN locations l ON l.code = s.location "
                "WHERE s.sku = %s AND s.qty > 0 AND l.zone IN ('PICK','BULK') "
                "ORDER BY (l.zone = 'PICK') DESC, s.qty ASC "
                "FOR UPDATE OF s;", (line["sku"],))
            sources = cur.fetchall()

            if sum(r["qty"] for r in sources) < requested:
                return jsonify(error="insufficient stock for sku", sku=line["sku"],
                               requested=requested,
                               available=sum(r["qty"] for r in sources)), 409

            remaining, allocation = requested, []
            for row in sources:
                if remaining == 0:
                    break
                take = min(remaining, row["qty"])
                cur.execute("UPDATE stock SET qty = qty - %s WHERE sku = %s AND location = %s;",
                            (take, line["sku"], row["location"]))
                cur.execute(
                    "INSERT INTO movements (sku, from_location, to_location, qty, reason, actor) "
                    "VALUES (%s, %s, %s, %s, 'PICK', %s);",
                    (line["sku"], row["location"], DESPATCH_LOCATION, take, actor))
                allocation.append({"location": row["location"], "zone": row["zone"], "qty": take})
                remaining -= take

            # Stock is conserved: it is now in the despatch lane, not gone.
            cur.execute(
                "INSERT INTO stock (sku, location, qty) VALUES (%s, %s, %s) "
                "ON CONFLICT (sku, location) DO UPDATE SET qty = stock.qty + EXCLUDED.qty;",
                (line["sku"], DESPATCH_LOCATION, requested))

            cur.execute("UPDATE order_lines SET qty_picked = qty_picked + %s "
                        "WHERE order_id = %s AND line_no = %s;", (requested, order_id, line_no))

            cur.execute(
                "UPDATE orders SET status = CASE WHEN NOT EXISTS ("
                "  SELECT 1 FROM order_lines WHERE order_id = %s AND qty_picked < qty"
                ") THEN 'PICKED' ELSE 'PICKING' END WHERE id = %s RETURNING status;",
                (order_id, order_id))
            status = cur.fetchone()["status"]
        conn.commit()

    return jsonify(picked=requested, sku=line["sku"], allocation=allocation,
                   order_status=status, actor=actor), 201


@app.route("/orders/<order_id>/dispatch", methods=["POST"])
def dispatch(order_id):
    """Ship a fully picked order. This is the only verb that removes stock."""
    actor = _actor()
    carrier = _body().get("carrier", "Harbourline Freight")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM orders WHERE id = %s FOR UPDATE;", (order_id,))
            head = cur.fetchone()
            if head is None:
                return jsonify(error="no such order"), 404
            if head["status"] != "PICKED":
                return jsonify(error="order is not fully picked",
                               status=head["status"]), 409

            cur.execute("SELECT sku, sum(qty_picked) AS qty FROM order_lines "
                        "WHERE order_id = %s GROUP BY sku;", (order_id,))
            for row in cur.fetchall():
                cur.execute("UPDATE stock SET qty = qty - %s "
                            "WHERE sku = %s AND location = %s AND qty >= %s;",
                            (row["qty"], row["sku"], DESPATCH_LOCATION, row["qty"]))
                if cur.rowcount == 0:
                    return jsonify(error="despatch lane does not hold the picked stock",
                                   sku=row["sku"]), 409
                cur.execute(
                    "INSERT INTO movements (sku, from_location, qty, reason, actor) "
                    "VALUES (%s, %s, %s, 'DISPATCH', %s);",
                    (row["sku"], DESPATCH_LOCATION, row["qty"], actor))

            shipment_id = f"SHP-{order_id.split('-')[-1]}"
            cur.execute(
                "INSERT INTO shipments (id, status, carrier) VALUES (%s, 'in-transit', %s) "
                "ON CONFLICT (id) DO UPDATE SET status = 'in-transit';",
                (shipment_id, carrier))
            cur.execute("UPDATE orders SET status = 'DISPATCHED' WHERE id = %s;", (order_id,))
        conn.commit()

    return jsonify(dispatched=order_id, shipment=shipment_id,
                   carrier=carrier, actor=actor), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
