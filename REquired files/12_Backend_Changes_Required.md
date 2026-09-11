# 12 — Backend Changes Required (Delta from Original `04_System_Architecture.md`)

> This file is a **change list**, not a full redesign — use it as a direct action-item checklist
> against whatever backend you've already started building from `04_System_Architecture.md`. It
> tells you exactly what to add, modify, or re-sequence.

---

## 12.1 Database Schema Changes

### `plots` table — ADD columns
```sql
ALTER TABLE plots ADD COLUMN soil_texture VARCHAR(30);
ALTER TABLE plots ADD COLUMN soil_awc NUMERIC;              -- available water capacity
```
**Why**: soil texture/AWC feed the Stage 1 soil-moisture regression as context features (sandy
soils dry faster than clay for the same rainfall/ET0 conditions).

### NEW table — `plot_features` (canonical per-plot-per-date feature row)
```sql
CREATE TABLE plot_features (
    plot_id UUID REFERENCES plots(id),
    obs_date DATE,
    vv_db NUMERIC, vh_db NUMERIC,
    delta_vv_7d NUMERIC, delta_vh_7d NUMERIC,
    ndvi NUMERIC, ndwi NUMERIC, evi NUMERIC, savi NUMERIC,
    delta_ndvi_7d NUMERIC, delta_ndvi_14d NUMERIC,
    rainfall_1d NUMERIC, rainfall_3d NUMERIC, rainfall_7d NUMERIC, rainfall_14d NUMERIC,
    rain_forecast_48h NUMERIC,
    et0 NUMERIC, kc NUMERIC, etc NUMERIC,
    lst NUMERIC,
    smap_sm NUMERIC,          -- regional prior, NOT the model's target
    crop_stage VARCHAR(20),
    label_source VARCHAR(20), -- 'water_balance' | 'ismn' | 'smap' | 'farmer_feedback'
    soil_moisture_label NUMERIC, -- nullable until label assigned
    PRIMARY KEY (plot_id, obs_date)
);
```
**Why**: This is the single biggest gap in the original architecture — there was no explicit,
versioned feature-storage schema. Without this table you cannot (a) audit what data went into a
given advisory, (b) do proper temporal/spatial train-test splitting, or (c) avoid the
mismatched-date bug described in `11_Complete_Architecture.md` §11.4.

### `advisory_feedback` table — ADD columns
```sql
ALTER TABLE advisory_feedback ADD COLUMN predicted_class VARCHAR(20);
ALTER TABLE advisory_feedback ADD COLUMN predicted_confidence NUMERIC;
ALTER TABLE advisory_feedback ADD COLUMN predicted_soil_moisture NUMERIC;
ALTER TABLE advisory_feedback ADD COLUMN model_version VARCHAR(20);
```
**Why**: needed so you can compute Precision/Recall/F1/**FPR** and RMSE/MAE per model version
after the fact — the original schema only logged the farmer's reply, not what the model predicted
alongside it, which makes proper evaluation impossible.

### NEW table — `model_evaluation_runs`
```sql
CREATE TABLE model_evaluation_runs (
    run_id UUID PRIMARY KEY,
    model_version VARCHAR(20),
    trained_at TIMESTAMP,
    agro_zone VARCHAR(50),
    rmse NUMERIC, mae NUMERIC, r2 NUMERIC,
    accuracy NUMERIC, precision_score NUMERIC, recall NUMERIC, f1 NUMERIC,
    fpr NUMERIC,
    passed_fpr_threshold BOOLEAN,
    notes TEXT
);
```
**Why**: makes the FPR-constrained model-selection rule (see `13_Model_Flowchart.md` §13.5) an
enforceable, auditable backend process instead of an ad-hoc notebook decision.

---

## 12.2 API/Service Changes

| Endpoint | Change |
|---|---|
| `POST /ingest/{plot_id}` | **Modify**: must now write to `plot_features` using the "nearest valid observation per source" join logic (11.4), not a naive same-day merge |
| `POST /soil-moisture/{plot_id}` | **New endpoint** — exposes Stage 1 regression output independently (soil moisture %, CWSI) so it can be evaluated/monitored separately from the final advisory |
| `POST /advise/{plot_id}` | **Modify**: now calls Stage 1 → Stage 2 internally, and returns `{class, reason_code, confidence}` — kept as a two-step pipeline internally so Stage 1 output is inspectable independently of the final advisory |
| `POST /feedback/{plot_id}` | **Modify**: must now snapshot the `predicted_class`/`predicted_confidence`/`predicted_soil_moisture` at time of advisory into `advisory_feedback`, not just log the farmer's reply |
| `GET /model/evaluation/{model_version}` | **New endpoint** — serves the dashboard's model-monitoring panel (RMSE/MAE/R²/FPR trend) from `model_evaluation_runs` |
| Retraining job (batch, not user-facing) | **Modify**: must enforce the FPR-constrained selection rule programmatically before promoting any new model version to production — do not let this be a manual/notebook step in the real deployment |

---

## 12.3 Ingestion Pipeline Changes

1. **Add explicit date-snapping logic** per source (S1: ±3 days, S2: ±5 days cloud-free, weather:
   exact date) before writing a `plot_features` row — see `11_Complete_Architecture.md` §11.4.
2. **Separate SMAP ingestion from the training-label pipeline.** SMAP must only ever populate the
   `smap_sm` *feature* column, never the `soil_moisture_label` column — enforce this at the code
   level (e.g., a lint check or unit test) since it's an easy mistake that silently causes
   data leakage (model learns to reproduce SMAP rather than predict independently).
3. **Add cloud/quality masking + outlier rejection** as a discrete pipeline step before feature
   computation, with rejected-observation counts logged for monitoring (currently implicit/absent
   in the original architecture).
4. **Add the water-balance weak-label generator as a scheduled job**, writing to
   `soil_moisture_label` with `label_source = 'water_balance'`, so it runs automatically per plot
   rather than being a one-off script.

---

## 12.4 ML Serving Changes

1. **Split model serving into two independently deployable services** (or at least two clearly
   separated modules): `soil_moisture_model` (Stage 1 regression) and `advisory_decision_engine`
   (Stage 2 rules + Stage 3 water-quantity calc) — keeps the auditable rule-based layer easy to
   inspect/modify without touching the ML model, and lets you evaluate/version them separately.
2. **Add model versioning** — every prediction written to `advisory_feedback` must carry a
   `model_version` so you can trace which model produced which advisory (needed for the
   evaluation-runs table above and for any liability/audit questions).
3. **Add a train/test split enforcement utility** — a shared function used by all training jobs
   that performs temporal or spatial holdout (never random row-level split) — see
   `13_Model_Flowchart.md` §13.5 for the exact logic. This should be a reused library function,
   not re-implemented per notebook, to avoid the accidental-leakage risk.
4. **Add SHAP-based feature importance logging** at each retrain, stored alongside the
   `model_evaluation_runs` row — useful both for debugging and for the SIH judge Q&A ("which
   features matter most").

---

## 12.5 Monitoring/Dashboard Changes

1. **Add a model-health panel** (new) showing, per model version and per agro-climatic zone:
   RMSE/MAE/R² (Stage 1), Accuracy/Precision/Recall/F1/**FPR** (Stage 2), and a confusion matrix.
2. **Add an alert** if a newly retrained model's FPR exceeds the agreed threshold — should block
   auto-promotion to production and require manual review.
3. **Add a "false-positive drilldown" view** — lets a KVK/technical admin see which specific
   plots/dates triggered false "Irrigate Now" alerts, to spot systematic issues (e.g., a
   particular soil type or crop stage the model handles poorly).

---

## 12.6 Priority Order for Implementation

If you're retrofitting an already-partially-built backend, do these in this order:

1. `plot_features` table + date-snapping ingestion fix (§12.1, §12.3.1) — **do this first**,
   everything else depends on clean, aligned features.
2. Separate SMAP feature vs. label usage (§12.3.2) — cheap fix, prevents a silent, hard-to-detect
   bug in your model's reported accuracy.
3. `advisory_feedback` prediction-snapshot columns (§12.1) — needed before you can compute any
   real evaluation metrics from live feedback.
4. `model_evaluation_runs` table + FPR-constrained promotion gate (§12.1, §12.2, §12.4.3) — do
   this once you have enough feedback data to evaluate against; earlier is fine too if you're
   validating against water-balance/ISMN data instead.
5. Dashboard monitoring panel (§12.5) — last, since it's for visibility, not correctness.
