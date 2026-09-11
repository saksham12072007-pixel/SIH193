"""
Model monitoring / evaluation endpoints -- sec 12.2 / 12.5

GET  /model/evaluation/{model_version}   -- serves dashboard model-monitoring panel
GET  /model/evaluation/latest            -- latest run per version / agro-zone
GET  /model/false-positives/{model_version}  -- false-positive drilldown view
POST /model/evaluation                   -- log a new evaluation run (retraining job)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import ModelEvaluationRun
from app.routers.institutional_auth import get_current_institutional_user
from app.services.model_evaluation_service import DEFAULT_FPR_THRESHOLD, ModelEvaluationService

router = APIRouter(prefix="/model", tags=["model-monitoring"])


@router.get("/evaluation/{model_version}")
def get_model_evaluation(
    model_version: str,
    agro_zone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_institutional_user),
) -> dict:
    """
    Retrieve evaluation metrics for a specific model version (sec 12.2).

    Returns RMSE/MAE/R2 (Stage 1) and Accuracy/Precision/Recall/F1/FPR (Stage 2).
    Used by the model-monitoring dashboard panel (sec 12.5.1).
    """
    service = ModelEvaluationService(db)
    runs = service.get_runs_for_version(model_version)

    if not runs:
        raise HTTPException(
            status_code=404,
            detail=f"No evaluation runs found for model version: {model_version!r}",
        )

    if agro_zone:
        runs = [r for r in runs if r.agro_zone == agro_zone]
        if not runs:
            raise HTTPException(
                status_code=404,
                detail=f"No evaluation runs for model={model_version!r} zone={agro_zone!r}",
            )

    return {
        "model_version": model_version,
        "agro_zone": agro_zone,
        "total_runs": len(runs),
        "latest": _format_run(runs[0]),
        "history": [_format_run(r) for r in runs],
    }


@router.get("/evaluation")
def get_latest_evaluations(
    agro_zone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_institutional_user),
) -> dict:
    """
    Return the latest evaluation run per model version (sec 12.5.1 dashboard).
    Optionally filtered by agro_zone.
    """
    service = ModelEvaluationService(db)
    runs = service.get_latest_per_version(agro_zone=agro_zone)
    return {
        "agro_zone": agro_zone,
        "fpr_threshold": DEFAULT_FPR_THRESHOLD,
        "versions": [_format_run(r) for r in runs],
    }


@router.get("/false-positives/{model_version}")
def get_false_positive_drilldown(
    model_version: str,
    agro_zone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_institutional_user),
) -> dict:
    """
    False-positive drilldown view (sec 12.5.3).

    Lists evaluation runs where FPR exceeded the threshold, helping a KVK/technical
    admin spot systematic issues (e.g., a particular soil type or crop stage the
    model handles poorly).
    """
    service = ModelEvaluationService(db)
    drilldown = service.get_false_positive_drilldown(model_version, agro_zone=agro_zone)
    return {
        "model_version": model_version,
        "agro_zone": agro_zone,
        "fpr_threshold": DEFAULT_FPR_THRESHOLD,
        "failed_runs": drilldown,
        "failed_count": len(drilldown),
    }


@router.post("/evaluation", status_code=status.HTTP_201_CREATED)
def log_evaluation_run(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_institutional_user),
) -> dict:
    """
    Log a new model evaluation run and check the FPR promotion gate (sec 12.2 / 13.5).

    Expected payload fields (all optional except model_version):
      model_version, agro_zone, trained_at,
      rmse, mae, r2,
      accuracy, precision_score, recall, f1,
      tp, fp, tn, fn,   <- preferred for automatic FPR calculation
      fpr,              <- or provide FPR directly
      shap_feature_importance,
      fpr_threshold,
      notes

    Returns the created evaluation run and whether promotion is allowed.
    """
    if "model_version" not in payload:
        raise HTTPException(status_code=400, detail="model_version is required")

    service = ModelEvaluationService(db)

    # Support direct FPR injection (if caller computes it externally)
    if "fpr" in payload and "tp" not in payload:
        payload.setdefault("tp", None)
        payload.setdefault("fp", None)
        payload.setdefault("tn", None)
        payload.setdefault("fn", None)

    try:
        run = service.log_evaluation(
            model_version=payload["model_version"],
            agro_zone=payload.get("agro_zone"),
            rmse=payload.get("rmse"),
            mae=payload.get("mae"),
            r2=payload.get("r2"),
            accuracy=payload.get("accuracy"),
            precision_score=payload.get("precision_score"),
            recall=payload.get("recall"),
            f1=payload.get("f1"),
            tp=payload.get("tp"),
            fp=payload.get("fp"),
            tn=payload.get("tn"),
            fn=payload.get("fn"),
            shap_feature_importance=payload.get("shap_feature_importance"),
            fpr_threshold=payload.get("fpr_threshold", DEFAULT_FPR_THRESHOLD),
            notes=payload.get("notes"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    promotable = run.passed_fpr_threshold

    return {
        "run": _format_run(run),
        "promotion_allowed": promotable,
        "message": (
            "Model PASSED FPR gate and may be promoted to production."
            if promotable
            else "Model FAILED FPR gate. Promotion is BLOCKED pending manual review."
        ),
    }


def _format_run(run: ModelEvaluationRun) -> dict:
    return {
        "run_id": run.run_id,
        "model_version": run.model_version,
        "trained_at": run.trained_at.isoformat() if run.trained_at else None,
        "agro_zone": run.agro_zone,
        "stage1": {
            "rmse": float(run.rmse) if run.rmse is not None else None,
            "mae": float(run.mae) if run.mae is not None else None,
            "r2": float(run.r2) if run.r2 is not None else None,
        },
        "stage2": {
            "accuracy": float(run.accuracy) if run.accuracy is not None else None,
            "precision": float(run.precision_score) if run.precision_score is not None else None,
            "recall": float(run.recall) if run.recall is not None else None,
            "f1": float(run.f1) if run.f1 is not None else None,
            "fpr": float(run.fpr) if run.fpr is not None else None,
        },
        "passed_fpr_threshold": run.passed_fpr_threshold,
        "shap_feature_importance": run.shap_feature_importance,
        "notes": run.notes,
        "created_at": run.created_at.isoformat(),
    }
