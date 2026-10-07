"""Guestbook worker.

Uses only Dapr building blocks:
  * Pub/Sub subscription -> receives entries from the topic (via dapr-ext-flask)
  * Output binding       -> reads/writes PostgreSQL (no database driver in this code)
  * Service invocation   -> exposes GET /entries to the frontend
Run several instances with the same app-id to scale out; Dapr spreads messages across them.
"""
import json
import os
import threading

from dapr.clients import DaprClient
from dapr.ext.flask import DaprApp
from flask import Flask, jsonify, request

PUBSUB_NAME = os.getenv("PUBSUB_NAME", "guestbook-pubsub")
TOPIC_NAME = os.getenv("TOPIC_NAME", "entries")
DB_BINDING = os.getenv("DB_BINDING", "guestbook-db")
APP_PORT = int(os.getenv("APP_PORT", "5001"))
MAX_ENTRIES = 100

app = Flask(__name__)
dapr_app = DaprApp(app)

_schema_ready = False
_schema_lock = threading.Lock()


def db(operation, sql, params=None):
    """Run SQL through the Dapr PostgreSQL output binding ('exec' or 'query')."""
    metadata = {"sql": sql}
    if params is not None:
        metadata["params"] = json.dumps(params)
    with DaprClient() as client:
        resp = client.invoke_binding(
            binding_name=DB_BINDING,
            operation=operation,
            binding_metadata=metadata,
        )
    return resp.data


def ensure_schema():
    """Create the table on first use (the sidecar is not ready at import time)."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if not _schema_ready:
            db(
                "exec",
                """CREATE TABLE IF NOT EXISTS guestbook_entries (
                       id         BIGSERIAL PRIMARY KEY,
                       event_id   TEXT UNIQUE NOT NULL,
                       message    TEXT NOT NULL,
                       created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                   )""",
            )
            _schema_ready = True


@dapr_app.subscribe(pubsub=PUBSUB_NAME, topic=TOPIC_NAME)
def on_entry():
    event = request.get_json(force=True)  # CloudEvent envelope added by Dapr
    data = event.get("data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    message = (data.get("message") or "").strip()[:500]
    if not message:
        return jsonify(status="DROP")  # invalid message: don't redeliver

    try:
        ensure_schema()
        # Pub/sub is at-least-once; the CloudEvent id makes the insert idempotent.
        db(
            "exec",
            "INSERT INTO guestbook_entries (event_id, message) VALUES ($1, $2) "
            "ON CONFLICT (event_id) DO NOTHING",
            [event["id"], message],
        )
    except Exception as exc:
        app.logger.error("Saving entry failed, asking Dapr to retry: %s", exc)
        return jsonify(status="RETRY")

    return jsonify(status="SUCCESS")


@app.get("/entries")
def list_entries():
    ensure_schema()
    raw = db(
        "query",
        "SELECT id, message, "
        "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') "
        "FROM guestbook_entries ORDER BY id DESC LIMIT $1",
        [MAX_ENTRIES],
    )
    rows = json.loads(raw or b"[]")
    # The binding returns each row as an array of column values.
    entries = [
        {"id": r[0], "message": r[1], "created_at": f"{r[2]} UTC"} for r in rows
    ]
    return jsonify(entries)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)
