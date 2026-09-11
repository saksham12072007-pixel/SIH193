# NIR MVP Release Runbook

## Pre-release

1. Install `backend/requirements.txt`.
2. Set `ML_API_ENABLED`, `ML_API_URL`, and `ML_API_KEY` through deployment
   secrets.
3. Run `PYTHONPATH=. python -m pytest -q` from `backend/`.
4. Confirm the legacy fallback remains enabled.

## Smoke test

1. Register a test farmer and create an active plot.
2. Ingest the plot's canonical features.
3. Call `/predictions/irrigation-stress/{plot_id}`.
4. Confirm the response includes `nir_percent`, `urgency`, `model_version`,
   and `fallback_used`.
5. Call `/advisories/generate/{plot_id}`.
6. Confirm the localized template and SMS log are created.
7. Temporarily disable the NIR API and repeat; confirm a legacy prediction is
   saved with `fallback_used: true`.
8. In Twilio, send a test message and confirm the signed status callback changes
   the corresponding `sms_logs.delivery_status` to `delivered` or `failed`.

## Rollback

Set `ML_API_ENABLED=false` and redeploy. Existing prediction and advisory
routes then use the legacy pipeline while preserving audit records.

## Release gates

- All automated tests pass.
- No API key appears in source, logs, or client responses.
- NIR and fallback smoke tests pass.
- Product and agronomy approve farmer-facing messages.
- Production rollout starts with a limited plot cohort.
- Twilio sender IDs, WhatsApp business templates, and India DLT registrations
  are approved for the exact farmer-facing message content.
