# 14 — Backend Guide for All Teams

> This document is meant for product, mobile, frontend, data, QA, and operations teams that need a clear view of what the backend does, how it is structured, which APIs exist, and how other components should integrate with it.

---

## 14.1 Purpose of the Backend

The backend is the central service layer for the crop advisory platform. It stores farmer and plot records, ingests satellite and weather data, computes plot-level features, runs the moisture and advisory pipeline, records feedback, and exposes dashboard and monitoring APIs for institutional users.

It is built as a FastAPI application with SQLAlchemy-backed persistence. The codebase is structured as an initial working implementation that already supports the main end-to-end flow, while still leaving room for future production hardening.

---

## 14.2 Technology Stack

- Python 3.13+
- FastAPI for HTTP APIs
- SQLAlchemy and Pydantic for persistence and validation
- PostgreSQL + PostGIS in production
- SQLite fallback for local development and smoke testing
- Alembic for database migrations

The app starts from `app/main.py`, which wires routers, middleware, exception handling, and health checks.

---

## 14.3 High-Level Architecture

The backend follows a pipeline-oriented design:

1. Farmer and plot onboarding
2. Satellite/weather ingestion
3. Canonical feature-row creation per plot and date
4. Soil-moisture estimation
5. Rule-based advisory generation
6. SMS / IVR / messaging delivery
7. Farmer feedback capture
8. Dashboard and model-monitoring support

The architecture docs in this workspace describe the intended full data flow in detail. The backend implementation reflects that design through separate router and service modules, especially for ingestion, predictions, advisories, and model monitoring.

---

## 14.4 Main Backend Modules

### Application entrypoint

- `app/main.py` creates the FastAPI app.
- It registers routers for farmers, plots, commands, ingestion, predictions, advisories, institutional auth, messages, internal operations, dashboard, soil moisture, and model monitoring.
- It also defines request logging, request IDs, and structured exception handlers.

### Database layer

- `app/db/database.py` configures the SQLAlchemy engine and session factory.
- SQLite is used automatically for local work when the configured database URL points to SQLite.
- PostgreSQL/PostGIS is the intended production target.

### Domain routers

- `app/routers/farmers.py` handles farmer registration, lookup, session creation, and deletion.
- `app/routers/plots.py` manages plot creation and plot lookup.
- `app/routers/ingestion.py` handles satellite ingestion, feature lookup, and weak-label generation.
- `app/routers/soil_moisture.py` exposes the Stage 1 moisture endpoint.
- `app/routers/predictions.py` exposes irrigation-stress prediction and explanation endpoints.
- `app/routers/advisories.py` generates advisories and stores farmer feedback.
- `app/routers/messages.py` handles SMS send, inbound SMS, delivery webhooks, and IVR callbacks.
- `app/routers/commands.py` parses farmer commands into structured actions.
- `app/routers/dashboard.py` provides aggregate, trend, and model-health views.
- `app/routers/model_monitoring.py` exposes evaluation and false-positive drilldown APIs.
- `app/routers/institutional_auth.py` supports institutional user signup, login, and profile retrieval.
- `app/routers/internal.py` exposes internal batch triggers such as ingestion, prediction runs, advisory generation, retraining, and SMS retry.

### Service layer

- `app/services/ingestion_service.py` handles data fetching and ingestion orchestration.
- `app/services/plot_features_service.py` manages canonical plot feature rows.
- `app/services/ml_prediction_service.py` and `app/services/water_balance_model.py` support moisture estimation and decision logic.
- `app/services/advisory_service.py` and `app/services/sms_template_service.py` create user-facing advisories.
- `app/services/messaging_service.py` and `app/services/sms_session_service.py` manage outbound and inbound messaging workflows.
- `app/services/model_evaluation_service.py` stores and serves model evaluation results.
- `app/services/compliance_service.py` and `app/utils/audit.py` support logging and compliance-oriented behavior.

---

## 14.5 Data and Storage Model

The backend is centered around a farmer/plot registry and a plot-level feature store.

Important data concepts include:

- Farmer records with contact and consent details
- Plot records tied to a farmer, with geospatial information
- Satellite and weather observations
- Canonical plot feature rows keyed by plot and observation date
- Soil moisture labels from the weak-label or feedback pipeline
- Advisory records and farmer replies
- Institutional accounts and evaluation runs

The architecture docs describe `plot_features` as the canonical per-plot-per-date row. This is the key object for model training, evaluation, and traceability.

Key design rule: source data should be date-aligned before merging. The backend should not silently mix observations from mismatched acquisition dates into one training row.

---

## 14.6 Core API Surface

Below is the main API surface other teams should expect.

### Health and readiness

- `GET /health` returns a basic service status.
- `GET /ready` performs a real database connectivity check.

### Farmers

- `POST /farmers/register`
- `POST /farmers/session`
- `GET /farmers/{farmer_id}`
- `GET /farmers/by-phone/{phone_number}`
- `DELETE /farmers/{farmer_id}`

### Plots

- `POST /plots/create`
- `GET /plots/{farmer_id}`
- `GET /plots/plot/{plot_id}`

### Commands

- `POST /commands/parse`

### Ingestion

- `POST /ingest/{plot_id}` triggers ingestion for a plot.
- `GET /ingest/latest/{plot_id}` returns the latest raw observations.
- `GET /ingest/features/{plot_id}/{obs_date}` returns the canonical feature row.
- `POST /ingest/water-balance-labels/{plot_id}` runs weak-label generation.
- Legacy compatibility is kept for `POST /ingestion/trigger/{plot_id}`.

### Soil moisture and predictions

- `POST /soil-moisture/{plot_id}` returns Stage 1 moisture output.
- `POST /predictions/irrigation-stress/{plot_id}` creates a prediction record.
- `GET /predictions/explain/{prediction_id}` returns explanation data.
- `GET /predictions/latest/{plot_id}` returns the latest prediction.

### Advisories and feedback

- `POST /advisories/generate/{plot_id}` generates an advisory.
- `GET /advisories/{advisory_id}` fetches an advisory.
- `POST /advisories/feedback/{advisory_id}` records farmer feedback.

### Messages

- `POST /sms/send`
- `POST /sms/webhook/delivery`
- `POST /sms/inbound`
- `POST /sms/ivr`

### Institutional and internal operations

- `POST /institutional/signup`
- `POST /institutional/login`
- `GET /institutional/me`
- `POST /internal/ingestion/trigger`
- `POST /internal/predictions/run`
- `POST /internal/advisories/generate`
- `POST /internal/retraining/run`
- `POST /internal/sms/retry`

### Dashboard and monitoring

- `GET /dashboard/aggregates`
- `GET /dashboard/trends`
- `GET /dashboard/model-health`
- `GET /model/evaluation/{model_version}`
- `GET /model/evaluation`
- `GET /model/false-positives/{model_version}`
- `POST /model/evaluation`

---

## 14.7 Request and Response Behavior

The backend uses structured error handling instead of returning raw server errors.

- Validation errors return a standardized `422` response with a request ID.
- Application `ValueError` exceptions are mapped to `400` responses.
- FastAPI `HTTPException` responses are normalized into a consistent error envelope.
- Unhandled exceptions are logged and returned as a controlled `500` response.

Every request receives or generates an `x-request-id` header. This makes it easier for QA, support, and operations teams to trace a failing request through logs.

---

## 14.8 Ingestion and Feature Flow

The ingestion pipeline is one of the most important backend responsibilities.

What it does:

1. Validates that the plot exists
2. Pulls satellite and related data for the plot cycle
3. Aligns observations to a canonical plot/date row
4. Applies cloud and quality filtering where needed
5. Writes or updates the feature record
6. Makes the canonical row available to prediction and advisory services

Important integration note:

- `plot_features` is the audit-friendly record used by downstream model jobs.
- SMAP should be treated as a feature or calibration prior, not as the label source.
- The weak-label generator is separated so the backend can distinguish model inputs from model targets.

---

## 14.9 Advisory and Messaging Flow

Advisory generation is not just an ML output. It is a controlled pipeline:

1. Stage 1 estimates soil moisture or stress.
2. Stage 2 applies rule-based decision logic.
3. A reason code is selected.
4. A vetted template is rendered into a human message.
5. The message is sent through the delivery channel.
6. Farmer response is stored as feedback for future improvement.

The system is designed to keep the final advisory explainable, localized, and traceable.

---

## 14.10 Model Monitoring and Evaluation

The backend includes monitoring endpoints for institutional users and technical teams.

Tracked metrics include:

- Stage 1: RMSE, MAE, R²
- Stage 2: accuracy, precision, recall, F1, FPR
- False-positive drilldown views for audits and debugging

This is important because production promotion should not be based only on accuracy. The system needs visibility into false-positive behavior, especially for advisory decisions that may cause unnecessary irrigation recommendations.

---

## 14.11 Security, Privacy, and Compliance

The backend handles sensitive data such as phone numbers, plot locations, and consent status.

Operational expectations:

- Treat phone numbers and GPS data as PII
- Use consent-aware onboarding flows
- Prefer minimal necessary storage
- Keep institutional access separate from farmer-facing flows
- Preserve request logs and audit trails

The architecture docs also call out production compliance concerns such as SMS sender registration and data minimization.

---

## 14.12 Local Development and Validation

For local development:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload
```

The current backend documentation and tests assume that the backend root is available on `sys.path` during test execution.

Recommended validation command:

```bash
cd backend && pytest -q
```

Local SQLite support means the app can boot without a production database, but production/staging should use PostgreSQL with the correct `DATABASE_URL` configured.

---

## 14.13 Notes for Other Teams

### Frontend team

- Use the canonical API surface and do not depend on private internal endpoints unless agreed.
- Expect request IDs in headers for troubleshooting.
- Dashboard and monitoring pages should consume the model-health and evaluation endpoints rather than re-deriving metrics in the UI.

### Mobile and messaging team

- SMS and IVR are first-class channels.
- Inbound SMS commands are converted into structured actions by the backend.
- Delivery webhooks should be handled as part of the messaging lifecycle, not as separate ad hoc callbacks.

### Data and ML team

- Use canonical plot/date feature rows for training and inference.
- Keep feature engineering aligned with the ingestion pipeline.
- Track model versions and evaluation runs so metrics can be traced later.

### QA team

- Validate `/health` and `/ready` first.
- Test farmer, plot, ingestion, prediction, advisory, and feedback flows together, not only as isolated endpoints.
- Verify backward compatibility for the legacy `/ingestion/trigger/{plot_id}` path if older integrations still use it.

### Operations team

- Monitor request IDs and structured logs.
- Keep an eye on database readiness and message delivery failure handling.
- Use the internal triggers for controlled batch execution where needed.

---

## 14.14 Current State and Scope

This backend is already organized around the intended production flow, but it should still be treated as a strong implementation baseline rather than a fully hardened deployment.

The main strengths of the current codebase are:

- Clear separation of routers and services
- Canonical ingestion and feature-row handling
- Structured request/error handling
- Explicit model-monitoring endpoints
- Support for both production-style and local-development database setups

The main expectation for future work is to keep the data flow auditable, the advisory pipeline explainable, and the public API stable for other teams.
