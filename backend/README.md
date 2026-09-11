# Crop Advisory Backend

This backend is the initial implementation of the SIH 2026 crop advisory platform, based on the project documentation in `Required Docx/`.

## Stack

- Python 3.13+
- FastAPI
- PostgreSQL + PostGIS for production
- SQLite fallback for local smoke testing and dev bootstrapping
- SQLAlchemy + Pydantic

## Quick start

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/dev_bootstrap.py   # local SQLite only: migrates + seeds demo data if empty
PYTHONPATH=. uvicorn app.main:app --reload
```

`scripts/dev_bootstrap.py` is the one-command local setup: it runs `alembic
upgrade head` and, if the database has no farmers yet, seeds the demo dataset
(see below). Re-run it any time you delete the local `.db` file or pull
migrations someone else added -- it's idempotent. It refuses to auto-seed
anything when `DATABASE_URL` isn't SQLite.

For a new or upgraded **non-local** database, apply migrations as an explicit
deployment step instead:

```bash
alembic upgrade head
```

### PostgreSQL/PostGIS

The repository includes `../docker-compose.postgis.yml` for a local or staging
PostgreSQL 16 + PostGIS 3.4 instance, plus containerized backend and frontend
services. Docker is required; do not use the development password defaults in a
real deployment.
On first initialization, `database/postgis-init.sql` enables the PostGIS and
PostGIS topology extensions.

```powershell
cd ..
$env:POSTGRES_PASSWORD = "replace-with-a-strong-password"
docker compose -f docker-compose.postgis.yml up -d
docker compose -f docker-compose.postgis.yml ps
```

Compose applies `alembic upgrade head` before starting the backend. The
frontend is then served at `http://127.0.0.1:8080` and the API at
`http://127.0.0.1:8000`. The frontend already
connects to the API through its `/dashboard`, `/institutional`, `/plots`,
`/predictions`, `/api`, `/health`, and `/ready` routes; no browser-to-database
connection is used. Verify the database-backed API before starting the
frontend:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/ready
Invoke-WebRequest http://127.0.0.1:8080/
```

For production, use a managed PostgreSQL/PostGIS service or a secured private
instance, store `DATABASE_URL` in deployment secrets, restrict network access,
enable TLS, and run `alembic upgrade head` as a release step. Never commit
`.env`, database passwords, or seeded demo data.

The API does not run migrations automatically, even on startup -- deliberately,
to avoid migration races against production replicas sharing the same
`DATABASE_URL`. `GET /ready` reflects this: it checks that the core schema
exists and (when Alembic bookkeeping is present) that it's at the code's
expected migration head, returning `503` with an actionable message instead
of silently reporting ready against an empty or stale schema.

### Local dashboard demo data

To populate the local SQLite database with a repeatable, clearly marked
dataset for the institutional dashboard:

```bash
../.venv/bin/python scripts/seed_demo_data.py
```

This creates 50 demo farmers, 70 demo plots across 10 villages in
Yavatmal, Maharashtra, covering cotton, maize, wheat, rice, sugarcane, and
groundnut. It also creates 14 days of advisory history and two model
evaluation versions. The local demo account is:
`demo@krishimitra.example.com` / `DemoPassword123!`. Never run this seed
against a production database.

## Notes

- The app defaults to SQLite locally so the project can boot without a running Postgres instance.
- `/health` and `/health/live` are liveness probes. `/ready` and
  `/health/ready` verify database connectivity and return `503` until the
  database is usable.
- For production or staged environments, set `DATABASE_URL` to a PostgreSQL/PostGIS value in `.env`.
- NIR API configuration and the agreed request/response contract are documented in `docs/ML_API_CONTRACT.md`.
- Communications use `SMS_PROVIDER=mock` locally. Set `SMS_PROVIDER=twilio` and provide
  the `TWILIO_*` secrets in deployment configuration for SMS, WhatsApp, voice calls,
  and signed delivery callbacks. Register the callback URL in Twilio and complete
  India DLT/template approval before sending production SMS.
- Set `ML_API_KEY` in `.env` or deployment secrets to enable the remote predictor; leave it unset to exercise the legacy fallback locally.
- The code is intentionally structured as a strong starter implementation, not a full production deployment.

### India-wide dashboard validation dataset

For a repeatable local load test with every state/UT and the district catalogue
available from the open geometry source, run:

```bash
PYTHONPATH=. ../.venv/bin/python scripts/seed_india_dataset.py \
  --count 2500 --history-days 90 --districts-file /path/to/india_district.geojson
```

The script creates 2,500 farmers and plots, 90 days of daily weather rows,
Sentinel-1/Sentinel-2-shaped observations, 30 days of canonical feature rows,
and 14 days of prediction/advisory history. Rows are prefixed
`india-demo-` and marked `synthetic_demo`; they are for dashboard/model
contract validation only and must not be presented as measured satellite or
weather observations.

The dashboard trend endpoint now returns live environmental aggregates from
`plot_features` alongside advisory counts. To use measured data, configure the
live ingestion provider (`INGESTION_PROVIDER=live`) with Earth Engine
credentials and rerun ingestion; the synthetic rows should then be removed
from the development database before evaluating production model performance.
# Krishi
