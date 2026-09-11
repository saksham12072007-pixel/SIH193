# 07 — System Architecture Diagram

Cross-references: `03_Technical_Requirements_Document.md` (tech choices), `06_Backend_Schema.md`
(data model), `04_App_Flow_Diagram.md` (the interaction sequences these components serve).

---

### 1. Component Overview Diagram

```
┌──────────────────┐        ┌─────────────────────┐        ┌──────────────────────┐
│  Farmer Client    │        │  Institutional        │        │  KVK Field Agent      │
│  (feature phone:  │        │  Dashboard (web)      │        │  (web form, assisted  │
│  SMS/USSD/IVR;    │        │  React + Leaflet       │        │  onboarding)          │
│  optional         │        │                        │        │                       │
│  WhatsApp/web)    │        └──────────┬─────────────┘        └──────────┬────────────┘
└─────────┬─────────┘                   │                                  │
          │                             │                                  │
          v                             v                                  v
┌───────────────────────────────────────────────────────────────────────────────┐
│                          Backend API (FastAPI)                                 │
│   - Farmer/Plot registration & command endpoints                               │
│   - Institutional auth + aggregated-read endpoints                             │
│   - Internal orchestration endpoints (triggered by scheduler)                  │
└───────┬─────────────────┬─────────────────┬─────────────────┬────────────────┘
        │                 │                 │                 │
        v                 v                 v                 v
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌────────────────────┐
│ Farmer & Plot  │ │ Satellite Data │ │ ML Inference   │ │ Advisory/Template   │
│ Registry       │ │ Ingestion       │ │ Service        │ │ Engine              │
│ (PostgreSQL +  │ │ Service         │ │ (FastAPI +     │ │ (Jinja2 renderer,   │
│ PostGIS)       │ │ (Python +       │ │ scikit-learn/  │ │ sms_templates table)│
│                │ │ GEE/geemap,     │ │ XGBoost)       │ │                     │
│                │ │ Airflow/cron)   │ │                │ │                     │
└───────┬────────┘ └───────┬────────┘ └───────┬────────┘ └──────────┬──────────┘
        │                  │                   │                    │
        │                  v                   │                    │
        │        ┌───────────────────────┐     │                    │
        │        │ External Data Sources  │     │                    │
        │        │ - Sentinel-1/2 (GEE)   │     │                    │
        │        │ - SMAP (NASA Earthdata)│     │                    │
        │        │ - Bhuvan/VEDAS (ISRO)  │     │                    │
        │        │ - IMD / NASA POWER     │     │                    │
        │        └───────────────────────┘     │                    │
        │                                       │                    │
        └──────────────► satellite_data ────────┘                    │
                          table (06_...md)                            │
                                                                       v
                                                            ┌──────────────────────┐
                                                             │ SMS / IVR Delivery    │
                                                             │ Gateway Integration   │
                                                             │ (MSG91/Gupshup/       │
                                                             │  Exotel — TRD §4)     │
                                                             └──────────┬────────────┘
                                                                        │
                                                                        v
                                                             ┌──────────────────────┐
                                                             │  Telecom Network       │
                                                             │  (delivers SMS/call    │
                                                             │  to farmer's phone)    │
                                                             └──────────┬────────────┘
                                                                        │
                                                                        v
                                                              [Farmer receives advisory,
                                                               may reply — reply routes
                                                               back through Backend API
                                                               to advisory_feedback table]
```

---

### 2. Data Flow Description (end to end)

1. **Onboarding:** Farmer/KVK agent → Backend API → `farmers`/`plots` tables (Farmer & Plot
   Registry). Buffer polygon generated here (PRD AC2.3).
2. **Scheduled ingestion:** Airflow/cron scheduler triggers the Satellite Data Ingestion Service
   for every `active` plot on the cadence defined in TRD §6. The service queries external data
   sources (Sentinel-1/2 via GEE, SMAP, Bhuvan/VEDAS, IMD/NASA POWER) for each plot's buffer
   polygon and writes results to `satellite_data`.
3. **Feature engineering:** performed within the Ingestion Service (cloud-masking, trend/anomaly
   computation, water-balance bucket model) before handing off to ML Inference.
4. **ML inference:** ML Inference Service reads the engineered feature set, produces Stage-1
   regression + Stage-2 classification output, writes to `ml_predictions`.
5. **Advisory generation:** Advisory/Template Engine reads the latest `ml_predictions` record,
   selects the correct vetted template (crop × reason-code × language), writes an `advisories`
   record, and — unless the class is `no_action` — hands off to the Delivery Gateway.
6. **Delivery:** SMS/IVR Gateway Integration sends the message via the telecom network, writes
   delivery status back to `sms_logs` via webhook callback.
7. **Feedback:** an inbound SMS reply is received by the Gateway, routed through the Backend API,
   matched to the originating advisory, and written to `advisory_feedback`.
8. **Retraining loop:** a weekly batch job reads `advisory_feedback` + subsequent
   `satellite_data`/`ml_predictions` (NDVI recovery signal) to recalibrate the ML model per
   agro-climatic zone (TRD §3.5); new model artifacts are versioned and referenced by future
   `ml_predictions.model_version` entries.
9. **Institutional read:** Institutional Dashboard queries the Backend API's aggregated-read
   endpoints (never raw farmer tables directly), which apply the aggregation-threshold and
   geography-scoping rules (PRD AC10.1) before returning data.

---

### 3. External Dependencies

| Dependency | Criticality | Notes |
|---|---|---|
| Google Earth Engine (GEE) | High | Primary compute backbone for Sentinel-1/2 processing; an outage stalls ingestion for that cycle |
| NASA Earthdata (SMAP) | Medium | Used as a calibration prior, not the sole signal — degraded but non-blocking if unavailable |
| Bhuvan/VEDAS (ISRO/SAC) | Medium | Supplementary agromet products; pipeline can proceed on Sentinel+IMD alone if this is unavailable |
| IMD / NASA POWER / Open-Meteo | High | Weather data feeds both feature engineering and the water-balance label model; a documented fallback order should be used (IMD primary, Open-Meteo/NASA POWER fallback) |
| SMS/IVR Gateway (MSG91/Gupshup/Exotel) | Critical | Sole channel to the farmer; an outage directly blocks PRD F5 — see failure handling below |
| TRAI DLT registration | Critical (compliance) | Not a runtime dependency but a legal prerequisite for any production SMS send |

---

### 4. Failure Handling (architecture-level; detailed rules in TRD §7)

| Failure scenario | System behavior |
|---|---|
| Satellite data source unavailable/cloud-masked for a plot's cycle | Ingestion Service falls back to SAR (all-weather) signal; if no source returns usable data for 2 consecutive cycles, plot is flagged `data_unavailable` and no advisory is generated for that cycle (PRD AC3.3) |
| ML Inference Service down | Advisory generation queue holds pending items; the rule-based baseline threshold logic (TRD §3.4) can still produce a conservative advisory without the full regression model, ensuring farmers are never left without any signal during a partial outage — but this fallback path is explicitly logged as "baseline mode" for audit purposes |
| SMS Gateway down / delivery failure | One retry within 30 minutes (TRD §7); if still failed, advisory is marked `sms_failed` and flagged for manual review — the advisory record itself is never lost, only the delivery attempt |
| Backend API / database outage | Scheduler-triggered jobs queue and retry on restoration; no data is generated or sent during the outage window — a full outage pauses the entire pipeline rather than risk inconsistent partial writes |
| Institutional Dashboard read failure | Isolated to the dashboard's read path only; has no effect on the farmer-facing advisory pipeline (dashboard is a downstream read-only consumer, not in the critical path) |

---

### 5. Scalability Notes
- GEE server-side reduction avoids downloading raw satellite scenes, keeping ingestion compute
  roughly constant per plot regardless of total system scale (TRD §8).
- The Backend API and ML Inference Service are stateless and horizontally scalable behind a load
  balancer; only the PostgreSQL/PostGIS layer requires vertical scaling or read-replica strategy
  planning as plot count grows into the tens/hundreds of thousands.
- The scheduler distributes ingestion across the revisit cadence window (not all plots processed
  in a single instant), smoothing load on both GEE and the Backend API.
