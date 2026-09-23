from flask import Flask, jsonify
import os, socket, psycopg

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "postgres")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

@app.route("/health")
def health():
    return jsonify(status="ok", host=socket.gethostname(), env=ENVIRONMENT)

@app.route("/config")
def config():
    return jsonify(db_host=DB_HOST, db_port=DB_PORT, db_user=DB_USER,
                   db_name=DB_NAME, environment=ENVIRONMENT)

@app.route("/dbcheck")
def dbcheck():
    conninfo = f"host={DB_HOST} port={DB_PORT} user={DB_USER} password={DB_PASSWORD} dbname={DB_NAME} connect_timeout=3"
    try:
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM shipments;")
                return jsonify(db="connected", shipments=cur.fetchone()[0])
    except Exception as e:
        return jsonify(db="error", detail=str(e)), 500


@app.route("/shipments")
def shipments():
    conninfo = f"host={DB_HOST} port={DB_PORT} user={DB_USER} password={DB_PASSWORD} dbname={DB_NAME} connect_timeout=3"
    try:
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, status FROM shipments ORDER BY id;")
                return jsonify({r[0]: {"origin": "-", "destination": "-", "status": r[1]} for r in cur.fetchall()})
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
