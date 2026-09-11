"""
Satellite data ingestion endpoints -- sec 12.2 / 12.3

POST /ingest/{plot_id}   -- triggers ingestion with date-snapping to plot_features
GET  /ingest/latest/{plot_id}  -- latest raw satellite readings
GET  /ingest/features/{plot_id}/{obs_date}  -- canonical plot_features row
POST /ingest/label/{plot_id}/{obs_date}  -- write soil moisture label (water-balance job)
POST /ingest/water-balance-labels/{plot_id} -- run water-balance label job for a plot
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plot, SatelliteData
from app.services.ingestion_service import IngestionService, WaterBalanceLabelJob
from app.services.plot_features_service import PlotFeaturesService

router = APIRouter(prefix="/ingest", tags=["ingestion"])
legacy_router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/{plot_id}", status_code=status.HTTP_202_ACCEPTED)
@legacy_router.post("/trigger/{plot_id}", status_code=status.HTTP_202_ACCEPTED)
def trigger_ingestion(
    plot_id: str,
    use_mock: bool = Query(
        False,
        description="Use generated data instead of configured live ingestion providers.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """
    Trigger satellite data ingestion for a plot.

    sec 12.2 / 12.3.1: writes to plot_features using the "nearest valid
    observation per source" date-snapping join logic (11.4), not a naive
    same-day merge.  Cloud/quality masking + outlier rejection applied
    before feature computation (sec 12.3.3).  Live ingestion is the default;
    pass ``use_mock=true`` only for local tests or demos.
    """
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    service = IngestionService(db)
    data = service.fetch_plot_cycle(plot_id, use_mock=use_mock)

    if data is None:
        raise HTTPException(status_code=500, detail="Failed to fetch satellite data")

    pred = service.last_prediction_result
    return {
        "status": "ingestion_triggered",
        "plot_id": plot_id,
        "records_ingested": len(data),
        "data_types": list(set([d.data_type for d in data])),
        "note": "plot_features row upserted with date-snapping alignment (sec 11.4)",
        "prediction": {
            "prediction_id": pred.prediction_id,
            "advisory_class": pred.advisory_class,
            "confidence_score": pred.confidence_score,
            "soil_moisture_pct": pred.predicted_value,
            "model_version": pred.model_version,
        } if pred else None,
    }


@router.get("/latest/{plot_id}")
def get_latest_satellite_data(plot_id: str, db: Session = Depends(get_db)) -> dict:
    """Retrieve latest raw satellite data for a plot."""
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    service = IngestionService(db)
    ndvi_data = service.get_latest_satellite_data(plot_id, data_source="sentinel2", data_type="ndvi")
    sar_data = service.get_latest_satellite_data(plot_id, data_source="sentinel1", data_type="sar")
    weather_data = service.get_latest_satellite_data(plot_id, data_source="weather", data_type="weather")

    return {
        "plot_id": plot_id,
        "ndvi": [
            {
                "date": d.observation_date.isoformat(),
                "value": d.value,
                "cloud_coverage": d.cloud_coverage,
            }
            for d in ndvi_data[:1]
        ],
        "sar": [
            {
                "date": d.observation_date.isoformat(),
                "value": d.value,
            }
            for d in sar_data[:1]
        ],
        "weather": [
            {
                "date": d.observation_date.isoformat(),
                "value": d.value,
            }
            for d in weather_data[:1]
        ],
    }


@router.get("/features/{plot_id}/{obs_date}")
def get_plot_features(plot_id: str, obs_date: date, db: Session = Depends(get_db)) -> dict:
    """
    Retrieve the canonical plot_features row for (plot_id, obs_date).

    This is the auditable feature record used for model training and serving.
    """
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    service = PlotFeaturesService(db)
    row = service.get_for_plot(plot_id, obs_date)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No feature row found for plot={plot_id} date={obs_date}. "
                   "Trigger ingestion first via POST /ingest/{plot_id}",
        )

    return {
        "plot_id": row.plot_id,
        "obs_date": row.obs_date.isoformat(),
        "sar": {"vv_db": row.vv_db, "vh_db": row.vh_db, "delta_vv_7d": row.delta_vv_7d, "delta_vh_7d": row.delta_vh_7d},
        "optical": {"ndvi": row.ndvi, "ndwi": row.ndwi, "evi": row.evi, "savi": row.savi,
                    "delta_ndvi_7d": row.delta_ndvi_7d, "delta_ndvi_14d": row.delta_ndvi_14d},
        "weather": {
            "rainfall_1d": row.rainfall_1d, "rainfall_3d": row.rainfall_3d,
            "rainfall_7d": row.rainfall_7d, "rainfall_14d": row.rainfall_14d,
            "rain_forecast_48h": row.rain_forecast_48h, "et0": row.et0,
            "kc": row.kc, "etc": row.etc, "lst": row.lst,
        },
        "smap_sm": row.smap_sm,
        "crop_stage": row.crop_stage,
        "label": {
            "soil_moisture_label": row.soil_moisture_label,
            "label_source": row.label_source,
        },
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.post("/water-balance-labels/{plot_id}", status_code=status.HTTP_200_OK)
def run_water_balance_label_job(
    plot_id: str,
    lookback_days: int = 30,
    db: Session = Depends(get_db),
) -> dict:
    """
    Run the water-balance weak-label generator for a plot (sec 12.3.4).

    Assigns soil_moisture_label with label_source='water_balance' to unlabeled
    plot_features rows.  In production this is called by a scheduled job; this
    endpoint allows manual triggering per plot.
    """
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    job = WaterBalanceLabelJob(db)
    labelled = job.run_for_plot(plot_id, lookback_days=lookback_days)

    return {
        "plot_id": plot_id,
        "rows_labelled": labelled,
        "label_source": "water_balance",
        "lookback_days": lookback_days,
        "message": f"Water-balance labels assigned to {labelled} plot_features rows.",
    }
