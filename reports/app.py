from flask import Flask, jsonify
import os, socket, psycopg

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "postgres")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

CONNINFO = (f"host={DB_HOST} port={DB_PORT} user={DB_USER} "
            f"password={DB_PASSWORD} dbname={DB_NAME} connect_timeout=3")


@app.route("/health")
def health():
    return jsonify(status="ok", host=socket.gethostname(), env=ENVIRONMENT, version="2.0")


@app.route("/reports/summary")
def summary():
    try:
        with psycopg.connect(CONNINFO) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status, count(*) FROM shipments GROUP BY status ORDER BY status;")
                rows = cur.fetchall()
        return jsonify(host=socket.gethostname(),
                       total=sum(r[1] for r in rows),
                       by_status={r[0]: r[1] for r in rows})
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/reports/carriers")
def carriers():
    try:
        with psycopg.connect(CONNINFO) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT carrier, count(*) FROM shipments GROUP BY carrier ORDER BY 2 DESC;")
                rows = cur.fetchall()
        return jsonify(host=socket.gethostname(), by_carrier={r[0]: r[1] for r in rows})
    except Exception as e:
        return jsonify(error=str(e)), 500



# ----------------------------------------------------------------- warehouse


@app.route("/reports/stock")
def stock():
    """On hand, by SKU and by zone.

    Two cuts of the same number because they answer different questions:
    "do we have enough to ship" is per SKU, "is the pick face starving" is per
    zone.
    """
    try:
        with psycopg.connect(CONNINFO) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT s.sku, sum(s.qty) AS qty, count(*) AS locations "
                "FROM stock s GROUP BY s.sku ORDER BY s.sku;")
            by_sku = {r[0]: {"qty": r[1], "locations": r[2]} for r in cur.fetchall()}

            cur.execute(
                "SELECT l.zone, coalesce(sum(s.qty), 0) FROM locations l "
                "LEFT JOIN stock s ON s.location = l.code GROUP BY l.zone ORDER BY l.zone;")
            by_zone = {r[0]: r[1] for r in cur.fetchall()}

        return jsonify(host=socket.gethostname(), by_sku=by_sku, by_zone=by_zone,
                       on_hand=sum(v["qty"] for v in by_sku.values()))
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/reports/throughput")
def throughput():
    """What the warehouse did, by movement reason and by operator.

    The actor breakdown is only possible because Deck writes who performed
    each movement into the ledger. Session state dies with the pod; this does
    not.
    """
    try:
        with psycopg.connect(CONNINFO) as conn, conn.cursor() as cur:
            cur.execute("SELECT reason, count(*), coalesce(sum(qty), 0) "
                        "FROM movements GROUP BY reason ORDER BY reason;")
            by_reason = {r[0]: {"movements": r[1], "units": r[2]}
                         for r in cur.fetchall()}

            cur.execute("SELECT actor, count(*), coalesce(sum(qty), 0) "
                        "FROM movements GROUP BY actor ORDER BY 3 DESC LIMIT 20;")
            by_actor = {r[0]: {"movements": r[1], "units": r[2]}
                        for r in cur.fetchall()}

        return jsonify(host=socket.gethostname(),
                       by_reason=by_reason, by_actor=by_actor)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/reports/reconciliation")
def reconciliation():
    """Re-derive the balance from the ledger and compare it to the balance table.

    THIS IS THE REPORT THAT MATTERS. Every stock change is written as a balance
    update AND a ledger entry inside one transaction, so the two must agree. If
    they ever diverge, something wrote to stock outside that discipline - a
    manual UPDATE, a migration, a service that forgot the ledger - and the
    number on the screen has quietly stopped describing the warehouse.

    A real WMS calls this a cycle-count control report, and it is the first
    thing an auditor asks for. It is cheap to compute and it either returns an
    empty list or tells you exactly which SKU and location to go and count.
    """
    try:
        with psycopg.connect(CONNINFO) as conn, conn.cursor() as cur:
            cur.execute("""
                WITH ledger AS (
                    SELECT sku, location, sum(delta) AS qty FROM (
                        SELECT sku, to_location   AS location,  qty AS delta
                          FROM movements WHERE to_location IS NOT NULL
                        UNION ALL
                        SELECT sku, from_location AS location, -qty AS delta
                          FROM movements WHERE from_location IS NOT NULL
                    ) m GROUP BY sku, location
                )
                SELECT coalesce(s.sku, l.sku), coalesce(s.location, l.location),
                       coalesce(s.qty, 0), coalesce(l.qty, 0)
                FROM stock s
                FULL OUTER JOIN ledger l ON l.sku = s.sku AND l.location = s.location
                WHERE coalesce(s.qty, 0) <> coalesce(l.qty, 0)
                ORDER BY 1, 2;
            """)
            discrepancies = [
                {"sku": r[0], "location": r[1], "balance": r[2],
                 "ledger": r[3], "difference": r[2] - r[3]}
                for r in cur.fetchall()
            ]
        return jsonify(host=socket.gethostname(),
                       balanced=not discrepancies,
                       discrepancies=discrepancies)
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/reports/open-orders")
def open_orders():
    """Orders not yet dispatched, with how far through picking each one is."""
    try:
        with psycopg.connect(CONNINFO) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT o.id, o.customer, o.status, "
                "       coalesce(sum(ol.qty), 0), coalesce(sum(ol.qty_picked), 0) "
                "FROM orders o LEFT JOIN order_lines ol ON ol.order_id = o.id "
                "WHERE o.status <> 'DISPATCHED' "
                "GROUP BY o.id, o.customer, o.status ORDER BY o.id;")
            orders = [
                {"id": r[0], "customer": r[1], "status": r[2],
                 "ordered": r[3], "picked": r[4],
                 # Guard the divide: an order with no lines is 0%, not a 500.
                 "fill_rate": round(r[4] / r[3], 3) if r[3] else 0.0}
                for r in cur.fetchall()
            ]
        return jsonify(host=socket.gethostname(), open_orders=orders,
                       count=len(orders))
    except Exception as e:
        return jsonify(error=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
