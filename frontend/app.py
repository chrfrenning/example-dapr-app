"""Guestbook frontend.

Uses only Dapr building blocks:
  * Pub/Sub            -> publish new entries to a topic (no broker SDK in this code)
  * Service invocation -> ask the worker for the latest 100 entries (no URL or port of the worker)
"""
import html
import json
import os

from dapr.clients import DaprClient
from flask import Flask, redirect, request

PUBSUB_NAME = os.getenv("PUBSUB_NAME", "guestbook-pubsub")
TOPIC_NAME = os.getenv("TOPIC_NAME", "entries")
WORKER_APP_ID = os.getenv("WORKER_APP_ID", "guestbook-worker")
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "5"))
APP_PORT = int(os.getenv("APP_PORT", "5000"))

app = Flask(__name__)

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="{refresh}">
<title>Guestbook</title>
</head>
<body>
<h1>Guestbook</h1>
<form method="post" action="/entries">
<input type="text" name="message" maxlength="500" required autofocus>
<button type="submit">Sign</button>
</form>
{notice}
<h2>Last 100 entries</h2>
{entries}
</body>
</html>
"""


def fetch_entries():
    """Get the latest entries from the worker through Dapr service invocation."""
    with DaprClient() as client:
        resp = client.invoke_method(
            app_id=WORKER_APP_ID,
            method_name="entries",
            http_verb="GET",
        )
    return json.loads(resp.data or b"[]")


@app.get("/")
def index():
    notice = ""
    try:
        entries = fetch_entries()
    except Exception as exc:  # worker or sidecar not reachable yet
        app.logger.warning("Could not load entries: %s", exc)
        entries = []
        notice = "<p>Entries are not available right now.</p>"

    if request.args.get("queued"):
        notice += "<p>Thanks! Your entry has been queued.</p>"

    if entries:
        items = "".join(
            f"<li>{html.escape(e['created_at'])} - {html.escape(e['message'])}</li>"
            for e in entries
        )
        entries_html = f"<ul>{items}</ul>"
    else:
        entries_html = "<p>No entries yet.</p>"

    return PAGE.format(refresh=REFRESH_SECONDS, notice=notice, entries=entries_html)


@app.post("/entries")
def add_entry():
    message = (request.form.get("message") or "").strip()
    if not message:
        return redirect("/", code=303)

    # Fire-and-forget: the worker saves it asynchronously.
    with DaprClient() as client:
        client.publish_event(
            pubsub_name=PUBSUB_NAME,
            topic_name=TOPIC_NAME,
            data=json.dumps({"message": message[:500]}),
            data_content_type="application/json",
        )
    return redirect("/?queued=1", code=303)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=APP_PORT)
