# 17 — Remaining Work by Team (Backlog)

> Point-in-time gap analysis (2026-09-08) of the current codebase against the documentation
> suite (`01`–`08`, `11`–`16`). Evidence references point at the exact files that show each
> gap. Ownership follows `16_Phase_1_Production_Baseline.md` (Saksham Sharma & Arnendu
> Biswas — engineering, Shankar Adhikary — agronomy/ML thresholds, Pratham & Saumya —
> product, Riti Patel — field ops).

## Status snapshot

| Team | Built (verified in code) | Remaining (this doc) |
|---|---|---|
| Backend / SDE | FastAPI app, 15 routers, 5 migrations, JWT auth, Twilio adapter, NIR integration, bounded SMS retry, 15 test files | Scheduler, production deploy, retention jobs, Marathi templates, DLT |
| GIS / Data | Canonical `plot_features`, date-snapping, outlier rejection, live GEE S2+S1 + Open-Meteo provider | Cloud-mask SAR fallback (in progress), SMAP/IMD sources, 48h forecast, buffer config, PostGIS |
| ML | Water-balance fallback, XGBoost Stage-1 training (temporal split, FPR gate, SHAP), evaluation service, Stage-2 rules, model monitoring | Train on real data, per-zone models, agronomy thresholds, ablation study |
| Frontend | React dashboard wired to auth/registry/map/alerts/operations APIs | Mock-to-API migration for 4 views, model-health panel, RBAC alignment, a11y pass |
| Product / Field / QA | Frozen pilot scope, seed scripts, runbook | Governance decisions, procurement, DLT, staging verification, field onboarding |

---

## 1. Backend / SDE (Saksham & Arnendu)

| # | Work item | Priority | Evidence / Done-when |
|---|---|---|---|
| 1.1 | **Ingestion/pipeline scheduler** — no cron/Airflow/APScheduler exists; the 3–5 day per-plot cadence (TRD §6), weekly retraining, and the 30-min SMS retry are manual `POST /internal/*` calls today | P0 — **done 2026-09-08** | `PipelineScheduler` in `backend/app/services/pipeline_scheduler.py` (stdlib threading, no new deps) drives pipeline / sms_retry / retraining jobs on the TRD cadences; enabled via `SCHEDULER_ENABLED=true` and wired into the FastAPI lifespan (`app/main.py`). Job bodies are the shared `run_*` functions in `app/routers/internal.py` (endpoints gained an optional `plot_ids` scope for consistency). Per-plot cadence default 96h (`PLOT_INGESTION_CADENCE_HOURS`). 6 tests in `backend/tests/test_scheduler.py` |
| 1.2 | **Production deployment** — PostGIS never deployed; hosting/region/DB not selected (doc 16); `alembic upgrade head` must run as a deploy step; GiST indexes unverified on Postgres | P0 | Staging/prod boots on `DATABASE_URL` (Postgres) with migrations applied and readiness checks green |
| 1.3 | **Retention & DPDP jobs** — nothing enforces doc 06 §5 (36mo raw satellite data, 12mo SMS body purge, 24mo anonymization post-deactivation); PII encryption-at-rest not implemented; deletion endpoint exists but no purge pipeline | P1 | Scheduled retention job + encryption-at-rest for `phone_number`/message bodies |
| 1.4 | **Marathi SMS templates** — `sms_template_service.DEFAULT_TEMPLATES` ships Hindi + English only; pilot languages frozen as Marathi, Hindi, English (doc 16) | P0 | Every reason-code has a vetted Marathi template (PRD AC6.3) |
| 1.5 | **TRAI DLT registration** of exact template content; Twilio sender-ID/WhatsApp template approval; staging execution of `docs/RELEASE_RUNBOOK.md` | P0 | Runbook smoke tests pass in staging with `SMS_PROVIDER=twilio` |

## 2. GIS / Data (M2 track)

| # | Work item | Priority | Evidence / Done-when |
|---|---|---|---|
| 2.1 | **Cloud-mask SAR fallback** — `IngestionService.handle_cloud_mask` was a placeholder (`ingestion_service.py:193`); PRD AC3.2 requires logging a fallback event and proceeding on SAR instead of failing the cycle; AC3.3 requires flagging `data_unavailable` after 2 consecutive empty cycles | P0 — **done 2026-09-08** | `handle_cloud_mask` implemented and wired into `fetch_plot_cycle` (optical / SAR-fallback / degraded outcomes); 5 regression tests in `backend/tests/test_cloud_mask_fallback.py` |
| 2.2 | **SMAP + IMD/NASA POWER + VEDAS live sources** — provider fetches only Sentinel-2 NDVI, Sentinel-1 VV/VH, and Open-Meteo (`ingestion_providers.py`); TRD §2 requires IMD-primary weather fallback order and SMAP as calibration prior | P1 | Live ingestion writes `smap_sm` context feature and IMD-backed weather with documented fallback order |
| 2.3 | **48h rain forecast + Kc/ETc in live path** — live weather records emit empty placeholders `"kc:,etc:,rain_forecast_48h:"` (`ingestion_providers.py:200-205`); rain-forecast-48h is a top-priority feature (doc 13.2) | P1 | `plot_features.rain_forecast_48h`, `kc`, `etc` populate from the live provider |
| 2.4 | **Configurable buffer radius** — live provider hardcodes `point.buffer(100)`; TRD §3.2 specifies 50m default, configurable per crop/region | P2 | Buffer radius comes from settings/crop config |
| 2.5 | **Production PostGIS geometry** — `app/utils/geospatial.py` is an admitted lightweight fallback (doc 15 §15.3); production needs real GEOGRAPHY storage + spatial functions | P1 | Plot geometry stored/queried via PostGIS in staging |
| 2.6 | **Rejected-observation monitoring surfaced** — counts are logged (sec 12.3.3) but not exposed; dashboard data-quality view is mock | P2 | `/institutional/operations/status` or a monitoring endpoint reports rejected/failed ingestion counts |

## 3. ML (M3 track; agronomy gates owned by Shankar)

| # | Work item | Priority | Evidence / Done-when |
|---|---|---|---|
| 3.1 | **Train on real data** — XGBoost Stage-1 has only been trained on synthetic/water-balance labels (`tests/test_ml_training.py`); validate RMSE against the 0.05–0.09 m³/m³ literature benchmark (doc 13.6) | P0 | Evaluation run on live-ingested `plot_features` meets the RMSE target or documents the gap |
| 3.2 | **Agronomy threshold validation per crop** (doc 16 acceptance gate 3): cotton, maize, wheat, rice, sugarcane, groundnut | P0 | Agronomy owner signs off Stage-2 thresholds per crop before any real farmer is live |
| 3.3 | **Per-agro-climatic-zone models** — TRD §3.4/§3.5 requires zone-scoped training; current pipeline trains one global model | P2 | Training job scopes by zone; `model_evaluation_runs.agro_zone` populated |
| 3.4 | **Feature-ablation study** (doc 13.7): SAR-only → +Optical → +Weather → full, for SIH judge credibility | P1 | Ablation table exists in the demo/evaluation notes |
| 3.5 | **Retraining automation** — `/internal/retraining/run` exists but needs the weekly scheduler (see 1.1) | P1 | Weekly retrain runs unattended; promotion gated by FPR |
| 3.6 | **NIR API acceptance checklist** — confidence on every response, immutable `model_version`, batch/rate limits, support owner (`docs/ML_API_CONTRACT.md`) | P1 | Checklist signed off with the ML service team |
| 3.7 | **SMAP-leakage enforcement test** (sec 12.3.2) — verify a unit test proves SMAP can never become `soil_moisture_label` when used as a feature | P2 | Dedicated regression test exists and passes |

## 4. Frontend (M5 track)

| # | Work item | Priority | Evidence / Done-when |
|---|---|---|---|
| 4.1 | **Mock-to-API migration** — `AnalyticsView`, `ReportsView`, `AdminUsersView`, `AdminDataQualityView` still import `src/data/mockDatabase.ts`; `AppContext` seeds farms/farmers/alerts from mock + localStorage | P0 | All listed views read from backend endpoints; mock data used only behind an explicit demo flag |
| 4.2 | **Model-health/monitoring panel** — backend exposes `/model/evaluation`, `/model/evaluation/{version}`, `/model/false-positives/{version}` but `src/services/api.ts` never calls them (doc 12.5: FPR/RMSE trends, confusion matrix, false-positive drilldown) | P1 | Dashboard model-health view renders evaluation runs + FPR trend + drilldown |
| 4.3 | **RBAC alignment** — frontend roles (ADMIN/DISTRICT_OFFICER/FIELD_OFFICER/ANALYST) don't match backend RBAC (kvk_viewer/state_dept_viewer/fpo_viewer/admin) | P1 | UI roles map 1:1 to backend roles; server-side scoping drives visible data |
| 4.4 | **Aggregation-threshold UI** — "insufficient data" cells (PRD AC10.1) not shown in backend-driven views (doc 05 §8) | P2 | Sub-threshold geographies render a distinct neutral state |
| 4.5 | **Real map layer** — `InteractiveGisMap.tsx` is custom SVG without map tiles/geography; docs specify React + Leaflet with low-bandwidth tiles | P2 | Plot markers/geo context render on a real basemap under 2G/3G conditions |
| 4.6 | **server.ts hygiene** — `/api/health` reports fake statuses ("satellite_stream: live", "database: connected"); Gemini farm-insight endpoint needs a product decision (integrate or remove) | P2 | Health endpoint proxies real backend status; AI endpoint intentionally kept or removed |
| 4.7 | **Accessibility & localization pass** (doc 05 §7): 44px targets, contrast, regional-script rendering, dashboard language toggle; P2 WhatsApp companion is lowest priority | P2 | Checklist from doc 05 §7 verified on low-end Android |

## 5. Product / Field Ops / QA

| # | Work item | Owner | Done-when |
|---|---|---|---|
| 5.1 | Governance decisions (doc 16): cloud/hosting + region, pilot-ready date, production DB + comms providers, risk owner + review cadence, final agronomy thresholds | Pratham/Saumya | All six decisions recorded and approved |
| 5.2 | Procurement: SMS/WhatsApp/IVR provider account, DLT registration, maps/geocoding provider (none exists in the backend today), production DB, hosting | Pratham/Saumya | Accounts live; credentials in deployment secrets only |
| 5.3 | QA: execute `backend/docs/RELEASE_RUNBOOK.md` smoke tests; reproducible staging from documented steps (doc 16 gate 5); security/privacy verification (gate 4) | Saksham/Arnendu + QA | All runbook gates pass in staging |
| 5.4 | Field ops: village coordination for the 10 frozen Yavatmal villages, KVK field-agent onboarding, in-field consent capture (DPDP) | Riti | Pilot cohort registered with logged consent |
| 5.5 | Product sign-off on farmer-facing messages in Marathi/Hindi/English (release gate) | Pratham/Saumya | Signed template approval recorded |

## 6. Cross-cutting

- **Test isolation fixed (2026-09-08):** `tests/conftest.py` now forces `SMS_PROVIDER=mock` / `INGESTION_PROVIDER=mock` so a local `backend/.env` with live Twilio credentials can no longer leak into the test suite (was causing 3 tests to call the real Twilio API). `SoilMoistureModel` also accepts an injectable `artifacts_dir` (production default unchanged), fixing the promoted-artifact serving mismatch.
- **Pipeline scheduler shipped (2026-09-08):** item 1.1 above. Enabled by setting `SCHEDULER_ENABLED=true` (+ optional `SCHEDULER_POLL_SECONDS`, `SCHEDULER_PIPELINE_INTERVAL_MINUTES`, `PLOT_INGESTION_CADENCE_HOURS`, `SCHEDULER_SMS_RETRY_INTERVAL_MINUTES`, `SCHEDULER_RETRAINING_INTERVAL_HOURS`). Default remains off so local dev and multi-worker deployments are unaffected until explicitly enabled.
- Full backend suite: **60 passed** (was 54 before the scheduler work).
- `Required Docx` 09 and 10 do not exist (numbering skips 08 → 11); write or renumber if they were intended deliverables.
- Demo hygiene: `seed_demo_data.py` / `seed_india_dataset.py` rows are `synthetic_demo`-marked and must never reach staging/production (doc 16).

## Priority order (critical path)

1. **3.1 + 3.2 Real-data training + agronomy thresholds** — core pilot credibility (next highest after 1.1 and 2.1, both done this sprint).
2. **1.4 + 1.5 Marathi templates + DLT/provider procurement + staging runbook** — legal, verified SMS path.
3. **4.1 Frontend mock-to-API migration** — dashboard truthfulness for reviews.
4. **1.2 Production deployment** (PostGIS, hosting, migrations-as-deploy-step) — unblocks everything above in staging.
5. **3.5 + 1.3 Retraining automation (now scheduled) + retention/DPDP jobs** — production hygiene.

