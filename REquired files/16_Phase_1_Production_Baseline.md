# Phase 1 — Production Baseline and Governance

## Frozen pilot scope

- **Geography:** Yavatmal district, Vidarbha region, Maharashtra
- **Villages:** 10
- **Farmers:** approximately 50
- **Plots:** approximately 70
- **Crops:** cotton, maize, wheat, rice, sugarcane, and groundnut
- **Farmer languages:** Marathi, Hindi, and English
- **Institutional dashboard:** read-only and aggregate-only; individual farmer
  identity and exact plot-level records remain restricted
- **Pilot deployment target:** not selected yet
- **Pilot release date:** not selected yet

## Owners

| Responsibility | Owner |
|---|---|
| Product and acceptance decisions | Pratham and Saumya |
| Engineering/SDE and technical release | Saksham Sharma and Arnendu Biswas |
| Agronomy | Shankar Adhikary |
| Field operations and village coordination | Riti Patel |

## Acceptance gates

The pilot is not accepted until all of these pass:

1. Farmer advisories are generated reliably and delivery status is traceable.
2. Institutional reporting is available without exposing individual records.
3. Model behavior is reviewed and accepted by the agronomy owner.
4. Security and privacy controls are verified.
5. Demo and staging environments are reproducible from documented steps.

## Dependency baseline

Available for the pilot:

- Satellite data access
- Weather data access

Still required:

- SMS, WhatsApp, and/or IVR provider
- Maps/geocoding provider
- Production database
- Cloud or hosting account
- Production deployment target

## Governance decisions still required

- Select the cloud/hosting platform and production region.
- Set a target pilot-ready date.
- Name the production database and communications providers.
- Approve the risk owner and review cadence.
- Approve the final agronomy thresholds for each pilot crop.

## Reproducible demo

The local seed script creates the frozen pilot shape with deterministic,
clearly marked records. It must only be run against a development database:

```bash
cd backend
../.venv/bin/python scripts/seed_demo_data.py
```

Demo credentials are documented in the backend and frontend READMEs and must
never be reused in staging or production.
