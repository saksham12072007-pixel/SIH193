"""Dataset upload endpoint for CSV and Excel farm/plot imports."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Farmer, Plot, PlotFeatures, SatelliteData
from app.routers.institutional_auth import get_current_institutional_user
from app.services.ingestion_service import IngestionService
from app.services.sms_template_service import SMSTemplateService
from app.utils.time import utc_now

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/datasets", tags=["datasets"])

REQUIRED_COLUMNS = {"lat", "lon", "crop", "soil_type", "sowing_date"}
OPTIONAL_COLUMNS = {
    "nir", "confidence", "ndvi", "temperature", "rainfall", "farmer_id",
    "farmer_name", "phone_number", "state", "district", "village",
    "plot_nickname", "area", "plot_size_declared",
}


def _value(row: pd.Series, name: str):
    value = row.get(name)
    return None if pd.isna(value) else value


def _parse_date(value: object):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError("sowing_date is invalid")
    return parsed.date()


@router.post("/datasets/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    _current_user=Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    try:
        content = await file.read()
        frame = (
            pd.read_csv(io.BytesIO(content))
            if suffix == ".csv"
            else pd.read_excel(io.BytesIO(content))
        )
    except Exception as exc:
        logger.exception("Failed to parse dataset file=%s", filename)
        raise HTTPException(status_code=400, detail=f"Unable to parse dataset: {exc}") from exc

    frame.columns = [str(column).strip().lower() for column in frame.columns]
    # Accept the documented import template as well as the normalized API names.
    frame = frame.rename(columns={
        "farmer_id": "farmer_id",
        "farmer_name": "farmer_name",
        "plot_id": "plot_id",
        "plot_area_acres": "area",
        "latitude": "lat",
        "longitude": "lon",
        "phone_no": "phone_number",
        "crop_type": "crop",
        "sowing_date": "sowing_date",
        "nir": "nir",
        "ndvi": "ndvi",
        "rainfall_mm": "rainfall",
        "temperature_c": "temperature",
        "soil_moisture_percent": "soil_moisture",
        "et0_mm_per_day": "et0",
        "irrigation_requirement": "irrigation_requirement",
        "irrigation_alert": "irrigation_alert",
    })
    if "plot_id" not in frame.columns and "plant_id" not in frame.columns:
        raise HTTPException(status_code=422, detail="Dataset must include plot_id or plant_id")
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required columns: {', '.join(missing)}")

    inserted = 0
    updated = 0
    errors: list[dict[str, object]] = []
    created_farmers: dict[str, Farmer] = {}
    plot_ids_processed: set[str] = set()

    for row_number, row in frame.iterrows():
        row_index = int(row_number) + 2
        try:
            plot_id_value = _value(row, "plot_id") or _value(row, "plant_id")
            plot_id = str(plot_id_value).strip() if plot_id_value is not None else ""
            if not plot_id:
                plot_id = str(uuid.uuid4())

            latitude = float(_value(row, "lat"))
            longitude = float(_value(row, "lon"))
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError("lat/lon are outside valid ranges")

            existing = db.query(Plot).filter(Plot.plot_id == plot_id).first()
            farmer_id_value = _value(row, "farmer_id")
            farmer_id = str(farmer_id_value).strip() if farmer_id_value is not None else ""

            if existing is None:
                if not farmer_id:
                    farmer_id = str(uuid.uuid4())
                farmer = (
                    created_farmers.get(farmer_id)
                    or db.query(Farmer).filter(Farmer.farmer_id == farmer_id).first()
                )
                if farmer is None:
                    phone = str(_value(row, "phone_number") or f"+910000{abs(hash(farmer_id)) % 100000000:08d}")
                    farmer = Farmer(
                        farmer_id=farmer_id,
                        phone_number=phone[:15],
                        name=str(_value(row, "farmer_name") or "Dataset Import"),
                        state=str(_value(row, "state") or "") or None,
                        district=str(_value(row, "district") or "") or None,
                        consent_given_at=utc_now(),
                        registration_channel="dataset",
                    )
                    db.add(farmer)
                    created_farmers[farmer_id] = farmer

                plot = Plot(
                    plot_id=plot_id,
                    farmer_id=farmer_id,
                    location_point=f"POINT ({longitude} {latitude})",
                    location_precision="gps",
                    village_name=str(_value(row, "village") or "") or None,
                    plot_nickname=str(_value(row, "plot_nickname") or "") or None,
                    crop_type=str(_value(row, "crop")).strip().lower(),
                    soil_texture=str(_value(row, "soil_type")).strip(),
                    plot_size_declared=float(_value(row, "area") or _value(row, "plot_size_declared") or 0) or None,
                    sowing_date=_parse_date(_value(row, "sowing_date")),
                    status="active",
                )
                db.add(plot)
                inserted += 1
            else:
                existing.location_point = f"POINT ({longitude} {latitude})"
                existing.location_precision = "gps"
                existing.crop_type = str(_value(row, "crop")).strip().lower()
                existing.soil_texture = str(_value(row, "soil_type")).strip()
                existing.sowing_date = _parse_date(_value(row, "sowing_date"))
                if _value(row, "village") is not None:
                    existing.village_name = str(_value(row, "village"))
                area = _value(row, "area") or _value(row, "plot_size_declared")
                if area is not None:
                    existing.plot_size_declared = float(area)
                updated += 1

            plot_ids_processed.add(plot_id)

            observation_date = utc_now()
            feature_date = observation_date.date()
            features = (
                db.query(PlotFeatures)
                .filter(PlotFeatures.plot_id == plot_id, PlotFeatures.obs_date == feature_date)
                .first()
            )
            telemetry = {
                "ndvi": _value(row, "ndvi"),
                "rainfall_7d": _value(row, "rainfall"),
                "lst": _value(row, "temperature"),
            }
            if any(value is not None for value in telemetry.values()):
                if features is None:
                    features = PlotFeatures(plot_id=plot_id, obs_date=feature_date)
                    db.add(features)
                for field, value in telemetry.items():
                    if value is not None:
                        setattr(features, field, float(value))

            for data_type in ("nir", "ndvi"):
                value = _value(row, data_type)
                if value is None:
                    continue
                satellite_id = f"dataset-{plot_id}-{feature_date.isoformat()}-{data_type}"
                observation = db.query(SatelliteData).filter(
                    SatelliteData.satellite_id == satellite_id
                ).first()
                if observation is None:
                    db.add(SatelliteData(
                        satellite_id=satellite_id,
                        plot_id=plot_id,
                        data_source="dataset",
                        data_type=data_type,
                        value=str(float(value)),
                        observation_date=observation_date,
                        quality_flag="good",
                        ingestion_status="success",
                    ))
                else:
                    observation.value = str(float(value))
        except Exception as exc:
            errors.append({"row": row_index, "error": str(exc)})
            logger.warning("Skipping invalid dataset row=%s file=%s error=%s", row_index, filename, exc)

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist dataset file=%s", filename)
        raise HTTPException(status_code=500, detail="Dataset could not be saved") from None

    # Auto-chain ingestion + prediction + advisory generation (live-update
    # wiring, mirrors the /ingest auto-chain): the dashboard's aggregates/
    # trends are built entirely from Advisory rows, and the ML model needs
    # satellite/weather telemetry to score a plot -- a dataset import only
    # carries farm metadata (lat/lon/crop/soil/sowing_date), rarely NDVI/SAR/
    # weather readings. Running the real ingestion pipeline per plot pulls
    # that telemetry (mock or live, per INGESTION_PROVIDER) exactly like a
    # normal /ingest call does, so imported plots get scored the same way as
    # any other plot instead of silently having nothing to predict from.
    # No SMS is sent for a bulk import -- advisories are recorded silently.
    predictions_generated = 0
    advisories_generated = 0
    sms_service = SMSTemplateService(db)
    sms_service.get_or_create_templates()
    ingestion_service = IngestionService(db)
    for plot_id in sorted(plot_ids_processed):
        try:
            plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
            farmer = db.query(Farmer).filter(Farmer.farmer_id == plot.farmer_id).first() if plot else None
            if not plot or not farmer:
                continue

            ingestion_service.fetch_plot_cycle(plot_id)
            prediction = ingestion_service.last_prediction_result
            if prediction is None:
                continue
            predictions_generated += 1

            message = sms_service.generate_advisory_message(
                farmer_id=farmer.farmer_id,
                farmer_phone=farmer.phone_number,
                plot_id=plot_id,
                crop_type=plot.crop_type,
                language=farmer.preferred_language or "en",
                advisory_class=prediction.advisory_class,
                reason_code=prediction.reason_code,
                confidence=prediction.confidence_score,
            )
            if message:
                sms_service.create_advisory_record(message, prediction.prediction_id, sms_sent=False)
                advisories_generated += 1
        except Exception:
            logger.exception("Auto-ingest/prediction/advisory failed for imported plot=%s", plot_id)

    logger.info(
        "Dataset upload completed file=%s inserted=%d updated=%d errors=%d predictions=%d advisories=%d",
        filename, inserted, updated, len(errors), predictions_generated, advisories_generated,
    )
    return {
        "filename": filename,
        "rows_inserted": inserted,
        "rows_updated": updated,
        "errors": errors,
        "total_errors": len(errors),
        "predictions_generated": predictions_generated,
        "advisories_generated": advisories_generated,
    }
