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
    return jsonify(status="ok", host=socket.gethostname(), env=ENVIRONMENT)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
