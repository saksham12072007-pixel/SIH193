"""Endpoints for ML predictions and model explanations."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plot
from app.services.ml_prediction_service import MLPredictionService, PredictionType

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.post("/irrigation-stress/{plot_id}", status_code=status.HTTP_201_CREATED)
def predict_irrigation_stress(plot_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Predict irrigation stress for a plot using water-balance model.

    Returns: predicted_class (no_stress, mild_stress, moderate_stress, severe_stress),
    confidence score, and explanation with feature impacts.
    """
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    service = MLPredictionService(db)
    try:
        result = service.predict_irrigation_stress(plot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Save to database for audit trail
    service.save_prediction(result)

    return {
        "prediction_id": result.prediction_id,
        "plot_id": result.plot_id,
        "predicted_class": result.advisory_class,
        "confidence": result.confidence_score,
        "soil_moisture_pct": result.explanation.get(
            "soil_moisture_pct",
            result.explanation.get("stage1_soil_moisture_pct"),
        ),
        "nir_percent": result.explanation.get("nir_percent"),
        "advice": result.explanation.get("advice"),
        "urgency": result.explanation.get("urgency"),
        "reason": result.explanation.get("reason", result.explanation.get("advice")),
        "fallback_used": result.explanation.get("fallback_used", False),
        "model_version": result.model_version,
        "reason_code": result.reason_code,
        "created_at": result.predicted_at.isoformat(),
    }


@router.get("/explain/{prediction_id}")
def explain_prediction(prediction_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Get SHAP-like explanation for a prediction.

    Shows feature impacts, feature importance, and reasoning.
    """
    service = MLPredictionService(db)
    explanation = service.explain_prediction(prediction_id)

    if not explanation:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return explanation


@router.get("/latest/{plot_id}")
def get_latest_prediction(plot_id: str, db: Session = Depends(get_db)) -> dict:
    """Retrieve latest irrigation stress prediction for a plot."""
    plot = db.query(Plot).filter(Plot.plot_id == plot_id).first()
    if not plot:
        raise HTTPException(status_code=404, detail="Plot not found")

    service = MLPredictionService(db)
    pred = service.get_latest_prediction(plot_id, PredictionType.IRRIGATION_STRESS)

    if not pred:
        raise HTTPException(status_code=404, detail="No predictions found for this plot")

    return {
        "prediction_id": pred.prediction_id,
        "plot_id": pred.plot_id,
        "predicted_class": pred.advisory_class,
        "confidence": pred.confidence_score,
        "model_version": pred.model_version,
        "reason_code": pred.reason_code,
        "created_at": pred.predicted_at.isoformat(),
    }
