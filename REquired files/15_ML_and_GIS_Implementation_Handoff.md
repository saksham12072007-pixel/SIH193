# 15 — ML and GIS Implementation Handoff

> This document is a working handoff for the GIS/Data engineer and ML engineer. It is intended to help them continue implementation from the current backend state without re-discovering the project structure.

---

## 15.1 Purpose

The backend already contains the core pipeline structure for ingestion, feature building, prediction, and model evaluation. What remains is to harden the GIS ingestion path, connect it to reliable source data, and replace the fallback ML logic with trainable, versioned model execution.

This document divides the work into two tracks:

- **GIS / Data track**: source ingestion, geospatial alignment, plot feature building, and data quality controls
- **ML track**: soil-moisture inference, advisory classification, evaluation, promotion gating, and retraining support

---

## 15.2 Current Backend State

The backend already includes the main scaffolding for both tracks:

- Canonical feature storage through `plot_features`
- Satellite/raw observation storage through `satellite_data`
- Two-stage prediction service in `ml_prediction_service.py`
- Water-balance weak-label generation
- Model evaluation storage and FPR-based promotion gate
- Geospatial helper functions for plot buffering and India-boundary validation

Important current files:

- `backend/app/services/ingestion_service.py`
- `backend/app/services/plot_features_service.py`
- `backend/app/services/ml_prediction_service.py`
- `backend/app/services/model_evaluation_service.py`
- `backend/app/utils/geospatial.py`
- `backend/app/models/__init__.py`

---

## 15.3 GIS / Data Engineer Work

### Goal

Build a reliable geospatial and ingestion pipeline that converts raw satellite and weather observations into aligned, audit-friendly plot feature rows.

### What already exists

The following behavior is already scaffolded in the backend:

- Date-snapping for source alignment
- Sentinel-1, Sentinel-2, weather, and SMAP source separation
- Cloud and outlier rejection during ingestion
- Water-balance weak labels written to `plot_features`
- Buffer polygon generation for plot geometry

### Continue work on these areas

#### 1. Source integration

Complete the real provider integrations for:

- Sentinel-1 SAR
- Sentinel-2 optical
- SMAP soil-moisture priors
- Weather inputs
- Any region-specific source currently planned for the project

Focus on making the raw records consistent in these fields:

- `plot_id`
- `data_source`
- `data_type`
- `value`
- `observation_date`
- `cloud_coverage`
- `ingestion_status`

#### 2. Geospatial consistency

Make sure each plot has stable and valid geospatial context:

- plot center point
- buffer polygon
- location precision
- India-boundary validation

The current local helper in `backend/app/utils/geospatial.py` is only a lightweight fallback. If production PostGIS is used, replace the approximation with real spatial functions and store geometry in the intended production format.

#### 3. Feature alignment rules

Keep the existing date-snapping rules as the source of truth:

- Sentinel-1: nearest pass within plus or minus 3 days
- Sentinel-2: nearest cloud-free pass within plus or minus 5 days
- Weather: exact date windows for 1, 3, 7, and 14 days
- SMAP: context feature only, never a training label

Do not merge mismatched dates into the same feature row.

#### 4. Data quality pipeline

Preserve and expand the existing filter logic for:

- cloud masking
- invalid ranges
- outlier rejection
- rejected-observation logging

This is important because downstream ML evaluation becomes unreliable if bad rows are silently accepted.

### GIS deliverables

The GIS member should finish these outputs:

- reliable satellite/weather ingestion source adapter(s)
- stable plot geometry handling
- validated feature-row alignment
- monitoring for rejected observations
- a clean feature build path for every active plot

---

## 15.4 ML Engineer Work

### Goal

Replace fallback behavior with a versioned, auditable ML pipeline that can train, evaluate, and serve soil-moisture and advisory decisions from canonical plot features.

### What already exists

The backend already has:

- Stage 1 soil-moisture regression service
- Stage 2 rule-based advisory engine
- Combined prediction pipeline
- Model evaluation run storage
- FPR promotion gate
- SHAP snapshot support in the model evaluation table

### Continue work on these areas

#### 1. Training data construction

Use `plot_features` as the canonical training table.

The ML engineer should define and reuse a single dataset builder that:

- selects valid feature rows
- excludes leaked targets
- enforces temporal or spatial split logic
- preserves model version metadata

The training target should come from approved labels such as:

- water-balance weak labels
- field probe / ISMN labels if available
- feedback-derived labels where valid

SMAP must remain a feature input, not a target source when used inside the same model run.

#### 2. Stage 1 model upgrade

The current service still uses the water-balance fallback as the immediate inference path. The next step is to swap in a trainable model, such as:

- XGBoost
- LightGBM
- another agreed regression model

The Stage 1 model should output:

- soil moisture percentage
- CWSI or equivalent stress score
- confidence
- model version
- feature snapshot for traceability

#### 3. Stage 2 advisory rules

Keep the advisory layer explainable and auditable.

The rule engine should continue to map Stage 1 output into:

- no_action
- monitor
- irrigate_soon
- irrigate_now

The ML member should validate that the thresholds and reason codes still make sense after the trainable model is introduced.

#### 4. Evaluation and promotion gate

Every retrain should write an entry to `model_evaluation_runs` and must include:

- model version
- regression metrics
- classification metrics
- FPR
- passed or blocked promotion state
- SHAP summary or equivalent explanation snapshot

Promotion to production should stay blocked if the FPR threshold is not met.

#### 5. Retraining loop

The retraining path should be automated enough that it is not a notebook-only workflow.

It should include:

- train / validation / test split enforcement
- evaluation on held-out data
- threshold-based promotion decision
- persistence of the winning version
- traceability for every deployed prediction

### ML deliverables

The ML member should finish these outputs:

- trainable Stage 1 regression model
- repeatable dataset builder from `plot_features`
- evaluation pipeline with FPR gate
- model versioning across predictions and feedback
- retraining workflow that can be scheduled or triggered internally

---

## 15.5 Shared Contract Between GIS and ML

The two tracks depend on each other through the canonical feature table.

### GIS provides

- clean raw observations
- aligned `plot_features` rows
- source provenance
- quality flags
- SMAP context features

### ML consumes

- stable feature rows
- label source metadata
- observation dates
- prediction-ready feature snapshots
- model-evaluation inputs

### Rule that must not be broken

Never let SMAP become the soil-moisture label when it is also used as a feature in the same model run. That creates circular leakage and invalidates model evaluation.

---

## 15.6 Recommended Implementation Order

1. Finish ingestion alignment and quality filtering.
2. Validate that `plot_features` is complete for the active plots.
3. Build the training dataset from those canonical rows.
4. Train and compare the Stage 1 regression model against the fallback path.
5. Persist model evaluation runs and enforce the FPR gate.
6. Wire the promoted model version back into the prediction service.
7. Add monitoring for rejected observations, failed ingestions, and low-confidence predictions.

---

## 15.7 Acceptance Criteria

The GIS and ML work can be considered ready for the next phase when all of the following are true:

- plots can be ingested with stable geospatial context
- canonical feature rows are produced for the correct observation dates
- cloud/outlier rejection is logged and visible
- `plot_features` can be used as a reliable training source
- the ML service can produce versioned predictions
- evaluation runs are written for every retrain
- FPR-based promotion blocking works as intended
- no SMAP leakage is possible in the same training run

---

## 15.8 File Map for Continuation

Use these files as the starting point for implementation work:

- `backend/app/services/ingestion_service.py`
- `backend/app/services/plot_features_service.py`
- `backend/app/services/ml_prediction_service.py`
- `backend/app/services/model_evaluation_service.py`
- `backend/app/utils/geospatial.py`
- `backend/app/models/__init__.py`
- `backend/app/routers/ingestion.py`
- `backend/app/routers/predictions.py`
- `backend/app/routers/model_monitoring.py`

---

## 15.9 Short Handoff Note

If the GIS member is blocked, work from raw source ingestion and feature-row alignment first. If the ML member is blocked, work from `plot_features` and the fallback water-balance model first. Both tracks can progress in parallel as long as the feature table contract stays stable.
