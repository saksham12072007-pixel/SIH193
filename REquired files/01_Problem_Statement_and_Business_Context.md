# 01 — Problem Statement & Business Context
## Satellite-Data-Driven Crop Advisory System for Smallholder Farmers

---

### 1. Why This Exists

ISRO/Bhuvan, along with allied Earth Observation (EO) sources (Sentinel, SMAP, IMD), already
publishes open soil-moisture and vegetation-index data covering the whole country. This data is
technically public — but it is published as **raster layers, WMS map services, and GIS portals**
that require geospatial expertise to interpret. A smallholder farmer with a feature phone, limited
literacy, and no data connection has no practical way to use it.

Meanwhile, that same farmer is making high-stakes decisions every few days — *"Should I irrigate
today?"*, *"Is my crop stressed?"* — based on visual inspection, neighbor consultation, or habit,
not on the actual, freely-available satellite signal covering their exact plot.

**The gap this system fills:** turning open EO data that already exists into a **plot-specific,
local-language, SMS-delivered decision** a farmer can act on in under a minute, with zero new
hardware and zero cost to the farmer.

### 2. Business Context

| Dimension | Detail |
|---|---|
| Target user | Smallholder/marginal farmer (avg. Indian holding ≈ 1.1 ha), feature-phone primary device, regional-language literate (not necessarily English/Hindi script) |
| Secondary users | Krishi Vigyan Kendras (KVKs), state agriculture departments, Farmer Producer Organisations (FPOs), agri-insurance assessors |
| Data inputs | ISRO/Bhuvan soil moisture + vegetation index (NDVI), supplemented by satellite/weather data described in the TRD |
| Delivery channel | SMS (primary), with an optional companion app/dashboard for institutional users and farmers with smartphones |
| Cost model | Must run on free/open government and space-agency data; marginal cost per farmer per advisory ≈ cost of one SMS |
| Regulatory context | TRAI DLT (Distributed Ledger Technology) registration required for SMS sender ID/templates in India; Digital Personal Data Protection (DPDP) Act, 2023 governs farmer PII (phone number, GPS location) |

### 3. What Success Means

Success is measured across three tiers, from immediate/technical to long-term/impact:

**Tier 1 — System health (technical success)**
- Satellite data successfully retrieved for ≥95% of registered plots per revisit cycle (accounting
  for unavoidable cloud/satellite-pass gaps).
- Advisory generated and SMS delivered within the defined SLA (see TRD §6) of new satellite data
  becoming available.
- SMS delivery success rate ≥98% (measured via gateway delivery receipts).

**Tier 2 — Farmer engagement (adoption success)**
- ≥60% of farmers who receive an "Irrigate Now" advisory reply to confirm action taken (feedback
  loop engagement), measured after the first full season.
- Farmer opt-out/unsubscribe rate <5% per season.
- Repeat/returning usage across seasons (farmer re-registers plot or continues receiving
  advisories without prompting).

**Tier 3 — Outcome success (impact, measured over 1+ seasons)**
- Measurable reduction in water waste (self-reported or comparative, e.g., number of irrigation
  events vs. a non-advisory control group in the same agro-climatic zone).
- Directional improvement in yield or reduction in crop-stress-related loss versus a control
  group, tracked through farmer-reported outcomes and, where available, post-season NDVI recovery
  trends.
- Positive qualitative trust signals (farmers acting on advisories without independent
  verification, KVKs citing the system in extension work).

### 4. Non-Goals (explicitly out of scope)

To keep the specification unambiguous, the following are **not** part of this system as specified:
- Pest/disease visual diagnosis (would require a different sensor class — drone or close-range
  imagery — not satellite EO).
- Market price / mandi advisory (a different problem domain; may integrate later but is not built
  here).
- Farm equipment/input marketplace or e-commerce.
- Full plot-boundary auto-delineation from imagery (plots are captured as a GPS point + declared
  approximate size/shape at registration, not derived from imagery).
- Real-time (sub-daily) satellite monitoring — cadence is bound by actual satellite revisit times
  (see TRD), not by user expectation.

### 5. Guiding Design Principles (apply to every document in this suite)
1. **Farmer-first**: every feature, screen, and message is evaluated against "can a smallholder
   with a feature phone and limited literacy use this?" before "is this technically elegant?"
2. **Explainable, not opaque**: every advisory carries a plain-language reason. No black-box output
   ever reaches a farmer.
3. **Free-data-only**: no component may depend on a paid satellite tasking or proprietary imagery
   license — this is what keeps marginal cost near zero and keeps the system aligned with
   ISRO/Bhuvan's open-data mandate.
4. **Fail safe, not silent**: if satellite data, ML inference, or SMS delivery fails, the system
   must degrade gracefully (retry, fallback, or explicit "data unavailable" state) — never send a
   wrong or stale advisory silently.
5. **Everything measurable**: every requirement in this document suite has an acceptance criterion
   or metric attached — no vague "should be fast" or "should be user-friendly" without a testable
   definition.

### 6. Document Suite Map
| # | Document | Purpose |
|---|---|---|
| 1 | `01_Problem_Statement_and_Business_Context.md` | This file — why, for whom, what success means |
| 2 | `02_Product_Requirements_Document.md` | All features + acceptance criteria |
| 3 | `03_Technical_Requirements_Document.md` | Complete tech stack + every assumption stated |
| 4 | `04_App_Flow_Diagram.md` | Navigation/interaction logic + decision points |
| 5 | `05_UIUX_Design_Brief.md` | Visual/interaction spec, SMS tone, accessibility |
| 6 | `06_Backend_Schema.md` | Database tables, relationships, auth, retention, indexing |
| 7 | `07_System_Architecture_Diagram.md` | Component connections, data flow, failure handling |
| 8 | `08_Team_Implementation_Plan.md` | 5-member team build sequence, ownership, timeline |
