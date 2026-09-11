# NIR API Integration Contract

This contract defines the interface between the backend and the ML team's NIR
service. The backend uses the service as the primary irrigation predictor and
keeps the legacy prediction pipeline as the temporary safety fallback.

## Service configuration

| Setting | Required | Default |
|---|---:|---|
| `ML_API_ENABLED` | No | `true` |
| `ML_API_URL` | No | `https://nir-api.onrender.com` |
| `ML_API_KEY` | Yes when enabled | unset |
| `ML_API_TIMEOUT_SECONDS` | No | `10` |
| `ML_API_MODEL_VERSION` | No | API response version |

`ML_API_KEY` must be supplied through deployment secrets or a local `.env`
file. It must never be committed to the repository, logs, or client code.

Live ingestion is used by default. For local tests or demos only, call
`POST /ingest/{plot_id}?use_mock=true`; this prevents generated mock
observations from being used accidentally in production.

## Request

The backend sends `POST {ML_API_URL}/predict` with an `X-API-Key` header and
the following JSON body:

```json
{
  "soil_moisture": 35.5,
  "temperature": 28.5,
  "rainfall": 45.2,
  "et0": 5.2,
  "crop_stage": 2,
  "crop": "cotton",
  "soil_type": "black"
}
```

| Field | Type | Constraint | Backend source |
|---|---|---|---|
| `soil_moisture` | number | `0..100` percent | water-balance Stage 1 estimate |
| `temperature` | number | `-10..60` °C | latest canonical temperature/LST |
| `rainfall` | number | `>=0` mm | canonical 7-day rainfall |
| `et0` | number | `>=0` mm/day | canonical ET0 |
| `crop_stage` | integer | `1..3` | canonical crop stage mapping |
| `crop` | string | non-empty | plot crop type |
| `soil_type` | string | accepted NIR class | normalized plot soil texture; Yavatmal black cotton soil maps to `black` |

The current implementation clamps numeric values to the API's accepted
ranges. Missing ET0 or temperature prevents a remote call and uses the
legacy fallback instead of inventing a measurement.

## Response

The ML service must return:

```json
{
  "nir": 22.4,
  "advice": "SAFE: No irrigation needed for 7 days.",
  "urgency": "SAFE",
  "confidence": 0.91,
  "model_version": "v2.0.0-2025-09-04"
}
```

`confidence` and `model_version` are supported when present. Until every
deployment returns them, the backend uses a documented urgency fallback for
confidence and the configured `ML_API_MODEL_VERSION` or API `version` field
for model identification.

| Field | Type | Constraint |
|---|---|---|
| `nir` | number | `0..100` percent |
| `advice` | string | required |
| `urgency` | string | `URGENT`, `MODERATE`, or `SAFE` |
| `confidence` | number | optional, `0..1` (or `0..100` percent; backend normalizes) |
| `model_version` | string | preferred; `version` is accepted temporarily |

## Backend mapping

The ML service is the source of truth for NIR/NRI. The backend does not
recalculate this value. It stores the returned percentage and uses the
returned `urgency` (which is the model's interpretation of that value) to
select the farmer message and delivery priority.

| API urgency | Advisory class | Reason code |
|---|---|---|
| `URGENT` | `irrigate_now` | `urgent_irrigation_needed` |
| `MODERATE` | `irrigate_soon` | `monitor_and_prepare` |
| `SAFE` | `no_action` | `safe_no_irrigation` |

Every saved prediction records the model version and the complete request and
response snapshot. Remote failures are logged and use the legacy prediction
pipeline during the 30-day safety period.

## ML team acceptance checklist

- [ ] Return `confidence` on every response.
- [ ] Return immutable `model_version` for every deployment.
- [ ] Confirm seven-field semantics and units.
- [ ] Confirm supported batch size, rate limits, and error status codes.
- [ ] Confirm uptime/maintenance expectations and the weekly support owner.
