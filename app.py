import os
import sqlite3
import subprocess
from flask import Flask, g, jsonify, render_template, request, abort

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", "/data/display.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT NOT NULL DEFAULT 'single',
            interval_secs INTEGER NOT NULL DEFAULT 30,
            active_url_id INTEGER REFERENCES urls(id) ON DELETE SET NULL,
            menu_active INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("INSERT OR IGNORE INTO config (id, mode, interval_secs) VALUES (1, 'single', 30)")
    for migration in [
        "ALTER TABLE config ADD COLUMN menu_active INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE config ADD COLUMN now_playing_url_id INTEGER REFERENCES urls(id) ON DELETE SET NULL",
        "ALTER TABLE config ADD COLUMN monitor_on INTEGER NOT NULL DEFAULT 1",
    ]:
        try:
            db.execute(migration)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    db.commit()
    db.close()


# --- Kiosk & Admin pages ---

@app.route("/kiosk")
def kiosk():
    return render_template("kiosk.html")


@app.route("/admin")
@app.route("/")
def admin():
    return render_template("admin.html")


# --- API ---

@app.route("/api/config", methods=["GET"])
def get_config():
    db = get_db()
    row = db.execute("""
        SELECT c.mode, c.interval_secs, c.active_url_id, c.monitor_on,
               c.now_playing_url_id,
               u.id AS u_id, u.label AS u_label, u.url AS u_url,
               np.id AS np_id, np.label AS np_label, np.url AS np_url
        FROM config c
        LEFT JOIN urls u  ON u.id  = c.active_url_id
        LEFT JOIN urls np ON np.id = c.now_playing_url_id
        WHERE c.id = 1
    """).fetchone()
    urls = db.execute("SELECT * FROM urls ORDER BY position, id").fetchall()
    active = None
    if row["u_id"]:
        active = {"id": row["u_id"], "label": row["u_label"], "url": row["u_url"]}
    now_playing = None
    if row["np_id"]:
        now_playing = {"id": row["np_id"], "label": row["np_label"], "url": row["np_url"]}
    return jsonify({
        "mode": row["mode"],
        "interval_secs": row["interval_secs"],
        "active_url": active,
        "now_playing": now_playing,
        "monitor_on": bool(row["monitor_on"]),
        "urls": [{"id": r["id"], "label": r["label"], "url": r["url"]} for r in urls],
    })


@app.route("/api/config", methods=["PUT"])
def update_config():
    data = request.get_json(force=True)
    db = get_db()
    cfg = db.execute("SELECT * FROM config WHERE id = 1").fetchone()

    mode = data.get("mode", cfg["mode"])
    if mode not in ("single", "cycle"):
        abort(400, "mode must be 'single' or 'cycle'")

    interval_secs = data.get("interval_secs", cfg["interval_secs"])
    try:
        interval_secs = int(interval_secs)
        if interval_secs < 5:
            abort(400, "interval_secs must be >= 5")
    except (TypeError, ValueError):
        abort(400, "interval_secs must be an integer")

    active_url_id = data.get("active_url_id", cfg["active_url_id"])
    if active_url_id is not None:
        exists = db.execute("SELECT id FROM urls WHERE id = ?", (active_url_id,)).fetchone()
        if not exists:
            abort(400, "active_url_id not found")

    db.execute(
        "UPDATE config SET mode=?, interval_secs=?, active_url_id=? WHERE id=1",
        (mode, interval_secs, active_url_id),
    )
    db.commit()
    return get_config()


@app.route("/api/monitor", methods=["POST"])
def monitor_control():
    data = request.get_json(force=True)
    action = data.get("action")
    if action not in ("wake", "sleep"):
        abort(400, "action must be 'wake' or 'sleep'")
    env = {**os.environ, "DISPLAY": ":0"}
    if action == "wake":
        subprocess.run(["xset", "dpms", "force", "on"], env=env, capture_output=True)
        subprocess.run(["xset", "-dpms"], env=env, capture_output=True)
    else:
        subprocess.run(["xset", "dpms", "force", "off"], env=env, capture_output=True)
    db = get_db()
    db.execute("UPDATE config SET monitor_on=? WHERE id=1", (1 if action == "wake" else 0,))
    db.commit()
    return "", 204


@app.route("/api/now-playing", methods=["POST"])
def set_now_playing():
    data = request.get_json(force=True)
    url_id = data.get("url_id")
    db = get_db()
    if url_id is not None:
        exists = db.execute("SELECT id FROM urls WHERE id = ?", (url_id,)).fetchone()
        if not exists:
            abort(400, "url_id not found")
    db.execute("UPDATE config SET now_playing_url_id=? WHERE id=1", (url_id,))
    db.commit()
    return "", 204


@app.route("/api/urls", methods=["GET"])
def list_urls():
    db = get_db()
    rows = db.execute("SELECT * FROM urls ORDER BY position, id").fetchall()
    return jsonify([{"id": r["id"], "label": r["label"], "url": r["url"], "position": r["position"]} for r in rows])


@app.route("/api/urls", methods=["POST"])
def add_url():
    data = request.get_json(force=True)
    label = (data.get("label") or "").strip()
    url = (data.get("url") or "").strip()
    if not url:
        abort(400, "url is required")
    if not url.startswith(("http://", "https://")):
        abort(400, "url must start with http:// or https://")
    if not label:
        label = url
    db = get_db()
    max_pos = db.execute("SELECT COALESCE(MAX(position), -1) FROM urls").fetchone()[0]
    cur = db.execute(
        "INSERT INTO urls (label, url, position) VALUES (?, ?, ?)",
        (label, url, max_pos + 1),
    )
    db.commit()
    row = db.execute("SELECT * FROM urls WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"id": row["id"], "label": row["label"], "url": row["url"], "position": row["position"]}), 201


@app.route("/api/urls/<int:url_id>", methods=["PUT"])
def update_url(url_id):
    db = get_db()
    row = db.execute("SELECT * FROM urls WHERE id = ?", (url_id,)).fetchone()
    if not row:
        abort(404, "URL not found")
    data = request.get_json(force=True)
    label = (data.get("label") or "").strip()
    url = (data.get("url") or "").strip()
    if not url:
        abort(400, "url is required")
    if not url.startswith(("http://", "https://")):
        abort(400, "url must start with http:// or https://")
    if not label:
        label = url
    db.execute("UPDATE urls SET label=?, url=? WHERE id=?", (label, url, url_id))
    db.commit()
    row = db.execute("SELECT * FROM urls WHERE id = ?", (url_id,)).fetchone()
    return jsonify({"id": row["id"], "label": row["label"], "url": row["url"], "position": row["position"]})


@app.route("/api/urls/<int:url_id>", methods=["DELETE"])
def delete_url(url_id):
    db = get_db()
    row = db.execute("SELECT * FROM urls WHERE id = ?", (url_id,)).fetchone()
    if not row:
        abort(404, "URL not found")
    db.execute("DELETE FROM urls WHERE id = ?", (url_id,))
    db.commit()
    return "", 204


@app.route("/api/urls/reorder", methods=["PUT"])
def reorder_urls():
    """Accept ordered list of ids and reassign positions."""
    data = request.get_json(force=True)
    ids = data.get("ids", [])
    if not isinstance(ids, list):
        abort(400, "ids must be a list")
    db = get_db()
    existing = {r["id"] for r in db.execute("SELECT id FROM urls").fetchall()}
    if set(ids) != existing:
        abort(400, "ids must contain exactly the current set of URL ids")
    for pos, url_id in enumerate(ids):
        db.execute("UPDATE urls SET position = ? WHERE id = ?", (pos, url_id))
    db.commit()
    return list_urls()


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=os.environ.get("FLASK_DEBUG") == "1")
