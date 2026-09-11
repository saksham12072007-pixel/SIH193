# 02 — Product Requirements Document (PRD)
## Satellite-Data-Driven Crop Advisory System

Cross-references: `01_Problem_Statement_and_Business_Context.md` (why), `03_Technical_Requirements_Document.md` (how), `04_App_Flow_Diagram.md` (flow), `05_UIUX_Design_Brief.md` (screens/SMS design).

---

### 1. Feature List Overview

| # | Feature | Priority (MVP/P1/P2) |
|---|---|---|
| F1 | Farmer Registration | MVP |
| F2 | Plot Geo-Tagging | MVP |
| F3 | Satellite Data Integration | MVP |
| F4 | ML Advisory Generation | MVP |
| F5 | SMS Delivery | MVP |
| F6 | Local-Language Support | MVP |
| F7 | Farmer Notification Preferences | P1 |
| F8 | Historical Advisory Tracking | P1 |
| F9 | Farmer Feedback / Confirmation Loop | P1 |
| F10 | Institutional Dashboard (KVK/Agri Dept) | P2 |

---

### F1 — Farmer Registration

**Description:** A farmer creates an account using only a phone number, enabling all subsequent
plot registration and advisory delivery.

**Requirements:**
- Registration works via **SMS/USSD short-code flow** (no smartphone or app required) and,
  optionally, a **web form** (for KVK field-agent-assisted onboarding) and a **WhatsApp flow**
  (for smartphone-owning farmers).
- Required fields at registration: phone number, name, preferred language, state/district
  (for locale + agro-climatic zone mapping).
- Phone number is the unique identifier and primary authentication factor (see F-Auth in TRD §5).
- Consent for data collection (phone number, GPS, crop data) must be explicitly captured and
  logged with a timestamp, per DPDP Act 2023 requirements.

**Acceptance Criteria:**
- AC1.1: A farmer can complete registration via SMS/USSD in ≤5 message exchanges.
- AC1.2: A farmer cannot proceed to plot registration (F2) without an explicit consent confirmation
  logged in the system.
- AC1.3: Duplicate registration with the same phone number updates the existing record rather than
  creating a duplicate farmer entity.
- AC1.4: Registration confirmation is sent back to the farmer in their selected language within
  60 seconds of completion.

---

### F2 — Plot Geo-Tagging

**Description:** A registered farmer associates one or more plots with their account, each
identified by a GPS location and basic crop metadata.

**Requirements:**
- Plot capture methods: (a) **GPS pin drop** via WhatsApp/web form location-share, (b) **missed-call
  triggered SMS with coordinates** relayed by a KVK field agent using a basic GPS tool, or
  (c) manual entry of village + approximate plot description as a fallback when GPS is unavailable.
- Each plot record requires: latitude/longitude (or fallback village-level location), crop type
  (from a controlled vocabulary — see TRD §3.4), approximate plot size (acres/hectares, farmer-
  declared), sowing date.
- Since exact plot boundaries are not captured (see Non-Goals in `01_...md`), the system generates
  a **buffer polygon** (default radius configurable per crop/region — see TRD §3.2) around the GPS
  point for satellite data extraction.
- A farmer may register multiple plots; each plot is independently tracked and advised.

**Acceptance Criteria:**
- AC2.1: A plot cannot be saved without a valid latitude/longitude within India's bounding box, or
  an explicit fallback village-level location.
- AC2.2: Crop type must be selected from the controlled vocabulary; free-text crop entry is
  rejected with a clarifying prompt.
- AC2.3: A buffer polygon is generated and stored for every plot within 5 seconds of plot creation.
- AC2.4: A farmer can view, via SMS query ("MY PLOTS"), a list of all their registered plots with
  crop and short plot nickname/ID.

---

### F3 — Satellite Data Integration

**Description:** The system automatically retrieves satellite-derived soil moisture and vegetation
index data for every registered plot's buffer polygon on a defined cadence.

**Requirements:**
- Data sources and cadence are fully specified in `03_Technical_Requirements_Document.md` §2
  (data sources) and §6 (refresh cadence) — this feature consumes that pipeline's output.
- For every plot, on every scheduled cycle, the system must attempt to retrieve: vegetation index
  (NDVI/NDWI), a soil-moisture proxy (SAR-derived and/or passive-microwave), and recent rainfall.
- If primary optical data is unavailable (cloud cover), the system must fall back to radar
  (SAR)-derived soil moisture rather than skip the cycle silently.
- Every retrieval attempt (success or failure) is logged with source, timestamp, and plot ID.

**Acceptance Criteria:**
- AC3.1: For ≥95% of registered plots, at least one usable data point (optical or SAR) is
  retrieved per scheduled cycle.
- AC3.2: If optical data is fully cloud-masked for a cycle, the system logs a fallback event and
  proceeds using SAR-derived soil moisture rather than failing the cycle.
- AC3.3: If no data source returns usable data for a plot for 2 consecutive cycles, the system
  flags the plot as "data unavailable" rather than generating an advisory from stale data.
- AC3.4: Every ingestion attempt is recorded in an auditable log (source, plot, timestamp, status).

---

### F4 — ML Advisory Generation

**Description:** The system converts retrieved satellite/weather data into one of a small set of
actionable advisory classes for each plot.

**Requirements:**
- Output classes: `No Action`, `Monitor`, `Irrigate Soon`, `Irrigate Now — Stress Alert` (exact
  modeling approach specified in TRD §3).
- Every advisory must include: the class, a confidence indicator, and a short machine-readable
  **reason code** (e.g., `low_soil_moisture`, `declining_ndvi_trend`) used to select the correct
  SMS template (see `05_UIUX_Design_Brief.md` §4).
- Advisory generation must account for crop growth stage (derived from sowing date + crop type)
  so thresholds are stage-appropriate, not a flat rule across the whole season.
- The decision layer (index → class) must be **rule-based and auditable**, even if the underlying
  regression uses ML — no advisory may be generated by an unexplainable/black-box step (see
  Guiding Principle 2 in `01_...md`).

**Acceptance Criteria:**
- AC4.1: Every generated advisory has a non-null class, confidence score, and reason code.
- AC4.2: Given the same input feature set, the system produces the same advisory class
  deterministically (rule layer is not stochastic).
- AC4.3: An advisory is never generated for a plot flagged "data unavailable" (AC3.3) — the system
  instead logs a skipped cycle.
- AC4.4: "Irrigate Now — Stress Alert" classification recall is prioritized over precision in
  threshold tuning (a missed stress event is worse than one unnecessary alert) — validated against
  the evaluation methodology in TRD §3.6.

---

### F5 — SMS Delivery

**Description:** Generated advisories are delivered to the farmer's registered phone number as an
SMS.

**Requirements:**
- SMS is the **primary and mandatory** delivery channel for every farmer (works on any feature
  phone with no data connection).
- Delivery must use a TRAI DLT-registered sender ID and pre-registered message templates (see TRD
  §4 for gateway selection).
- Each SMS must fit within SMS segment constraints in a way that keeps cost predictable — target
  ≤2 segments (≤320 characters for Unicode/regional-script SMS) per message.
- Delivery status (sent/delivered/failed) must be tracked per message via the gateway's delivery
  receipt callback.
- Failed deliveries are retried according to a defined retry policy (see TRD §6).

**Acceptance Criteria:**
- AC5.1: An advisory generated for a plot with an active "Irrigate Now" or "Monitor" class results
  in an SMS send attempt within the SLA defined in TRD §6.
- AC5.2: SMS delivery success rate is ≥98% measured over any 7-day rolling window (excluding
  farmer-side handset issues).
- AC5.3: A failed SMS is retried at least once within 30 minutes before being marked
  permanently failed and logged for manual review.
- AC5.4: No SMS is ever sent without a corresponding logged advisory record (SMS content is never
  generated ad hoc outside the advisory pipeline).

---

### F6 — Local-Language Support

**Description:** All farmer-facing communication (SMS, IVR, registration flow) is delivered in the
farmer's selected regional language and script.

**Requirements:**
- Minimum MVP language set: Hindi + one regional language matched to the pilot deployment area
  (configurable, not hardcoded — see TRD §3.4).
- Language preference is captured at registration (F1) and can be changed at any time via a
  simple SMS command (e.g., "LANG <code>").
- All SMS templates are authored and stored per (crop × reason-code × language) combination —
  never machine-translated at send-time (see `05_UIUX_Design_Brief.md` §3 for template governance).
- Native script is used (not Romanized transliteration) wherever the SMS gateway supports Unicode
  delivery for that language.

**Acceptance Criteria:**
- AC6.1: A farmer receives every message (registration confirmation, advisory, error/fallback
  message) in their currently selected language — no message is ever sent in a language the
  farmer did not select.
- AC6.2: A "LANG" change command takes effect for the very next outgoing message.
- AC6.3: No advisory reason-code exists in the system without a corresponding vetted template for
  every currently supported language (a missing translation blocks that reason-code from firing
  in that language, falling back to a default supported language plus a flag for translation
  backlog, rather than sending a broken/blank message).

---

### F7 — Farmer Notification Preferences

**Description:** Farmers can control frequency and channel of advisories.

**Requirements:**
- A farmer can opt to receive advisories only for specific plots (if they manage multiple), and
  can pause/resume advisories per plot via SMS command.
- A farmer can opt into IVR (voice call) as a redundant channel for "Irrigate Now" alerts
  specifically (see `05_UIUX_Design_Brief.md` §5 for channel ranking).
- A hard cap of 1–2 advisory messages per 3–5 day cycle applies by default, to prevent alert
  fatigue; an "immediate alert" for sudden-onset stress is the only exception and is explicitly
  labeled as such.

**Acceptance Criteria:**
- AC7.1: A "PAUSE <plot-id>" command stops advisories for that plot within one cycle and is
  confirmed back to the farmer.
- AC7.2: A farmer opted into IVR receives a voice call in addition to (not instead of) the SMS for
  any "Irrigate Now — Stress Alert" advisory.
- AC7.3: No farmer receives more than 2 advisory messages for the same plot within any 3-day
  window, except for a labeled immediate/urgent alert.

---

### F8 — Historical Advisory Tracking

**Description:** Farmers and institutional users can access a plot's advisory history.

**Requirements:**
- A farmer can request their plot's recent advisory history via SMS command ("HISTORY <plot-id>"),
  returned as a condensed summary (last 3 advisories with dates and classes).
- Full historical detail (all advisories, all reason codes, all satellite readings) is retained
  in the backend and exposed via the institutional dashboard (F10), not sent in full over SMS
  (SMS is summary-only, per farmer-first design).
- Historical data is retained per the retention policy defined in `06_Backend_Schema.md` §5.

**Acceptance Criteria:**
- AC8.1: A "HISTORY" SMS command returns the last 3 advisories for the specified plot (or the
  farmer's only plot, if unambiguous) within one SMS.
- AC8.2: Every advisory ever generated for a plot remains queryable in the backend for at least
  the retention period defined in `06_Backend_Schema.md`, even if the plot is later deactivated.

---

### F9 — Farmer Feedback / Confirmation Loop

**Description:** Farmers can reply to an advisory confirming the action taken, creating a
feedback signal used to improve future advisories.

**Requirements:**
- Every advisory SMS includes a reply option (e.g., "Reply 1 = irrigated, 2 = not needed, 3 = crop
  already damaged").
- Replies are matched to the originating advisory (via short code or sender-number session
  matching) and logged against the (plot, advisory, date) record.
- Feedback data feeds the model recalibration process described in TRD §3.5 — this feature is the
  data-collection half of that loop; the retraining pipeline itself is a technical process,
  not a farmer-facing feature.

**Acceptance Criteria:**
- AC9.1: A single-digit SMS reply from a farmer within 72 hours of receiving an advisory is
  correctly attributed to that specific advisory record.
- AC9.2: An ambiguous or unrecognized reply results in a clarifying SMS, not a silently-dropped
  feedback event.
- AC9.3: Feedback records are queryable by the ML retraining process without any manual data
  wrangling (i.e., they land in a structured table per `06_Backend_Schema.md`).

---

### F10 — Institutional Dashboard (KVK / State Agri Dept / FPO)

**Description:** A web dashboard for institutional users to view aggregated, anonymized advisory
and stress data across farmers in their jurisdiction.

**Requirements:**
- Authenticated institutional users (see auth model in `06_Backend_Schema.md` §4) can view a
  map-based, village/block-level rollup of current advisory classes (e.g., "12% of plots in
  stress alert this week").
- Individual farmer data is never exposed at PII-identifiable granularity to institutional users
  without separate, explicit authorization (aggregation/anonymization by default).
- Dashboard is a **read-only** view for MVP — no institutional user can directly edit farmer or
  plot data through this interface.

**Acceptance Criteria:**
- AC10.1: An institutional user sees only aggregated data (minimum aggregation threshold — e.g.,
  no cell shown for fewer than 5 plots) for any geography, never a single identifiable farmer's
  data, unless a separate elevated-access role is granted.
- AC10.2: Dashboard data reflects advisory data no more than 24 hours stale.
- AC10.3: Institutional users cannot trigger, modify, or delete any farmer-facing advisory or SMS
  through the dashboard in MVP scope.

---

### 2. Feature Dependency Summary (build-order signal; full plan in `08_...md`)
```
F1 (Registration) -> F2 (Plot Geo-Tagging) -> F3 (Satellite Ingestion) -> F4 (ML Advisory)
                                                                              |
                              F6 (Language) --------------------------------> F5 (SMS Delivery)
                                                                              |
                                                          F9 (Feedback) <-----+-----> F7 (Preferences)
                                                                              |
                                                                     F8 (History) -> F10 (Dashboard)
```
