# 13 — ML Model Flowchart (Detailed)

> Consolidates the soil-moisture indices, labeling strategy, XGBoost fine-tuning approach, and
> FPR-aware evaluation discussion into one flowchart-driven reference.

---

## 13.1 Overall Two-Stage Model Flow

```
                         RAW SATELLITE + WEATHER + CONTEXT DATA
                                        │
                                        ▼
                          ┌─────────────────────────┐
                          │  FEATURE ENGINEERING     │
                          │  (see 13.2)              │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌─────────────────────────┐
                          │  STAGE 1: REGRESSION      │
                          │  XGBoost/LightGBM         │
                          │  -> Soil Moisture %, CWSI │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌─────────────────────────┐
                          │ STAGE 2: DECISION LAYER │
                          │ Rule-based classifier   │
                          │ -> No Action/Monitor/   │
                          │    Irrigate Soon/Now    │
                          └─────────────┬───────────┘
                                        │
                                        ▼
                          ┌─────────────────────────┐
                          │  ADVISORY (reason-code +  │
                          │  class + confidence)      │
                          └─────────────────────────┘
```

---

## 13.2 Feature Engineering Detail

```
SENTINEL-1 (SAR — primary soil-moisture signal, cloud-proof)
  ├── VV backscatter (dB)
  ├── VH backscatter (dB)
  ├── ΔVV (7-day, 14-day change-detection)
  └── ΔVH (7-day, 14-day change-detection)
        Priority: ⭐⭐⭐⭐⭐

SENTINEL-2 (Optical — vegetation-stress signal, NOT soil moisture directly)
  ├── NDVI  = (B8−B4)/(B8+B4)                  Priority: ⭐⭐⭐⭐⭐
  ├── NDWI  = (B8−B11)/(B8+B11)                Priority: ⭐⭐⭐⭐
  ├── EVI                                       Priority: ⭐⭐⭐
  ├── SAVI (soil-adjusted, sparse canopies)     Priority: ⭐⭐⭐
  └── ΔNDVI (7d, 14d trend + anomaly vs 3-5yr median)

WEATHER
  ├── Rainfall 1d/3d/7d/14d                     Priority: ⭐⭐⭐⭐⭐
  ├── Rain forecast 48h/72h                     Priority: ⭐⭐⭐⭐⭐
  ├── ET0 (Penman-Monteith)                     Priority: ⭐⭐⭐⭐⭐
  └── LST                                        Priority: ⭐⭐⭐⭐

CROP/CONTEXT
  ├── Crop type
  ├── Days-after-sowing -> Growth stage -> Kc    Priority: ⭐⭐⭐⭐⭐
  └── ETc = ET0 × Kc

SOIL
  ├── Soil texture
  └── AWC (available water capacity)            Priority: ⭐⭐⭐⭐

SMAP (regional calibration prior ONLY — never the training label)
  └── Coarse soil moisture                       Priority: ⭐⭐⭐⭐
```

**MVP starter set (10 features)**: VV, VH, ΔVV, ΔVH, NDVI, NDWI, Rainfall-7d, Rain-forecast-48h,
ET0, Crop-stage/Kc. Add SMAP, LST, EVI, SAVI, Soil AWC, NDVI-anomaly as v2.

---

## 13.3 Labeling Strategy (Ground Truth Hierarchy)

```
                    LABEL QUALITY (best -> weakest)
                              │
     ┌────────────────────────┼─────────────────────────┐
     ▼                        ▼                          ▼
 ISMN / field           SMAP (validation-only        Water-balance
 soil probes            if not used as input;         bucket model
 (BEST, sparse)         else regional prior only)      (MVP weak label)
     │                        │                          │
     └────────────────────────┴──────────────────────────┘
                              │
                              ▼
                  soil_moisture_label (plot_features table)
                              │
                              ▼
                  Farmer feedback (post-deployment) adds
                  weak supervision: reply + next-cycle NDVI
                  recovery -> refines/recalibrates per zone
```

**Rule enforced**: if SMAP is used as an **input feature**, it must NOT also be the **evaluation
ground truth** for that same model run (data leakage / circular evaluation) — validate instead
against ISMN or the water-balance estimate.

---

## 13.4 Data Record & Train/Test Split

```
                    plot_features (canonical rows)
                              │
              date-aligned per plot (11.4 in Complete Architecture)
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │   SPLIT STRATEGY (choose one, never       │
        │   random row-level split)                 │
        ├─────────────────────────────────────────┤
        │  TEMPORAL:                                │
        │    TRAIN: Jan–Jun    VALID: Jul   TEST: Aug│
        │                                           │
        │  SPATIAL:                                 │
        │    TRAIN: Plots 1-4       TEST: Plot 5    │
        └─────────────────────────────────────────┘
                              │
                              ▼
                  Cross-validation on TRAIN/VALID only
                  TEST held out until final evaluation
```

---

## 13.5 Fine-Tuning & Hyperparameter Loop

```
                    XGBoost hyperparameters to tune:
        n_estimators, max_depth, learning_rate, subsample,
        colsample_bytree, min_child_weight, reg_alpha, reg_lambda
                              │
                              ▼
              Cross-validation on TRAIN/VALID (test set untouched)
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │  MODEL SELECTION RULE (not accuracy-only!)    │
        │  1. FPR (Stage 2) must be below threshold      │
        │  2. Among models passing (1):                  │
        │     - best RMSE/R² for Stage 1 regression       │
        │     - best Recall on "Irrigate Now" class        │
        │       (false negative = missed crop stress —      │
        │        costlier than a false positive)             │
        └─────────────────────────────────────────────┘
                              │
                              ▼
                  FINAL MODEL -> single evaluation on
                  held-out TEST set -> log to
                  model_evaluation_runs table
                              │
                              ▼
                  Deploy if FPR check passes; else
                  block promotion, flag for review
```

---

## 13.6 Evaluation Metrics by Stage

```
STAGE 1 (Regression — Soil Moisture / CWSI)
  ├── MAE   = (1/n)Σ|y − ŷ|
  ├── RMSE  = √[(1/n)Σ(y − ŷ)²]      Target: ~0.05-0.09 m³/m³ (literature benchmark)
  ├── R²    = explained variance
  └── Pearson correlation

STAGE 2 (Classification — Advisory Class)
  ├── Accuracy
  ├── Precision  = TP / (TP + FP)
  ├── Recall     = TP / (TP + FN)     <- weighted higher for "Irrigate Now"
  ├── F1-score
  ├── Confusion matrix (per class)
  └── FPR = FP / (FP + TN)            <- must stay below agreed ceiling
```

### Worked FPR example (illustrative)
```
1,000 test observations
  Actual irrigation-required     = 300
  Actual NOT required            = 700

  Model predicts:
    TP = 270   FN = 30
    FP = 70    TN = 630

  FPR = 70 / (70+630) = 10%
  Precision = 270 / (270+70) = 79%
```
A false positive here = one unnecessary irrigation (water/cost waste). A false negative = a
missed stress signal (potential crop damage) — this asymmetry is why Recall on "Irrigate Now" is
weighted above raw accuracy, and why FPR is tracked as a hard constraint rather than optimized
away to zero (an FPR of 0% usually means the model has become too conservative and is missing
real stress cases instead — i.e., FN has risen).

---

## 13.7 Feature Ablation Plan (for SIH Demo Credibility)

```
Model 1 — SAR only                     -> RMSE, R² (baseline)
Model 2 — SAR + Optical                -> RMSE, R² (should improve)
Model 3 — + Weather (rain, ET0)        -> RMSE, R² (should improve further)
Model 4 — + SMAP + Crop + Soil (full)  -> RMSE, R² (best)
```
Presenting this progression ("adding multimodal data progressively improved soil-moisture
estimation") is a stronger judge-facing argument than quoting a single accuracy number.

---

## 13.8 Full Loop Summary (One Diagram)

```
 Satellite + Weather Data
          │
          ▼
 Feature Engineering (temporal-aligned, per plot)
          │
          ▼
 Stage 1: XGBoost Regression -> Soil Moisture % / CWSI
          │
          ▼
 Stage 2: Rule-based Decision Layer
          │
          ▼
 Advisory (SMS/IVR) -> Farmer
          │
          ▼
 Farmer Feedback (weak label)
          │
          ▼
 Periodic Retrain (temporal/spatial split,
 FPR-constrained model selection)
          │
          └──────────────► back to Stage 1 (improved model)
```
