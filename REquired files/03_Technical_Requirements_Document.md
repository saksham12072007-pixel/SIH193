# 03 — Technical Requirements Document (TRD)
## Satellite-Data-Driven Crop Advisory System

Cross-references: `02_Product_Requirements_Document.md` (features this stack must support),
`06_Backend_Schema.md` (data model), `07_System_Architecture_Diagram.md` (component wiring).

Every assumption below is stated explicitly, per the brief's constraint that nothing be assumed
silently. Where a choice is uncertain, the tradeoff is flagged.

---

### 1. Assumptions (stated explicitly)

| # | Assumption | Why it matters |
|---|---|---|
| A1 | The team has (or can obtain) free-tier/research access to Google Earth Engine (GEE), Copernicus Data Space, and NASA Earthdata | These are the free backbone for satellite data; without access, ingestion must fall back to slower direct-portal downloads |
| A2 | ISRO/Bhuvan/VEDAS data is accessed via their public portal/API and does not require a paid data license for this use case | Confirmed for research/public-good, non-commercial use per current published access terms; must be re-verified if the deployment shifts to commercial |
| A3 | The MVP targets a single pilot district and 1–2 crops before generalizing | Keeps Kc-curve tuning, thresholds, and language templates tractable at build time |
| A4 | Farmers do not have precise plot-boundary GPS surveys; only a point + declared size is available | Drives the buffer-polygon approach (PRD F2) instead of true polygon ingestion |
| A5 | SMS is the mandatory channel; IVR/WhatsApp are additive, not replacements | Ensures the system works for the lowest-common-denominator device (feature phone) |
| A6 | A DoT-registered bulk SMS aggregator account (with TRAI DLT template registration) will be set up before any production SMS send — a sandbox/test account is used through MVP build | Legal SMS delivery in India requires this; cannot be skipped for production |
| A7 | The team has basic agronomy domain input available (even informally, via a KVK contact) to vet Kc values and thresholds before go-live | Without this, threshold tuning is a technical guess with real farm-decision consequences |

---

### 2. Satellite & Weather Data Sources

| Data need | Primary source | Fallback / cross-validation | Access method |
|---|---|---|---|
| Vegetation index (NDVI/NDWI/EVI) | Sentinel-2 L2A (Copernicus, 10m, ~5-day revisit) | Bhuvan/VEDAS NDVI product; NASA MODIS (250m–1km, long historical baseline) | Google Earth Engine (`COPERNICUS/S2_SR_HARMONIZED`) |
| Soil moisture (cloud-proof) | Sentinel-1 GRD SAR backscatter (VV/VH, 10m, ~6-12 day revisit) | ISRO RISAT/EOS-04 (via Bhoonidhi/NRSC) | Google Earth Engine (`COPERNICUS/S1_GRD`) |
| Soil moisture (regional calibration prior) | NASA SMAP L3/L4 (9–36km) | ESA CCI Soil Moisture (long-term baseline) | NASA Earthdata |
| Rainfall / temperature | IMD Gridded Rainfall (0.25°) | NASA POWER (global daily), Open-Meteo (fast/no-key, useful for MVP) | IMD Pune / data.gov.in; power.larc.nasa.gov |
| Bhuvan/VEDAS direct agromet products | VEDAS Surface Soil Moisture, Surface Dryness Index, LST, PET | — | vedas.sac.gov.in (SAC-ISRO) |
| Soil type / available water capacity | Soil Health Card Scheme (where farmer enrolled) | NBSS&LUP district soil maps; FAO HWSD (global fallback) | soilhealth.dac.gov.in; nbsslup.in |
| Crop calendar / growth stage | ICAR crop calendars | FAO-56 crop coefficient (Kc) tables | icar.org.in; FAO Irrigation & Drainage Paper 56 |

**Flagged uncertainty:** Sentinel-1's 6–12 day effective revisit over India, combined with
Sentinel-2's cloud-masked usable-frame rate dropping to ~1–2/month in Kharif, means the *effective*
usable-data cadence during monsoon is closer to 5–7 days than a naive "daily" expectation. The
system's SLA (§6) is set against this realistic cadence, not an idealized daily-refresh assumption.

---

### 3. ML Model Stack

#### 3.1 Two-stage design
- **Stage 1 (Regression):** estimate root-zone soil moisture (%) and/or a Crop Water Stress Index
  (CWSI) from EO + weather features.
- **Stage 2 (Classification/rules):** map the Stage 1 estimate + crop-stage context to one of four
  advisory classes: `No Action / Monitor / Irrigate Soon / Irrigate Now — Stress Alert`.

#### 3.2 Feature set
- Optical: NDVI, NDWI, EVI, SAVI, 7/14-day trend slope, anomaly vs. 3–5yr historical median.
- Radar: VV, VH backscatter, VV/VH ratio, day-to-day change-detection soil-moisture index.
- Passive microwave: SMAP coarse soil moisture as regional bias-correction prior.
- Weather: rainfall (3/7/14-day), forecast rainfall (48–72h), reference ET0 (Penman-Monteith),
  land surface temperature, humidity.
- Crop/soil context: crop type, days-after-sowing → growth stage → FAO-56 Kc value; soil texture/
  available water capacity (AWC).
- Default buffer-polygon radius for feature extraction: **50m** for row crops on <1ha plots,
  configurable per crop/region (flagged as a tunable parameter, not a fixed constant — validate
  against pilot district plot sizes before hard-coding).

#### 3.3 Ground-truth / label strategy (staged)
1. **MVP (no field sensors needed):** physics-based weak labels via a FAO-56 dual-crop-coefficient
   water-balance bucket model (soil moisture depletion = ET0×Kc − effective rainfall − irrigation).
2. **Validation:** cross-check SAR/optical-to-soil-moisture mapping against published Sentinel-1/2
   accuracy benchmarks (~0.05–0.09 m³/m³ RMSE) before trusting the model on live plots.
3. **Post-MVP:** farmer feedback replies (PRD F9) + next-cycle NDVI recovery as weak supervision
   for periodic recalibration.
4. **Medium-term:** a small number of KVK/ICAR instrumented reference plots per agro-climatic zone
   for ongoing ground-truth correction.

#### 3.4 Modeling approach by stage of maturity
| Stage | Approach | Rationale |
|---|---|---|
| Baseline (Day 1 / safety net) | Threshold + Kc rule engine (no training data needed) | Fast, fully explainable, always available as fallback |
| MVP ML | Gradient-boosted trees (XGBoost/LightGBM), regressing water-balance-estimated soil moisture from EO+weather features, trained per agro-climatic zone | Handles nonlinearity; SHAP-interpretable for auditability |
| Future | Sequence model (LSTM/Temporal CNN) over multi-week EO time series, possibly with data assimilation into a crop-growth model (WOFOST/AquaCrop) | Requires longer accumulated time series + more compute; explicitly post-MVP |
| Classifier layer (always) | Rule-based mapping from regression output + crop-stage + trend to the 4-class advisory | Keeps the farmer-facing decision auditable regardless of Stage-1 model sophistication |

**Flagged uncertainty:** exact classification thresholds (e.g., "soil moisture below X% for crop
stage Y triggers Irrigate Now") must be set per crop and validated with agronomy input (Assumption
A7) before go-live — do not hardcode thresholds from literature defaults without local validation.

#### 3.5 Retraining cadence
- Weekly batch recalibration job, incorporating new farmer feedback (F9) and next-cycle NDVI
  recovery signal, scoped per agro-climatic zone (not a single national model).
- Model version is logged against every advisory record (see `06_Backend_Schema.md` `ml_predictions`
  table) for auditability — a farmer's advisory can always be traced to the exact model version
  that produced it.

#### 3.6 Evaluation
- Regression: RMSE/MAE against the water-balance bucket-model estimate and any available ground
  sensor data.
- Classification: precision/recall per class, with **recall on "Irrigate Now" weighted higher**
  than precision (a missed stress event costs a crop; a false positive costs one unneeded
  irrigation).
- Field validation: staggered/A-B rollout across pilot villages vs. control, comparing input use
  and self-reported yield.

---

### 4. SMS Gateway Selection

| Option | Notes |
|---|---|
| **MVP/sandbox:** Fast2SMS or Twilio (sandbox mode) | Fast to integrate, good for demo/dev; not production-legal for bulk SMS in India without DLT registration |
| **Production candidate:** MSG91 or Gupshup | Both offer DoT-registered aggregator status, DLT template registration support, and IVR/voice add-ons — **final selection should be based on a cost-per-SMS + regional-language Unicode support comparison at production-commit time**, not hardcoded here |
| **IVR provider (production):** Exotel or Gupshup Voice | For the redundant voice-call channel (PRD F7) |

**Flagged uncertainty:** exact gateway pricing and Unicode-segment costs for regional-language SMS
change over time; this must be re-quoted immediately before production sign-off rather than
assumed from this document.

---

### 5. Backend Framework, Frontend Platform, Authentication

| Component | Choice | Rationale |
|---|---|---|
| Backend framework | Python + FastAPI | Async-friendly for I/O-bound satellite/SMS calls, lightweight, easy to pair with the Python-native GEE/ML ecosystem |
| Database | PostgreSQL + PostGIS extension | Native geospatial types (plot points/polygons), mature, free, well-supported |
| Task scheduling | Airflow (or cron for MVP) | Orchestrates the recurring ingestion → feature engineering → ML → advisory → SMS pipeline |
| Institutional dashboard frontend | React + Leaflet/Mapbox (or Streamlit for hackathon/MVP speed) | Read-only map dashboard (PRD F10) does not need a heavy frontend framework at MVP |
| Farmer-facing "frontend" | **None required for MVP** — SMS/USSD is the interface | Matches farmer-first, feature-phone-first principle in `01_...md` |
| Authentication — farmers | **Phone-number + OTP-free session model**: the phone number itself, verified by SMS/USSD origin, is the identity; sensitive actions (e.g., "PAUSE") are accepted only from the registered number | Avoids requiring app-based login for a feature-phone user base; full rationale and schema in `06_Backend_Schema.md` §4 |
| Authentication — institutional users | Standard email/password + optional MFA, role-based access control (RBAC) scoped to geography | Institutional users have a smartphone/desktop, so standard web auth is appropriate here |

**Flagged uncertainty:** phone-number-as-identity is inherently spoofable if SIM-swap fraud occurs;
for MVP this risk is accepted (low financial stakes — an advisory, not a transaction), but should be
revisited with a stronger verification step (e.g., periodic OTP re-confirmation) before scaling to
schemes with financial linkage (e.g., PMFBY claims).

---

### 6. Data Refresh Cadence & Model Update Frequency

| Process | Cadence | Notes |
|---|---|---|
| Satellite data ingestion | Every 3–5 days per plot (aligned to realistic Sentinel-1/2 combined revisit, §2 flagged uncertainty) | Immediate/ad hoc re-check triggered if a sudden anomaly is suspected from the most recent data point |
| Weather data ingestion | Daily | Cheap, high-value for ET0/rainfall-triggered advisories |
| ML advisory generation | Triggered per plot immediately after a successful ingestion cycle | Not a fixed clock time — event-driven off ingestion completion |
| SMS delivery SLA | Within 30 minutes of advisory generation | Defines AC5.1 in the PRD |
| Model retraining | Weekly batch, per agro-climatic zone | Per §3.5 |
| Institutional dashboard data freshness | ≤24 hours stale | Defines AC10.2 in the PRD |

---

### 7. Failure Handling Requirements (technical detail; architecture-level view in `07_...md`)
- Satellite ingestion failure for a plot → retry once within the same cycle window; if still
  failed, log and skip (PRD AC3.3) rather than generate an advisory from stale/absent data.
- ML service unavailable → advisory generation queue holds/retries; no fallback advisory is ever
  auto-generated by the rule engine alone without at least the baseline threshold check passing
  (baseline logic, per §3.4, is always available since it requires no external ML service call).
- SMS gateway failure → retry per PRD AC5.3 (one retry within 30 minutes), then flag for manual
  review; never silently drop a generated advisory.

---

### 8. Non-Functional Requirements
| Category | Requirement |
|---|---|
| Scalability | Ingestion + ML pipeline must handle thousands of plots per cycle without degrading the SLA in §6; achieved via GEE server-side reduction (avoids raw scene downloads) and horizontal scaling of the FastAPI inference service |
| Security | PII (phone number, GPS) encrypted at rest; TLS in transit; DPDP Act 2023-aligned consent and deletion support |
| Auditability | Every advisory traceable to exact input data, model version, and template used |
| Cost | Marginal cost per farmer per advisory ≈ 1 SMS segment cost; no paid satellite imagery license in the pipeline |
