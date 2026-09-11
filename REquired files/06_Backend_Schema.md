# 06 — Backend Schema

Cross-references: `03_Technical_Requirements_Document.md` §5 (framework/DB choice: PostgreSQL +
PostGIS), `02_Product_Requirements_Document.md` (features each table supports).

---

### 1. Entity-Relationship Summary

```
farmers (1) ──< (many) plots (1) ──< (many) satellite_data
                    │                       │
                    │                       v
                    │                 (many) ml_predictions
                    │                       │
                    │                       v
                    └──────────────< (many) advisories ──< (many) sms_logs
                                              │
                                              v
                                        (many) advisory_feedback

institutional_users (many) ──< (many, via assigned_geographies) dashboard access (read-only, aggregated)
```

---

### 2. Tables

#### 2.1 `farmers`
| Column | Type | Notes |
|---|---|---|
| `farmer_id` | UUID (PK) | Primary identifier |
| `phone_number` | VARCHAR(15), UNIQUE, NOT NULL, ENCRYPTED | Identity/auth anchor (TRD §5); unique constraint enforces PRD AC1.3 |
| `name` | VARCHAR(120) | Farmer-declared |
| `preferred_language` | VARCHAR(10), NOT NULL | ISO-ish language code, references `supported_languages` |
| `state` | VARCHAR(60) | For agro-climatic zone mapping |
| `district` | VARCHAR(60) | For agro-climatic zone mapping |
| `consent_given_at` | TIMESTAMP, NOT NULL | Required before any plot record can be created (PRD AC1.2) |
| `registration_channel` | ENUM('sms','ussd','web','whatsapp') | For onboarding analytics |
| `created_at` | TIMESTAMP, NOT NULL | |
| `updated_at` | TIMESTAMP, NOT NULL | |
| `status` | ENUM('active','paused','deactivated') | Global account state |

**Indexes:** UNIQUE index on `phone_number` (primary lookup path for every inbound SMS); index on
`(state, district)` for agro-climatic zone queries.

#### 2.2 `plots`
| Column | Type | Notes |
|---|---|---|
| `plot_id` | UUID (PK) | |
| `farmer_id` | UUID (FK → farmers.farmer_id), NOT NULL | |
| `plot_nickname` | VARCHAR(40) | Short farmer-facing identifier, e.g. "Plot 2" (PRD AC2.4) |
| `location_point` | GEOGRAPHY(POINT, 4326) | Nullable if only village-level fallback available |
| `location_precision` | ENUM('gps','village_fallback') | Drives buffer-polygon default (TRD §3.2) |
| `village_name` | VARCHAR(100) | Used when `location_precision = village_fallback` |
| `buffer_polygon` | GEOGRAPHY(POLYGON, 4326) | Generated at plot creation (PRD AC2.3) |
| `crop_type` | VARCHAR(60), NOT NULL, FK → `crop_reference.crop_code` | Controlled vocabulary (PRD AC2.2) |
| `plot_size_declared` | DECIMAL(6,2) | In acres, farmer-declared |
| `sowing_date` | DATE, NOT NULL | Drives growth-stage calculation |
| `status` | ENUM('active','paused','deactivated') | Independent of farmer-level status (PRD AC7.1) |
| `created_at` | TIMESTAMP, NOT NULL | |
| `updated_at` | TIMESTAMP, NOT NULL | |

**Indexes:** spatial GiST index on `location_point` and `buffer_polygon` (required for efficient
satellite-data-extraction queries at scale); index on `farmer_id`; index on `status` (scheduler
only queries active plots).

#### 2.3 `satellite_data`
| Column | Type | Notes |
|---|---|---|
| `reading_id` | UUID (PK) | |
| `plot_id` | UUID (FK → plots.plot_id), NOT NULL | |
| `source` | ENUM('sentinel2','sentinel1','smap','vedas','imd','nasa_power') | |
| `reading_type` | ENUM('ndvi','ndwi','evi','sar_vv','sar_vh','soil_moisture','rainfall','lst','et0') | |
| `value` | DECIMAL(10,4) | Raw reading value |
| `capture_date` | DATE, NOT NULL | Satellite pass / weather-data date |
| `ingested_at` | TIMESTAMP, NOT NULL | |
| `cloud_masked` | BOOLEAN, DEFAULT FALSE | Flags optical readings excluded due to cloud cover |
| `ingestion_status` | ENUM('success','failed','fallback_used') | Supports PRD AC3.4 audit log requirement |

**Indexes:** composite index on `(plot_id, capture_date DESC)` (primary query pattern: "latest
readings for this plot"); index on `ingestion_status` for pipeline monitoring queries.

**Retention:** raw readings retained per policy in §5.

#### 2.4 `ml_predictions`
| Column | Type | Notes |
|---|---|---|
| `prediction_id` | UUID (PK) | |
| `plot_id` | UUID (FK → plots.plot_id), NOT NULL | |
| `model_version` | VARCHAR(30), NOT NULL | Ties every prediction to an exact model version (TRD §3.5 auditability requirement) |
| `stage1_soil_moisture_estimate` | DECIMAL(5,2) | Regression output (%) |
| `stage1_cwsi_estimate` | DECIMAL(5,2) | Crop Water Stress Index, nullable if not computed |
| `advisory_class` | ENUM('no_action','monitor','irrigate_soon','irrigate_now') | Stage-2 output (PRD F4) |
| `confidence_score` | DECIMAL(4,3) | 0.000–1.000 |
| `reason_code` | VARCHAR(50), NOT NULL | e.g. `low_soil_moisture`; drives template selection (PRD AC4.1) |
| `input_feature_snapshot` | JSONB | Full feature vector used, for audit/reproducibility |
| `predicted_at` | TIMESTAMP, NOT NULL | |

**Indexes:** index on `(plot_id, predicted_at DESC)`; index on `advisory_class` (for institutional
dashboard aggregation queries, PRD F10).

#### 2.5 `advisories`
| Column | Type | Notes |
|---|---|---|
| `advisory_id` | UUID (PK) | |
| `plot_id` | UUID (FK → plots.plot_id), NOT NULL | |
| `prediction_id` | UUID (FK → ml_predictions.prediction_id), NOT NULL | Every advisory traces to exactly one ML prediction |
| `advisory_class` | ENUM(same as ml_predictions.advisory_class) | Denormalized for fast history queries (PRD AC8.1) |
| `template_id` | UUID (FK → sms_templates.template_id) | Which vetted template was used |
| `language_used` | VARCHAR(10) | May differ from farmer's current preference if a template was mid-translation-backlog (PRD AC6.3) |
| `sms_sent` | BOOLEAN, DEFAULT FALSE | "No Action" advisories are logged but not sent by default (App Flow §2) |
| `ivr_triggered` | BOOLEAN, DEFAULT FALSE | |
| `created_at` | TIMESTAMP, NOT NULL | |

**Indexes:** index on `(plot_id, created_at DESC)` (primary access pattern for HISTORY command,
AC8.1).

**Retention:** per policy in §5 — advisories must remain queryable for the full retention window
even if the plot is later deactivated (PRD AC8.2).

#### 2.6 `sms_logs`
| Column | Type | Notes |
|---|---|---|
| `sms_log_id` | UUID (PK) | |
| `advisory_id` | UUID (FK → advisories.advisory_id), NULLABLE | Null for non-advisory system messages (e.g., registration confirmations) |
| `farmer_id` | UUID (FK → farmers.farmer_id), NOT NULL | |
| `direction` | ENUM('outbound','inbound') | |
| `message_body` | TEXT | Actual sent/received content (encrypted at rest) |
| `gateway_message_id` | VARCHAR(100) | External reference from SMS aggregator |
| `delivery_status` | ENUM('queued','sent','delivered','failed') | |
| `retry_count` | SMALLINT, DEFAULT 0 | Supports PRD AC5.3 retry policy |
| `sent_at` | TIMESTAMP | |
| `delivered_at` | TIMESTAMP, NULLABLE | |

**Indexes:** index on `(farmer_id, sent_at DESC)`; index on `delivery_status` (for retry/failure
monitoring); index on `gateway_message_id` (for delivery-receipt webhook matching).

#### 2.7 `advisory_feedback`
| Column | Type | Notes |
|---|---|---|
| `feedback_id` | UUID (PK) | |
| `advisory_id` | UUID (FK → advisories.advisory_id), NOT NULL | |
| `farmer_id` | UUID (FK → farmers.farmer_id), NOT NULL | |
| `reply_code` | ENUM('irrigated','not_needed','crop_damaged','unrecognized') | Maps to PRD F9 digit options |
| `raw_reply_text` | VARCHAR(160) | Original SMS text, for unrecognized-reply debugging |
| `received_at` | TIMESTAMP, NOT NULL | Must be within 72 hrs of advisory to attribute correctly (PRD AC9.1) |
| `used_in_retraining_batch` | VARCHAR(30), NULLABLE | Model retraining batch ID this record contributed to, once consumed |

**Indexes:** index on `advisory_id` (attribution lookup); index on `used_in_retraining_batch` (for
retraining pipeline queries, TRD §3.5).

#### 2.8 Supporting reference tables
| Table | Purpose |
|---|---|
| `crop_reference` | Controlled vocabulary of supported crops + associated FAO-56 Kc curve reference (PRD AC2.2) |
| `supported_languages` | Active language codes + script metadata (PRD F6) |
| `sms_templates` | (crop_code, reason_code, language_code) → vetted template text + review-status workflow field (`05_UIUX_Design_Brief.md` §4) |
| `agro_climatic_zones` | Zone boundaries used to scope per-zone model versions (TRD §3.4/3.5) |

#### 2.9 `institutional_users`
| Column | Type | Notes |
|---|---|---|
| `user_id` | UUID (PK) | |
| `email` | VARCHAR(120), UNIQUE, NOT NULL | |
| `password_hash` | VARCHAR(255), NOT NULL | bcrypt/argon2 |
| `mfa_enabled` | BOOLEAN, DEFAULT FALSE | |
| `role` | ENUM('kvk_viewer','state_dept_viewer','fpo_viewer','admin') | RBAC (TRD §5) |
| `assigned_geography` | JSONB | List of district/block codes this user may view (supports PRD AC10.1 scoping) |
| `created_at` | TIMESTAMP, NOT NULL | |
| `last_login_at` | TIMESTAMP | |

---

### 3. Relationships Summary
- `farmers` (1) → `plots` (many): one farmer manages multiple plots.
- `plots` (1) → `satellite_data` (many): every ingestion cycle appends readings, never overwrites.
- `plots` (1) → `ml_predictions` (many): one prediction per plot per successful ingestion cycle.
- `ml_predictions` (1) → `advisories` (1): each prediction results in exactly one advisory record
  (even if `sms_sent = false`).
- `advisories` (1) → `sms_logs` (0 or many): zero if `sms_sent = false`; typically one outbound +
  possibly one inbound (reply) log entry.
- `advisories` (1) → `advisory_feedback` (0 or 1): a farmer's reply, if given within the window.

---

### 4. Authentication Flow

**Farmers (SMS/USSD-native, per TRD §5):**
1. Identity = phone number the message originates from. No password.
2. Sensitive commands (`PAUSE`, `LANG`, feedback replies) are accepted only from a phone number
   that matches an existing `farmers.phone_number` record with `status = active`.
3. No OTP required for MVP (adds friction inconsistent with feature-phone/SMS-first design);
   flagged in TRD §5 as a risk accepted for MVP scope, revisit before financial-scheme linkage.

**Institutional users (web dashboard):**
1. Email + password (bcrypt/argon2 hashed) login.
2. Optional MFA (TOTP-based) — recommended default-on for `admin` role, optional for viewer roles.
3. Session token (JWT, short-lived, refresh-token pattern) scoped to `assigned_geography` and
   `role` — every dashboard query is filtered server-side by these claims, never trusted from
   client input, to enforce PRD AC10.1's aggregation/anonymization guarantee at the query layer.

---

### 5. Data Retention Policy

| Data category | Retention | Rationale |
|---|---|---|
| `farmers`, `plots` (active) | Retained indefinitely while account is active | Core operational data |
| `farmers`, `plots` (deactivated) | Retained 24 months post-deactivation, then anonymized (PII stripped, aggregate stats kept) | Balances DPDP Act 2023 "right to deletion" support with legitimate model-improvement use of historical aggregate patterns |
| `satellite_data` (raw readings) | Retained 36 months | Supports multi-season historical-baseline/anomaly calculations (TRD §3.2) |
| `ml_predictions`, `advisories` | Retained 36 months minimum, indefinitely for plots still active (PRD AC8.2) | Auditability + historical tracking feature (PRD F8) |
| `sms_logs` | Retained 12 months, then message body purged (metadata/status retained longer for delivery-rate analytics) | Minimizes long-term storage of raw PII-adjacent message content per data-minimization principle |
| `advisory_feedback` | Retained same as `advisories` | Feedback is intrinsically tied to the advisory's audit trail |
| Explicit farmer deletion request | PII purged within 30 days; aggregate/anonymized advisory-class statistics may be retained | DPDP Act 2023 right-to-deletion compliance |

---

### 6. Indexing Strategy Summary (for fast queries at scale)
- **Spatial (GiST) indexes** on all geography columns — required for the plot-lookup-by-region and
  satellite-extraction query patterns to remain performant at thousands-of-plots scale (TRD §8
  scalability requirement).
- **Composite (entity_id, timestamp DESC) indexes** on every high-volume time-series table
  (`satellite_data`, `ml_predictions`, `advisories`, `sms_logs`) — matches the dominant query
  pattern of "most recent N records for this plot/farmer".
- **Status/enum indexes** on fields the scheduler and monitoring jobs filter by (`plots.status`,
  `satellite_data.ingestion_status`, `sms_logs.delivery_status`) — keeps operational/pipeline
  queries from full-table scans as volume grows.
- **Partitioning consideration (flagged, not committed for MVP):** `satellite_data` and `sms_logs`
  are the fastest-growing tables; if volume exceeds single-table performance comfortably handled
  by indexing alone (re-evaluate at ~10M+ rows), consider time-based partitioning (e.g., monthly)
  — deferred decision, not required at MVP/pilot scale.
