# Dapr guestbook (Python + Flask)

```
browser ──POST──> frontend ──publish──> [Dapr pub/sub: guestbook-pubsub / entries]
                     │                              │
                     │ service invocation           ▼ subscription
                     └──GET /entries──────────> worker ──output binding──> PostgreSQL
```

The application code contains no Redis, Postgres or HTTP-to-other-service
code. Everything goes through the Dapr sidecar:

| Concern            | Dapr building block                | Where                        |
|--------------------|------------------------------------|------------------------------|
| Queue an entry     | Pub/Sub `publish_event`            | `frontend/app.py`            |
| Process entries    | Pub/Sub subscription               | `worker/app.py` `on_entry`   |
| Save / read rows   | Output binding `bindings.postgresql` | `worker/app.py` `db()`     |
| Read last 100      | Service invocation `invoke_method` | frontend -> worker `/entries`|

Change the broker or database by editing `components/*.yaml`; the Python stays the same.

## Run on an Ubuntu VM

```bash
make install   # system packages, Docker, Dapr CLI, Python venv (asks for sudo)
make init      # dapr init + PostgreSQL
make run       # http://localhost:5000
```

`make help` lists all targets (`stop`, `db-down`, `clean`, `uninstall-dapr`).

## Run manually

Prerequisites: Docker, the [Dapr CLI](https://docs.dapr.io/getting-started/install-dapr-cli/), Python 3.10+.

```bash
dapr init                      # starts Redis, placement, zipkin
docker compose up -d           # starts PostgreSQL
pip install -r requirements.txt
dapr run -f .                  # starts frontend + worker with sidecars
```

Open http://localhost:5000. The page refreshes every 5 seconds (`REFRESH_SECONDS`).

### Scale the workers

Start extra workers with the same app-id; Dapr treats them as one consumer group:

```bash
cd worker
dapr run --app-id guestbook-worker --app-port 5002 --resources-path ../components -- \
  env APP_PORT=5002 python3 app.py
```

## Notes

- Delivery is at-least-once; the worker uses the CloudEvent id as a unique key so
  redelivered messages are not stored twice.
- On a database error the worker returns `RETRY` and Dapr redelivers; empty
  messages return `DROP`.
- The table is created on first use.
- The DB password in `components/guestbook-db.yaml` is a local demo value. Use a
  Dapr secret store (`secretKeyRef`) outside local development.
