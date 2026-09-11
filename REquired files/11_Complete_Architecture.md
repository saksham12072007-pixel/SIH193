# 11 — Complete Architecture (Consolidated, Updated)

> This file supersedes `04_System_Architecture.md` as the **single source of truth** for the full
> pipeline — it folds in the soil-moisture indices work, the SAR/optical fusion logic, the
> two-stage ML design, the FPR-aware evaluation approach, and the water-quantity recommendation
> module that were developed after the original architecture was written.

---

## 11.1 End-to-End Flow (Full Pipeline)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  1. FARMER ONBOARDING                                                    │
│     Missed call / USSD / WhatsApp / KVK agent app                        │
│     Captures: phone#, GPS pin/plot polygon, plot area, crop,             │
│                sowing date, irrigation method (flood/drip/sprinkler),    │
│                language preference                                       │
│     -> stored in Farmer & Plot Registry (PostgreSQL + PostGIS)           │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  2. SCHEDULER (every 3–5 days per plot, + event-triggered)               │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  3. DATA INGESTION LAYER  (per plot polygon, via Google Earth Engine)    │
│                                                                            │
│  Sentinel-1 SAR (GRD)        Sentinel-2 (L2A)         Weather/Agromet    │
│   ├─ VV backscatter           ├─ NDVI, NDWI            ├─ Rainfall        │
│   ├─ VH backscatter           ├─ EVI, SAVI             │  (1/3/7/14d +   │
│   └─ (cloud-proof)            └─ (cloud-masked)         │   48-72h fcst)  │
│                                                          ├─ ET0 (Penman-  │
│  SMAP (regional prior)        Soil/Context               │   Monteith)    │
│   └─ Coarse soil moisture      ├─ Soil texture/AWC       ├─ LST           │
│      (9-36km, calibration      ├─ Crop + sowing date     └─ Surface       │
│       only, not plot signal)   └─ -> growth stage/Kc         Dryness Idx  │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  4. FEATURE ENGINEERING LAYER                                            │
│     - Temporal alignment: snap all sources to nearest date per plot      │
│       (see 11.4 "Temporal Alignment" — avoids mismatched-date bugs)      │
│     - ΔVV, ΔVH (7-day, 14-day SAR change-detection)                      │
│     - ΔNDVI, ΔNDWI (7-day, 14-day trend + anomaly vs 3-5yr median)       │
│     - Rainfall windows (1/3/7/14d) + forecast (48/72h)                   │
│     - ETc = ET0 × Kc (crop water requirement)                            │
│     - Cloud/quality masking, outlier removal, missing-value handling     │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  5. ML DECISION ENGINE (two-stage — see 13_Model_Flowchart.md for detail)│
│                                                                            │
│  STAGE 1 — Regression (XGBoost/LightGBM)                                 │
│    Inputs: SAR + optical + weather + SMAP + crop/soil features           │
│    Output: Estimated surface/root-zone soil moisture %, CWSI             │
│    Labels: water-balance weak labels (MVP) -> ISMN/field probes (later)  │
│                                                                            │
│  STAGE 2 — Decision Layer (rule-based, explainable)                      │
│    Inputs: Stage-1 output + crop stage + rain forecast + NDVI trend      │
│    Output: No Action / Monitor / Irrigate Soon / Irrigate Now            │
│            + reason-code + confidence                                    │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  6. ADVISORY GENERATION LAYER                                            │
│     Reason-code -> pre-vetted vernacular template                       │
│     (Jinja2, agronomist-reviewed, per crop × reason-code × language)     │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  7. DELIVERY LAYER — SMS (primary) / IVR (redundant) / WhatsApp (opt.)   │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  8. FARMER FEEDBACK LOOP                                                 │
│     Reply "1=irrigated / 2=not needed / 3=crop damaged" via SMS/missed   │
│     call -> logged against (plot, advisory, date) -> weak label for      │
│     retraining -> weekly/seasonal model recalibration per agro-zone      │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  9. INSTITUTIONAL DASHBOARD (KVK/State Agri Dept/FPO)                    │
│     Aggregated, anonymized village/block heatmap + model performance     │
│     monitoring (RMSE/MAE/R² for Stage 1, Precision/Recall/FPR for Stage2)│
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 11.2 What's New Since the Original Architecture (`04_System_Architecture.md`)

| Area | Original (`04`) | Now (this file) |
|---|---|---|
| Soil moisture | Treated as a single "Stage 1 regression" output, source unspecified | Explicit index set defined: SAR VV/VH/ΔVV/ΔVH as **primary** signal, NDVI/NDWI as **vegetation-stress** signal (not soil moisture directly), SMAP as **regional calibration prior only** |
| Ground truth | Mentioned water-balance weak labels generically | Full labeling hierarchy defined: ISMN/field probes (best) > SMAP (acceptable, but must not double as both input and label) > water-balance bucket model (MVP weak label) |
| Model evaluation | RMSE/MAE/precision/recall mentioned | Explicit **FPR constraint** added as a first-class evaluation metric alongside accuracy — model selection must satisfy an FPR ceiling, not just maximize accuracy |
| Validation splitting | Not specified | Explicit **temporal/spatial split** requirement (never random-split same-plot time series) — see 11.4 |
| Feature engineering | High-level bullet list | Explicit feature table with priority ranking (see `13_Model_Flowchart.md`) and temporal-alignment requirement |

---

## 11.3 Component-Level Architecture (Updated)

| Layer | Tech choice | Notes / Change from `04` |
|---|---|---|
| Farmer Registry & Plot DB | PostgreSQL + PostGIS | Unchanged from original |
| Data Ingestion | GEE Python API / `geemap`, scheduled via Airflow/cron | **Add**: explicit per-source date-snapping logic (11.4) to avoid mismatched acquisition dates across S1/S2/SMAP/weather |
| Feature Store | Parquet / PostGIS, or GEE server-side reduction | **Add**: versioned feature table (see `13_Model_Flowchart.md` §13.4) with plot_id, date, all raw + engineered features, and the label source used |
| ML Serving | scikit-learn/XGBoost behind FastAPI | **Add**: two endpoints — `/soil-moisture` (Stage 1 regression) and `/advise` (Stage 2+3 combined) — kept separable for independent evaluation/monitoring |
| Model Monitoring | *(not in original)* | **New component**: tracks RMSE/MAE/R² (Stage 1) and Accuracy/Precision/Recall/F1/**FPR**/confusion matrix (Stage 2) per retraining cycle, per agro-climatic zone |
| Advisory/Template Engine | Jinja2, rule-based | Unchanged from original |
| SMS/IVR Gateway | Fast2SMS/MSG91/Twilio (sandbox); Gupshup/Exotel (prod) | Unchanged |
| Dashboard | React+Leaflet or Streamlit | **Add**: model-monitoring panel (FPR trend, RMSE trend) visible to technical/KVK admin users |
| Feedback Store | PostgreSQL `advisory_feedback` table | **Add**: `predicted_class`, `predicted_confidence` columns for post-hoc evaluation |

---

## 11.4 Temporal Alignment (New — Critical Fix)

A key defect risk identified: combining Sentinel-1 (e.g., Aug 10), Sentinel-2 (e.g., Aug 2), and
rainfall (Aug 3–9) into one "record" without alignment silently corrupts training data.

**Fix — Canonical Per-Plot-Per-Date Record:**
```
                    PLOT P001 @ Aug 10
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
  Sentinel-1          Sentinel-2          Weather
  nearest available   nearest cloud-free   preceding
  pass (±3 days)      pass (±5 days)       1/3/7/14-day
        │                 │                  window ending Aug 10
        └─────────────────┼──────────────────┘
                          │
                    ONE FEATURE ROW
              (date = Aug 10, plot = P001)
```
Every ingestion job writes to this canonical row structure — no feature is merged across sources
without an explicit "nearest valid observation" join. This directly fixes the drift/leakage risk
flagged in the ML design discussion.

---

## 11.5 Evaluation & Fine-Tuning Loop (New — Governs Model Updates)

```
                    ALL HISTORICAL DATA
                           │
             ┌─────────────┴─────────────┐
             │                           │
          TRAIN                        TEST (held out, never touched
     (temporal or spatial               during tuning)
      split — see 13_Model_Flowchart.md)
             │
             ▼
        Cross-validation / hyperparameter tuning
        (n_estimators, max_depth, learning_rate,
         subsample, colsample_bytree, reg_alpha/lambda)
             │
             ▼
        Candidate model selection rule:
        1. FPR must stay below agreed threshold (Stage 2)
        2. Among models satisfying (1), pick best RMSE/R² (Stage 1)
           and best Recall on "Irrigate Now" class (Stage 2)
             │
             ▼
        FINAL MODEL -> ONE evaluation on held-out TEST set
             │
             ▼
        Deploy -> Monitor in production (dashboard, §11.3)
             │
             ▼
        Farmer feedback (Section 8 of the pipeline) accumulates
             │
             ▼
        Periodic retrain (weekly/seasonal) repeats this loop
```

---

## 11.6 Security, Privacy & Compliance (Unchanged from `04`, Carried Forward)
- Phone numbers + GPS are PII — encrypted at rest, consent captured at onboarding.
- TRAI DLT registration required for SMS sender ID + templates in production.
- DPDP Act 2023 compliance — data minimization, right to deletion.
- Prefer Agristack/Farmer ID integration over a parallel PII store.
