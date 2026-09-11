# Deploying to Render + Supabase

The database and the app run on two different platforms:

- **Supabase** — managed Postgres only. It does not run this app's Python
  code; it's just where `DATABASE_URL` points.
- **Render** — runs the actual app, as two services defined in `render.yaml`:
  - `crop-advisory-backend` — the FastAPI app (`backend/Dockerfile`), migrated
    via a pre-deploy step (`alembic upgrade head`), never on app startup.
  - `crop-advisory-frontend` — the built React app served by nginx
    (`frontend/Dockerfile`).

PostGIS is not required — the app stores plot coordinates as plain WKT text,
not a real geometry column, so Supabase's default Postgres (no extensions
needed) is sufficient for current functionality.

## 0. Create the Supabase project and get a connection string

1. [supabase.com](https://supabase.com) → sign in → **New project**. Pick any
   name/region (closer to your users is fine) and set a strong database
   password — you'll need it in the connection string below.
2. Wait for provisioning (a couple of minutes), then open the project →
   **Project Settings** (gear icon, bottom left) → **Database**.
3. Under **Connection string**, pick the **URI** tab. Use the **Session
   pooler** connection string (or the direct connection, both on port 5432 by
   default) — not the **Transaction pooler** (port 6543), which doesn't
   support the prepared statements SQLAlchemy may issue.
4. Copy it — it looks like
   `postgresql://postgres.xxxxxxxx:[YOUR-PASSWORD]@aws-0-xx-xxxx-1.pooler.supabase.com:5432/postgres`
   — and replace `[YOUR-PASSWORD]` with the password from step 1. This whole
   string is your `DATABASE_URL`; the app already normalizes Supabase's
   `postgresql://` scheme to the `psycopg` driver it uses, no edits needed.

## 1. Push this repo to GitHub

```bash
git remote add origin <your-github-repo-url>
git branch -M main
git push -u origin main
```

(Already done, per your last message — skip if so.)

## 2. Create the Blueprint on Render

1. Render dashboard → **New +** → **Blueprint**.
2. Connect your GitHub account/repo if you haven't already, then select this repo.
3. Render detects `render.yaml` and lists the two app services (no database —
   Supabase is external to Render now).
4. You'll be prompted to fill in every `sync: false` env var before the first
   deploy:
   - `DATABASE_URL` → the Supabase connection string from step 0.
   - `FRONTEND_ALLOWED_ORIGINS` and `VITE_API_BASE_URL` → fine as placeholders
     for now (e.g. `https://placeholder`), corrected in step 4 below since
     neither Render service has a URL yet.
5. Click **Apply**. Render builds and deploys both services against your
   Supabase database.

## 2b. Apply database migrations

Render's free plan doesn't support pre-deploy commands, so this project's
`render.yaml` no longer runs `alembic upgrade head` automatically (see
`backend/README.md` for why migrations never run from app startup either).
**The backend will come up "healthy" on `/health` but every DB-backed request
will fail with an empty schema until you run this manually** — do it once
right after the first Apply, and again after any deploy that adds a new
migration:

```bash
cd backend
DATABASE_URL="<your Supabase connection string from step 0>" alembic upgrade head
```

`GET /ready` on the backend will return `503` until this has been run
successfully.

## 3. Note the two service URLs

Once both services are live, Render shows each one's URL, e.g.:

- Backend: `https://crop-advisory-backend-xxxx.onrender.com`
- Frontend: `https://crop-advisory-frontend-xxxx.onrender.com`

## 4. Wire the two services together

The frontend and backend each need to know the other's real URL — this can't
be known until step 3, which is why these two are `sync: false` placeholders
in the blueprint:

1. Backend service → **Environment** → set `FRONTEND_ALLOWED_ORIGINS` to the
   frontend's URL from step 3 (comma-separated if you add more origins later)
   → save (triggers a redeploy; no rebuild needed, it's a runtime var).
2. Frontend service → **Environment** → set `VITE_API_BASE_URL` to the
   backend's URL from step 3 → save. **This one requires a rebuild** — Render
   passes it in as a Docker build `ARG` (see `frontend/Dockerfile`), since
   Vite bakes `import.meta.env.VITE_API_BASE_URL` into the static bundle at
   build time. Trigger **Manual Deploy → Clear build cache & deploy** if it
   doesn't rebuild automatically.

## 5. Create the first admin account

Self-service signup (`POST /institutional/signup`, used by the frontend's
Sign Up page) always creates a `field_officer` account with no assigned
geography — by design, so nobody can self-grant themselves visibility into
data outside their region. There is deliberately no self-serve way to become
`admin`.

To create just an admin account (no demo data) in the new production
database, run this from your machine against the same Supabase connection
string from step 0:

```bash
cd backend
DATABASE_URL="<your Supabase connection string>" python -c "
from app.db.database import SessionLocal
from app.models import InstitutionalUser
from app.core.auth import hash_password
import uuid
db = SessionLocal()
db.add(InstitutionalUser(user_id=str(uuid.uuid4()), email='you@example.com', password_hash=hash_password('ChangeThisPassword123!'), role='admin', assigned_geography={}))
db.commit()
print('Admin account created.')
"
```

Only run `python scripts/seed_india_dataset.py` against production if you
actually want ~2500 rows of clearly-marked synthetic demo data seeded in —
useful for a pitch/demo deployment, not for a real pilot database.

This creates `demo@krishimitra.example.com` / `DemoPassword123!` as an
`admin` account, plus the synthetic pilot dataset. Skip this if you'd rather
start with an empty production database — just adjust the script or write a
one-off equivalent to create a single `role="admin"` user instead.

## Known limitations of this deployment

- **Render's free plan has no persistent disk.** `MODEL_ARTIFACTS_DIR`
  (trained model `.joblib` files) will not survive a redeploy or restart —
  this matches an existing gap noted in the project's own docs (models are
  trained via `/internal/retraining/run` and re-trained state is currently
  ephemeral outside of a real disk or object storage). Not something this
  pass attempts to fix.
- **`ENABLE_SCHEDULER` defaults to `false`.** Render's free plan can idle
  after inactivity, which would silently stop a background scheduler anyway;
  turn it on only once you're on a plan that stays warm, or trigger the
  `/internal/*` pipeline endpoints from an external cron instead.
- **SMS/IVR/live satellite ingestion default to `mock`.** Set `SMS_PROVIDER`,
  `INGESTION_PROVIDER`, and the related credentials once real Twilio/GEE
  accounts are ready — `config.py` enforces the required Twilio vars are all
  present before it will accept `SMS_PROVIDER=twilio` in production.
