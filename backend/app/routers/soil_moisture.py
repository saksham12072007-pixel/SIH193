"""
Stage 1 soil moisture endpoint -- sec 12.2

POST /soil-moisture/{plot_id}
  Exposes Stage 1 regression output independently (soil moisture %, CWSI)
  so it can be evaluated and monitored separately from the final advisory.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plot
from app.services.ml_prediction_service import MLPredictionService

router = APIRouter(prefix="/soil-moisture", tags=["soil-moisture"])


@router.post("/{plot_id}", status_code=status.HTTP_200_OK)
def get_soil_moisture(plot_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Run Stage 1 regression independently and return soil moisture estimate.

    Returns soil moisture % and CWSI without triggering the full advisory pipeline.
    Useful for:
      - Evaluating Stage 1 accuracy independently of Stage 2 decision rules
      - Monitoring soil moisture trends without sending farmer advisories
      - Model-monitoring dashboard (RMSE/MAE/R2 against ISMN or water-balance labels)
    """
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    service = MLPredictionService(db)
    try:
        result = service.predict_soil_moisture(plot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "plot_id": result.plot_id,
        "soil_moisture_pct": result.soil_moisture_pct,
        "cwsi": result.cwsi,
        "confidence": result.confidence,
        "model_version": result.model_version,
        "predicted_at": result.predicted_at.isoformat(),
        "feature_snapshot": result.feature_snapshot,
        "stage": "stage1_regression",
    }
