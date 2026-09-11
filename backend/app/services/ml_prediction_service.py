"""
ML Prediction Service -- sec 12.4

Primary pipeline:
  NIR API -- seven validated inputs -> NIR %, urgency, and advice

Legacy Stage 1 + Stage 2 remain available as a safety fallback during the
agreed transition period.

Every prediction records model_version for audit / evaluation-runs tracing (sec 12.4.2).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models import MlPrediction, Plot, PlotFeatures
from app.services.feature_engineering_service import FeatureEngineeringService
from app.services.ml_training_service import MLTrainingService
from app.services.nir_api_service import NirApiError, NirApiService
from app.services.water_balance_model import IrrigationStress, WaterBalanceBucketModel
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class PredictionType(str, Enum):
    """Type of ML prediction."""
    IRRIGATION_STRESS = "irrigation_stress"


@dataclass
class SoilMoistureResult:
    """Stage 1 output -- soil moisture regression."""
    plot_id: str
    soil_moisture_pct: float   # 0-100 %
    cwsi: float                # Crop Water Stress Index 0-1
    confidence: float
    model_version: str
    feature_snapshot: dict
    predicted_at: datetime


@dataclass
class AdvisoryDecision:
    """Stage 2 output -- rule-based decision layer."""
    plot_id: str
    advisory_class: str        # no_action | monitor | irrigate_soon | irrigate_now
    reason_code: str
    confidence: float
    stage1_result: SoilMoistureResult
    model_version: str
    predicted_at: datetime


@dataclass
class PredictionResult:
    """Combined Stage 1 + Stage 2 output (returned by /advise endpoint)."""
    prediction_id: str
    plot_id: str
    prediction_type: PredictionType
    predicted_value: float
    advisory_class: str
    confidence_score: float
    reason_code: str
    explanation: dict
    model_version: str
    predicted_at: datetime


# ------------------------------------------------------------------
# Stage 1: Soil Moisture Regression
# ------------------------------------------------------------------

class SoilMoistureModel:
    """
    sec 12.4.1 -- Stage 1 regression module (independently deployable).

    MVP: water-balance bucket model as weak-label regression proxy.
    Production upgrade path: train XGBoost/LightGBM on plot_features table
    and swap in here without touching the Stage 2 decision layer.
    """

    MODEL_VERSION = "v1.1-water-balance-stage1"

    def __init__(self, db: Session, artifacts_dir: str | Path | None = None) -> None:
        self.db = db
        self._wb = WaterBalanceBucketModel(db)
        self._features = FeatureEngineeringService(db)
        self._artifacts_dir = artifacts_dir

    def predict(self, plot_id: str) -> SoilMoistureResult:
        """Run Stage 1 regression and return soil moisture % and CWSI.

        Serving order (doc 13.5 / 15.4): the promoted XGBoost artifact is used
        when available; the water-balance bucket model remains the safety
        fallback so Stage 1 never fails silently.
        """
        plot = self.db.query(Plot).filter(Plot.plot_id == plot_id).first()
        if not plot:
            raise ValueError(f"Plot {plot_id} not found")

        trained = self._try_trained_model(plot_id, plot)
        if trained is not None:
            return trained

        wb = self._wb.estimate_stress(plot_id)
        if wb.confidence <= 0:
            raise ValueError("Insufficient satellite data for Stage 1 prediction")

        features = self._features.get_features_for_plot(plot_id)
        if not features:
            raise ValueError("Insufficient satellite data for Stage 1 prediction")

        cwsi = max(0.0, min(1.0, 1.0 - (wb.soil_moisture_pct / 100.0)))

        feature_snapshot = {
            "model_type": "water-balance-bucket",
            "soil_moisture_pct": wb.soil_moisture_pct,
            "confidence": float(wb.confidence),
            "reason": wb.reason,
            "ndvi": float(features.ndvi) if features.ndvi is not None else None,
            "ndvi_trend": float(features.ndvi_trend) if features.ndvi_trend is not None else None,
            "rainfall_mm": float(features.rainfall_mm) if features.rainfall_mm is not None else None,
            "temperature_max": float(features.temperature_max) if features.temperature_max is not None else None,
            "days_since_sowing": features.days_since_sowing,
            "sar_vv": float(features.sar_vv) if features.sar_vv is not None else None,
            "sar_vh": float(features.sar_vh) if features.sar_vh is not None else None,
        }

        return SoilMoistureResult(
            plot_id=plot_id,
            soil_moisture_pct=float(wb.soil_moisture_pct),
            cwsi=cwsi,
            confidence=float(wb.confidence),
            model_version=self.MODEL_VERSION,
            feature_snapshot=feature_snapshot,
            predicted_at=utc_now(),
        )

    # ------------------------------------------------------------------
    # Trained XGBoost serving path (doc 15.4.2 -- Stage 1 model upgrade)
    # ------------------------------------------------------------------

    def _try_trained_model(self, plot_id: str, plot: Plot) -> SoilMoistureResult | None:
        """Serve the promoted XGBoost artifact if available; else None (fallback)."""
        try:
            artifact = MLTrainingService(self.db, artifacts_dir=self._artifacts_dir).load_promoted_model()
            if artifact is None:
                return None

            row = (
                self.db.query(PlotFeatures)
                .filter(PlotFeatures.plot_id == plot_id)
                .order_by(PlotFeatures.obs_date.desc())
                .first()
            )
            if row is None:
                return None

            import numpy as np

            feature_vector = []
            for col in artifact["feature_columns"]:
                if col == "days_since_sowing":
                    days_since_sowing = (row.obs_date - plot.sowing_date).days if plot.sowing_date else 0
                    feature_vector.append(float(days_since_sowing))
                else:
                    value = getattr(row, col)
                    feature_vector.append(float(value) if value is not None else np.nan)

            import pandas as pd

            X = pd.DataFrame([dict(zip(artifact["feature_columns"], feature_vector))])
            fraction = float(np.clip(artifact["model"].predict(X)[0], 0.0, 1.0))
            soil_moisture_pct = fraction * 100.0
            cwsi = max(0.0, min(1.0, 1.0 - fraction))

            metrics = artifact.get("metrics", {})
            r2 = metrics.get("r2")
            confidence = max(0.5, min(0.95, float(r2))) if r2 is not None else 0.75

            features = self._features.get_features_for_plot(plot_id)
            feature_snapshot = {
                "model_type": "xgboost-stage1",
                "soil_moisture_pct": soil_moisture_pct,
                "confidence": confidence,
                "reason": "promoted XGBoost Stage-1 regression (FPR gate passed)",
                "ndvi": float(features.ndvi) if features and features.ndvi is not None else None,
                "ndvi_trend": (
                    float(features.ndvi_trend)
                    if features and features.ndvi_trend is not None
                    else None
                ),
                "rainfall_mm": (
                    float(features.rainfall_mm)
                    if features and features.rainfall_mm is not None
                    else None
                ),
                "temperature_max": (
                    float(features.temperature_max)
                    if features and features.temperature_max is not None
                    else None
                ),
                "days_since_sowing": features.days_since_sowing if features else None,
                "sar_vv": float(row.vv_db) if row.vv_db is not None else None,
                "sar_vh": float(row.vh_db) if row.vh_db is not None else None,
            }

            return SoilMoistureResult(
                plot_id=plot_id,
                soil_moisture_pct=soil_moisture_pct,
                cwsi=cwsi,
                confidence=confidence,
                model_version=artifact["model_version"],
                feature_snapshot=feature_snapshot,
                predicted_at=utc_now(),
            )
        except Exception as exc:
            logger.warning(
                "Trained Stage-1 model unavailable for plot %s; falling back to "
                "water-balance: %s",
                plot_id,
                exc,
            )
            return None


# ------------------------------------------------------------------
# Stage 2: Rule-based Decision Layer
# ------------------------------------------------------------------

class AdvisoryDecisionEngine:
    """
    sec 12.4.1 -- Stage 2 rule-based decision layer (independently deployable).

    Takes Stage 1 output (soil moisture %, CWSI) plus contextual signals
    (crop stage, rain forecast, NDVI trend) and maps to an advisory class.

    Rule-based so it is easy to audit, inspect, and modify without retraining
    the Stage 1 ML model.
    """

    MODEL_VERSION = "v1.1-rule-based-stage2"

    def __init__(self, db: Session) -> None:
        self.db = db
        self._features = FeatureEngineeringService(db)

    def decide(self, stage1: SoilMoistureResult) -> AdvisoryDecision:
        """Apply Stage 2 rules to Stage 1 output and produce an advisory decision."""
        plot_id = stage1.plot_id
        features = stage1.feature_snapshot

        soil_moisture_pct = stage1.soil_moisture_pct
        cwsi = stage1.cwsi
        ndvi_trend = features.get("ndvi_trend") or 0.0
        rainfall_mm = features.get("rainfall_mm") or 0.0

        # Stage 2 rules (explainable threshold-based logic)
        if soil_moisture_pct > 80:
            advisory_class = "no_action"
            reason_code = "adequate_moisture"
        elif soil_moisture_pct > 60 and rainfall_mm > 5:
            advisory_class = "no_action"
            reason_code = "recent_rainfall_adequate"
        elif soil_moisture_pct > 50:
            if ndvi_trend < -0.05:
                advisory_class = "monitor"
                reason_code = "declining_ndvi_trend"
            else:
                advisory_class = "monitor"
                reason_code = "stage_monitor"
        elif soil_moisture_pct > 25:
            advisory_class = "irrigate_soon"
            reason_code = "moderate_stress_detected"
        else:
            advisory_class = "irrigate_now"
            reason_code = "low_soil_moisture"

        # Confidence: inherit from Stage 1 but discount for borderline thresholds
        confidence = stage1.confidence
        if advisory_class in {"monitor", "irrigate_soon"} and 40 < soil_moisture_pct < 60:
            confidence *= 0.85  # borderline zone -- lower confidence

        return AdvisoryDecision(
            plot_id=plot_id,
            advisory_class=advisory_class,
            reason_code=reason_code,
            confidence=round(confidence, 4),
            stage1_result=stage1,
            model_version=self.MODEL_VERSION,
            predicted_at=utc_now(),
        )


# ------------------------------------------------------------------
# Combined Two-Stage Pipeline (used by /advise endpoint)
# ------------------------------------------------------------------

class MLPredictionService:
    """
    Orchestrate NIR API predictions with a legacy model fallback.

    Stage 1 output remains inspectable independently via /soil-moisture endpoint.
    Every prediction carries model_version for audit tracing (sec 12.4.2).
    """

    MODEL_VERSION = "v1.1-two-stage"

    def __init__(self, db: Session):
        self.db = db
        self._stage1 = SoilMoistureModel(db)
        self._stage2 = AdvisoryDecisionEngine(db)
        self._features_service = FeatureEngineeringService(db)
        self._nir_api = NirApiService()

    # ---- Stage 1 only (for /soil-moisture endpoint) ----

    def predict_soil_moisture(self, plot_id: str) -> SoilMoistureResult:
        """Run Stage 1 regression and return soil moisture + CWSI independently."""
        return self._stage1.predict(plot_id)

    # ---- Full two-stage pipeline (for /advise endpoint) ----

    def predict_irrigation_stress(self, plot_id: str) -> PredictionResult:
        """Use the NIR API primarily, with the legacy model as a safety fallback."""
        stage1 = self._stage1.predict(plot_id)

        nir_input, input_fallback_reason = self._build_nir_input(plot_id, stage1)
        if nir_input is not None:
            try:
                nir = self._nir_api.predict(nir_input)
                urgency_map = {
                    "URGENT": ("irrigate_now", "urgent_irrigation_needed", 0.95),
                    "MODERATE": ("irrigate_soon", "monitor_and_prepare", 0.70),
                    "SAFE": ("no_action", "safe_no_irrigation", 0.50),
                }
                advisory_class, reason_code, urgency_confidence = urgency_map[nir.urgency]
                return PredictionResult(
                    prediction_id=str(uuid.uuid4()),
                    plot_id=plot_id,
                    prediction_type=PredictionType.IRRIGATION_STRESS,
                    predicted_value=nir.nir,
                    advisory_class=advisory_class,
                    confidence_score=(
                        nir.confidence
                        if nir.confidence is not None
                        else urgency_confidence
                    ),
                    reason_code=reason_code,
                    explanation={
                        "provider": "nir_api",
                        "nir_percent": nir.nir,
                        "advice": nir.advice,
                        "urgency": nir.urgency,
                        "confidence": nir.confidence,
                        "nir_request": nir.request,
                        "fallback_used": False,
                        "fallback_reason": None,
                        "stage1_soil_moisture_pct": stage1.soil_moisture_pct,
                    },
                    model_version=nir.model_version,
                    predicted_at=utc_now(),
                )
            except NirApiError as exc:
                # The existing two-stage model is the agreed 30-day safety net.
                logger.warning(
                    "NIR API unavailable for plot %s; using legacy fallback: %s",
                    plot_id,
                    exc,
                )

        decision = self._stage2.decide(stage1)

        explanation = {
            "provider": "legacy_fallback",
            "fallback_used": True,
            "fallback_reason": input_fallback_reason or "NIR API request failed",
            **stage1.feature_snapshot,
            "stage2_rules": {
                "advisory_class": decision.advisory_class,
                "reason_code": decision.reason_code,
                "soil_moisture_pct": stage1.soil_moisture_pct,
                "cwsi": stage1.cwsi,
            },
            "thresholds": {
                "no_action": "> 80%",
                "monitor": "50-80%",
                "irrigate_soon": "25-50%",
                "irrigate_now": "< 25%",
            },
        }

        return PredictionResult(
            prediction_id=str(uuid.uuid4()),
            plot_id=plot_id,
            prediction_type=PredictionType.IRRIGATION_STRESS,
            predicted_value=stage1.soil_moisture_pct,
            advisory_class=decision.advisory_class,
            confidence_score=decision.confidence,
            reason_code=decision.reason_code,
            explanation=explanation,
            model_version=self.MODEL_VERSION,
            predicted_at=utc_now(),
        )

    def _build_nir_input(
        self, plot_id: str, stage1: SoilMoistureResult
    ) -> tuple[dict | None, str | None]:
        """Build the agreed seven-field request from the latest canonical row."""
        plot = self.db.query(Plot).filter(Plot.plot_id == plot_id).first()
        features = self.db.query(PlotFeatures).filter(
            PlotFeatures.plot_id == plot_id
        ).order_by(PlotFeatures.obs_date.desc()).first()
        if not plot:
            return None, "plot not found"
        if not features:
            logger.warning("No canonical features available for plot %s", plot_id)
            return None, "canonical features unavailable"
        if features.et0 is None:
            logger.warning("ET0 unavailable for plot %s", plot_id)
            return None, "ET0 unavailable"
        if features.lst is None:
            logger.warning("Temperature unavailable for plot %s", plot_id)
            return None, "temperature unavailable"

        crop_stage_map = {
            "seedling": 1,
            "vegetative": 1,
            "flowering": 2,
            "pod_fill": 3,
            "mature": 3,
        }
        crop_stage = crop_stage_map.get((features.crop_stage or "").lower(), 2)
        soil_type = (plot.soil_texture or "").strip().lower()
        # The NIR contract accepts agronomic soil classes rather than every
        # database texture label. Vidarbha black cotton soil is the pilot
        # default; unknown values remain explicit instead of being guessed.
        soil_type = {
            "black cotton": "black",
            "black cotton soil": "black",
            "medium black": "black",
            "red": "red",
            "red soil": "red",
            "sandy": "sandy",
            "sandy loam": "sandy",
            "clay": "clay",
            "clayey": "clay",
            "loam": "loamy",
        }.get(soil_type, soil_type or "unknown")
        return {
            "soil_moisture": max(0.0, min(100.0, stage1.soil_moisture_pct)),
            "temperature": max(-10.0, min(60.0, float(features.lst))),
            "rainfall": max(0.0, float(features.rainfall_7d or 0.0)),
            "et0": max(0.0, float(features.et0)),
            "crop_stage": crop_stage,
            "crop": plot.crop_type,
            "soil_type": soil_type,
        }, None

    def save_prediction(self, result: PredictionResult) -> MlPrediction:
        """Save prediction to the database for audit and model evaluation (sec 12.4.2)."""
        ml_pred = MlPrediction(
            prediction_id=result.prediction_id,
            plot_id=result.plot_id,
            model_version=result.model_version,
            stage1_soil_moisture_estimate=result.predicted_value,
            stage1_cwsi_estimate=result.explanation.get("stage2_rules", {}).get("cwsi"),
            advisory_class=result.advisory_class,
            confidence_score=result.confidence_score,
            reason_code=result.reason_code,
            input_feature_snapshot=result.explanation,
            predicted_at=result.predicted_at,
        )
        self.db.add(ml_pred)
        self.db.commit()
        self.db.refresh(ml_pred)
        return ml_pred

    def get_latest_prediction(self, plot_id: str, prediction_type: PredictionType) -> Optional[MlPrediction]:
        """Retrieve the latest prediction for a plot."""
        return (
            self.db.query(MlPrediction)
            .filter(MlPrediction.plot_id == plot_id)
            .order_by(MlPrediction.predicted_at.desc())
            .first()
        )

    def explain_prediction(self, prediction_id: str) -> dict:
        """Return a structured SHAP-like explanation for a stored prediction (sec 12.4.4)."""
        pred = self.db.query(MlPrediction).filter(MlPrediction.prediction_id == prediction_id).first()
        if not pred:
            return {}

        explanation = pred.input_feature_snapshot or {}
        features = explanation

        impacts: dict[str, dict] = {}

        ndvi = features.get("ndvi")
        if ndvi is not None:
            impacts["ndvi"] = {"value": ndvi, "impact": -0.5 * ndvi, "direction": "negative",
                                "note": "vegetation stress signal"}

        sar_vv = features.get("sar_vv")
        if sar_vv is not None:
            impacts["sar_vv"] = {"value": sar_vv, "impact": -0.3 * abs(sar_vv) / 30, "direction": "negative",
                                  "note": "primary soil moisture signal (cloud-proof)"}

        rainfall = features.get("rainfall_mm")
        if rainfall is not None:
            impacts["rainfall"] = {"value": rainfall, "impact": -0.1 * rainfall, "direction": "negative",
                                    "note": "recent rainfall reduces stress"}

        days_sown = features.get("days_since_sowing")
        if isinstance(days_sown, int) and 60 <= days_sown <= 120:
            impacts["growth_stage"] = {"value": "mid_season", "impact": 0.3, "direction": "positive",
                                        "note": "peak water demand (mid-season Kc)"}

        ndvi_trend = features.get("ndvi_trend")
        if ndvi_trend is not None and ndvi_trend < -0.05:
            impacts["ndvi_trend"] = {"value": ndvi_trend, "impact": 0.4, "direction": "positive",
                                      "note": "declining NDVI trend indicates stress"}

        return {
            "prediction_id": prediction_id,
            "plot_id": pred.plot_id,
            "advisory_class": pred.advisory_class,
            "confidence_score": float(pred.confidence_score) if pred.confidence_score is not None else None,
            "reason_code": pred.reason_code,
            "stage1_soil_moisture_pct": float(pred.stage1_soil_moisture_estimate) if pred.stage1_soil_moisture_estimate is not None else None,
            "stage1_cwsi": float(pred.stage1_cwsi_estimate) if pred.stage1_cwsi_estimate is not None else None,
            "feature_impacts": impacts,
            "base_explanation": explanation.get("reason", ""),
            "model_version": pred.model_version,
        }

    # ------------------------------------------------------------------
    # Static helpers (kept for backward compatibility)
    # ------------------------------------------------------------------

    @staticmethod
    def _reason_code_for_stress(stress: IrrigationStress) -> str:
        if stress == IrrigationStress.NO_STRESS:
            return "adequate_moisture"
        if stress == IrrigationStress.MILD_STRESS:
            return "stage_monitor"
        if stress == IrrigationStress.MODERATE_STRESS:
            return "declining_ndvi_trend"
        return "low_soil_moisture"

    @staticmethod
    def _advisory_class_for_stress(stress: IrrigationStress) -> str:
        if stress == IrrigationStress.NO_STRESS:
            return "no_action"
        if stress == IrrigationStress.MILD_STRESS:
            return "monitor"
        if stress == IrrigationStress.MODERATE_STRESS:
            return "irrigate_soon"
        return "irrigate_now"
