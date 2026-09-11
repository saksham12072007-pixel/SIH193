# KrishiMitra frontend

React/Vite frontend for the FastAPI crop advisory backend.

## Development

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The Vite development server runs on port `3000` and proxies API requests under `/api` to `http://127.0.0.1:8000`. This keeps frontend routes such as `/dashboard` from being intercepted by FastAPI. Set `VITE_API_BASE_URL` for a deployed backend.

## Local database

The backend uses `backend/crop_advisory.db` (SQLite) for local development. From
the backend directory, apply migrations and seed the demo records with:

```powershell
.\.venv\Scripts\python.exe scripts\dev_bootstrap.py
```

Start the backend before the frontend and verify both database readiness and
frontend proxy connectivity:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/ready
Invoke-WebRequest http://127.0.0.1:3000/ready
```

For production, set the backend `DATABASE_URL` to PostgreSQL/PostGIS and run
`alembic upgrade head` as an explicit deployment step. The repository-level
`docker-compose.postgis.yml` provides a PostgreSQL 16 + PostGIS 3.4 instance
plus containerized backend and frontend services for local/staging integration:

```powershell
cd ..
$env:POSTGRES_PASSWORD = "replace-with-a-strong-password"
$env:SECRET_KEY = "replace-with-a-random-secret-at-least-32-characters"
docker compose -f docker-compose.postgis.yml up -d --build
Invoke-WebRequest http://127.0.0.1:8080/
Invoke-WebRequest http://127.0.0.1:8000/ready
```

Never seed demo data or commit database credentials to source control.

The frontend includes institutional authentication and self-signup, protected routing, role-aware navigation, a responsive application shell, dashboard analytics, maps, alerts, inspections, ingestion, advisory workflows, dataset imports, model monitoring, data-quality reporting, and admin user provisioning.

## Backend contract

The client uses the FastAPI routes registered in `backend/app/main.py`. It sends the institutional JWT as a bearer token and expects the backend error envelope containing `detail`, `error.message`, and an optional `request_id`. Keep `VITE_API_BASE_URL` empty for the local Vite proxy or set it to the deployed API origin.

### Frontend endpoint inventory

The current UI calls these backend route groups:

- Auth: `/institutional/login`, `/institutional/signup`, `/institutional/me`
- Dashboard: `/dashboard/aggregates`, `/dashboard/analytics`, `/dashboard/model-health`
- Operations: `/institutional/operations/status`
- Plots and history: `/institutional/plots/map`, `/institutional/plots/{plot_id}/history`
- Alerts and rules: `/institutional/alerts`, `/institutional/alert-rules`
- Inspections: `/institutional/inspections`
- ML and ingestion: `/predictions/*`, `/advisories/*`, `/ingest/*`
- Data and monitoring: `/api/datasets/datasets/upload`, `/institutional/data-quality`, `/model/*`
- Readiness: `/health`, `/ready`

## Production checks

```powershell
npm run lint
npm run build
```

For a deployment build, provide the public API origin before building:

```powershell
$env:VITE_API_BASE_URL = "https://api.example.com"
npm ci
npm run check
npm run preview
```

The generated `dist` directory can be served by any static host. Configure the
backend CORS allow-list for the deployed frontend origin, and configure the
host to fall back to `index.html` for client-side routes such as `/analytics`
and `/users`. Do not commit production `.env` files or access tokens.
