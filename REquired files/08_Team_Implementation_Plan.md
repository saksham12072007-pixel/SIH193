# 08 — 5-Member Team Implementation Plan

Cross-references: all prior documents — this plan sequences the build of every feature/component
specified in `02_...md` through `07_...md`.

---

### 1. Team Roles & Module Ownership

| Member | Role | Owns |
|---|---|---|
| **M1** | Backend & Auth Lead | Farmer/Plot Registry (`farmers`, `plots` tables), Backend API core (FastAPI scaffolding), farmer SMS/USSD command handling (auth model, PRD F1/F2/F7), institutional auth (RBAC) |
| **M2** | Data/GIS Engineer | Satellite Data Ingestion Service (GEE pipeline, Sentinel-1/2, SMAP, Bhuvan/VEDAS, IMD integration), `satellite_data` table, feature engineering (cloud-masking, trend/anomaly, water-balance bucket model) |
| **M3** | ML Engineer | ML Inference Service (Stage-1 regression + Stage-2 rule classifier), `ml_predictions` table, evaluation pipeline, retraining batch job (TRD §3.5) |
| **M4** | Integration & Delivery Engineer | Advisory/Template Engine, `advisories`/`sms_templates` tables, SMS/IVR Gateway integration, `sms_logs`, feedback ingestion (`advisory_feedback`), retry/failure handling (TRD §7) |
| **M5** | Frontend & Localization Lead | Institutional Dashboard (React+Leaflet), WhatsApp/web companion (P2), SMS template authoring workflow + localization review process (`05_...md` §4), UI/UX implementation |

*(Note: agronomy input for Kc-value/threshold validation, referenced as Assumption A7 in
`03_...md`, is treated as an external advisory input coordinated by M3, not a dedicated team seat
— flagged as a real dependency the team must secure, not a role this 5-person team can self-supply.)*

---

### 2. Build Order (dependencies first)

The dependency chain established in `02_...md` §2 drives this sequence:
```
Registry (M1) → Ingestion (M2) → ML (M3) → Advisory+Delivery (M4) → Dashboard/Localization (M5)
```
Localization (SMS templates, M5) and Auth (M1) are foundational and start immediately in parallel
with Registry, since Delivery (M4) cannot go live without vetted templates, and no farmer action
is possible without auth.

---

### 3. Phased Timeline

**Phase 0 — Setup (Days 1–2, all members)**
- Repo scaffolding, environment setup, shared PostgreSQL+PostGIS instance, GEE/Copernicus/NASA
  Earthdata credential provisioning, SMS sandbox account setup.
- Agree on API contracts between modules (schema in `06_...md` reviewed and locked as v1 by all).

**Phase 1 — Foundations (Days 3–7)**
| Member | Task |
|---|---|
| M1 | `farmers`/`plots` tables live; registration flow (SMS/USSD stub + web form) functional end-to-end for a test farmer; buffer-polygon generation (PRD AC2.3) |
| M2 | GEE pipeline pulling Sentinel-1/2 for a hardcoded test plot; `satellite_data` table populated; cloud-mask logic working |
| M3 | Water-balance bucket-model weak-label generator running against M2's sample output (can start on synthetic data before M2 fully lands) |
| M4 | SMS sandbox integration proven (send/receive test message); `sms_templates` table schema live |
| M5 | Language/template governance workflow drafted; first Hindi + 1 regional-language template set drafted for agronomist review; dashboard skeleton (empty map) scaffolded |

**Integration checkpoint 1 (end of Day 7):** M1's plot registration successfully triggers M2's
ingestion pipeline for a real (test) plot. **Owner: M1 + M2 pair.**

**Phase 2 — Core Pipeline (Days 8–16)**
| Member | Task |
|---|---|
| M1 | Farmer self-service commands (MY PLOTS, STATUS, PAUSE/RESUME, LANG) built on top of stable Registry; institutional auth (RBAC) implemented |
| M2 | Full feature engineering layer complete (trend/anomaly, SAR fallback logic, PRD AC3.2); ingestion scheduler (cron/Airflow) running on the defined cadence (TRD §6) |
| M3 | Baseline threshold+Kc rule engine complete (always-available fallback, TRD §3.4); MVP XGBoost regressor trained on M2's real pipeline output; `ml_predictions` table live with model versioning |
| M4 | Advisory/Template Engine built (reason-code → template selection); `advisories` table live; retry/failure handling per TRD §7 |
| M5 | Template review workflow enforced (draft → agronomist → native-speaker → sign-off, blocking activation without all 3, PRD AC6.3); dashboard map rendering real aggregated data from a read-only API endpoint |

**Integration checkpoint 2 (end of Day 16):** end-to-end path proven — a test plot's satellite data
flows through M2 → M3 → M4 and produces a real templated SMS sent to a test phone number.
**Owner: M3 + M4 pair, with M2 supporting data issues.**

**Phase 3 — Feedback & Institutional Layer (Days 17–24)**
| Member | Task |
|---|---|
| M1 | Institutional dashboard geography-scoping and RBAC enforcement finalized; PII protection audit on Registry endpoints |
| M2 | Data ingestion monitoring/alerting (ingestion_status audit log dashboarding for the team, not the farmer-facing product) |
| M3 | Feedback-driven retraining batch job wired to `advisory_feedback` (TRD §3.5); evaluation metrics (precision/recall per class) reported |
| M4 | Feedback SMS reply handling (PRD F9) complete, including clarifying-prompt logic for unrecognized replies (AC9.2); IVR integration for critical alerts (PRD F7) |
| M5 | Full institutional dashboard (aggregation thresholds, PRD AC10.1; filter bar; read-only enforcement AC10.3); WhatsApp/web companion started if time permits (P2, lowest priority) |

**Integration checkpoint 3 (end of Day 24):** full feedback loop proven — a test farmer's SMS
reply is correctly attributed, logged, and visible to the (simulated) retraining job; institutional
dashboard correctly shows aggregated data with threshold suppression working.
**Owner: M4 + M3 pair, M5 validates dashboard against real feedback-influenced data.**

**Phase 4 — Hardening & Launch Readiness (Days 25–30)**
| Member | Task |
|---|---|
| All | Cross-team testing across the full farmer journey (App Flow §1-4) for every advisory class and at least 2 languages |
| M1 | DPDP Act 2023 compliance pass (consent logging, deletion flow) |
| M2 | Scale-testing ingestion against a larger synthetic plot set (validate TRD §8 scalability approach) |
| M3 | Final threshold validation with agronomy input (Assumption A7) before any real farmer goes live |
| M4 | TRAI DLT template registration process completed (or formally scheduled, if lead time exceeds sprint) for a real (non-sandbox) production gateway account |
| M5 | Accessibility pass on all UI surfaces (`05_...md` §7); template localization completeness check (no missing reason-code × language combination, PRD AC6.3) |

---

### 4. Hand-off Points Summary

| From → To | What's handed off | Checkpoint |
|---|---|---|
| M1 → M2 | Active plot record (with buffer polygon) ready for ingestion | Integration checkpoint 1 |
| M2 → M3 | Engineered feature set per plot/cycle | Ongoing, validated at checkpoint 1 & 2 |
| M3 → M4 | `ml_predictions` record (class, confidence, reason-code, model version) | Integration checkpoint 2 |
| M4 → M5 (templates) | Reason-codes needing a template | Continuous, template governance workflow (Phase 1 onward) |
| M5 → M4 | Vetted, sign-off-complete templates | Blocks M4's advisory send for any reason-code without one |
| M4 → M3 | `advisory_feedback` records | Integration checkpoint 3, feeds retraining |
| M1 (auth/RBAC) → M5 | Institutional session scoping | Phase 2–3, before dashboard goes live to real institutional users |

---

### 5. Risk Note on Team Sequencing
The critical path runs M1 → M2 → M3 → M4, so any slippage in the Data/GIS layer (M2) — the most
externally-dependent module (GEE/Copernicus/NASA Earthdata access, cloud-cover edge cases) —
has the largest downstream impact. Recommend M2 starts Phase 1 work with synthetic/mocked plot
data in parallel with M1's real registration flow, so M3 and M4 are never fully blocked waiting on
live satellite access.
