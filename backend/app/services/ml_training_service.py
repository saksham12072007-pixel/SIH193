"""
ML Training Service -- implements the training loop from 13_Model_Flowchart.md.

Closes the "ML model part" gap identified against the documentation:

1. Dataset builder from canonical `plot_features` rows (doc 12.1) with the
   leakage guard enforced at query level: rows whose label came from SMAP are
   excluded whenever SMAP is used as an input feature (doc 13.3 rule).
2. Temporal train/test split (doc 13.4) -- random row-level splits are never
   used; the test set is always the most recent holdout in time.
3. XGBoost Stage-1 regression (doc 13.5 hyperparameters) predicting the
   soil-moisture label stored as a [0, 1] fraction (m3/m3 scale, matching the
   literature RMSE target of ~0.05-0.09 in doc 13.6).
4. Stage-2 classification metrics derived by applying the same rule thresholds
   as `AdvisoryDecisionEngine` to predictions vs. labels -- confusion matrix,
   precision/recall/F1 and FPR for the "irrigate_now" class.
5. Evaluation logged to `model_evaluation_runs` via `ModelEvaluationService`,
   which enforces the FPR promotion gate (doc 13.5): a model version is only
   promotable when FPR <= threshold.
6. Model artifacts persisted with joblib; `load_promoted_model()` is used by
   `SoilMoistureModel` to serve the trained model with water-balance fallback.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, cast

import joblib
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from xgboost import XGBRegressor

from app.core.config import get_settings
from app.models import ModelEvaluationRun, Plot, PlotFeatures
from app.services.model_evaluation_service import (
    DEFAULT_FPR_THRESHOLD,
    ModelEvaluationService,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# Doc 13.2 feature set -- all numeric columns available on the canonical row,
# plus days_since_sowing derived from plots.sowing_date. SMAP (smap_sm) is a
# context FEATURE only; the leakage guard below keeps it from ever being the
# training target.
FEATURE_COLUMNS: list[str] = [
    "vv_db",
    "vh_db",
    "delta_vv_7d",
    "delta_vh_7d",
    "ndvi",
    "ndwi",
    "evi",
    "savi",
    "delta_ndvi_7d",
    "delta_ndvi_14d",
    "rainfall_1d",
    "rainfall_3d",
    "rainfall_7d",
    "rainfall_14d",
    "rain_forecast_48h",
    "et0",
    "kc",
    "etc",
    "lst",
    "smap_sm",
    "days_since_sowing",
]

# Doc 13.5 -- XGBoost hyperparameters exposed for the tuning loop.
XGB_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "objective": "reg:squarederror",
    "random_state": 42,
}

# Minimum data before training is attempted (guards against degenerate fits).
MIN_LABELED_ROWS = 40
MIN_DISTINCT_DATES = 4
TEST_FRACTION = 0.2  # most-recent 20% of observation dates -> held-out test


def _advisory_class_for_moisture(soil_moisture_fraction: float, rainfall_7d: float | None) -> str:
    """Mirror of AdvisoryDecisionEngine thresholds (doc 13.6 Stage-2 mapping).

    Takes soil moisture as a [0, 1] fraction and the 7-day rainfall (mm) and
    returns one of the four advisory classes. Kept in sync with the rule
    engine in ml_prediction_service.py.
    """
    pct = soil_moisture_fraction * 100.0
    if pct > 80:
        return "no_action"
    if pct > 60 and (rainfall_7d or 0.0) > 5:
        return "no_action"
    if pct > 50:
        return "monitor"
    if pct > 25:
        return "irrigate_soon"
    return "irrigate_now"


@dataclass
class TrainingResult:
    """Summary of one retraining cycle (doc 13.5 loop)."""

    status: str  # trained | blocked | skipped
    model_version: Optional[str] = None
    labeled_rows: int = 0
    train_rows: int = 0
    test_rows: int = 0
    train_start: Optional[str] = None
    train_end: Optional[str] = None
    test_start: Optional[str] = None
    test_end: Optional[str] = None
    rmse: Optional[float] = None
    mae: Optional[float] = None
    r2: Optional[float] = None
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    fpr: Optional[float] = None
    passed_fpr_threshold: Optional[bool] = None
    shap_feature_importance: dict[str, float] = field(default_factory=dict)
    artifact_path: Optional[str] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class MLTrainingService:
    """Train, evaluate, gate, and persist the Stage-1 soil-moisture model."""

    def __init__(self, db: Session, artifacts_dir: str | Path | None = None) -> None:
        self.db = db
        self._eval_service = ModelEvaluationService(db)
        settings = get_settings()
        self.artifacts_dir = Path(artifacts_dir or settings.model_artifacts_dir)

    # ------------------------------------------------------------------
    # Dataset construction (doc 13.4 canonical rows)
    # ------------------------------------------------------------------

    def build_dataset(self) -> pd.DataFrame:
        """
        Load labeled canonical rows into a feature frame.

        Leakage guard (doc 13.3): rows labelled from SMAP are excluded because
        smap_sm is used as an input feature in this same run -- using them
        would let the model learn to reproduce SMAP instead of predicting
        independently.
        """
        rows = (
            self.db.query(PlotFeatures, Plot)
            .join(Plot, Plot.plot_id == PlotFeatures.plot_id)
            .filter(
                PlotFeatures.soil_moisture_label.isnot(None),
                PlotFeatures.label_source.isnot(None),
                PlotFeatures.label_source != "smap",  # leakage guard
            )
            .all()
        )

        records: list[dict[str, Any]] = []
        for pf, plot in rows:
            record: dict[str, Any] = {
                "plot_id": pf.plot_id,
                "obs_date": pf.obs_date,
                "label": float(pf.soil_moisture_label),
                "label_source": pf.label_source,
            }
            for col in FEATURE_COLUMNS:
                if col == "days_since_sowing":
                    record[col] = (pf.obs_date - plot.sowing_date).days
                else:
                    value = getattr(pf, col)
                    record[col] = float(value) if value is not None else np.nan
            records.append(record)

        frame = pd.DataFrame.from_records(records)
        if not frame.empty:
            frame = frame.sort_values(["obs_date", "plot_id"]).reset_index(drop=True)
        return frame

    # ------------------------------------------------------------------
    # Temporal split (doc 13.4 -- never a random row-level split)
    # ------------------------------------------------------------------

    @staticmethod
    def temporal_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split by observation date: the most recent TEST_FRACTION of distinct
        dates becomes the held-out test set; everything earlier is training.
        Deterministic -- no shuffling, no randomness.
        """
        distinct_dates = sorted(frame["obs_date"].unique())
        if len(distinct_dates) < MIN_DISTINCT_DATES:
            raise ValueError(
                f"Need at least {MIN_DISTINCT_DATES} distinct observation dates for a "
                f"temporal split; found {len(distinct_dates)}"
            )
        cutoff_idx = max(1, int(len(distinct_dates) * (1 - TEST_FRACTION)))
        cutoff_date = distinct_dates[cutoff_idx - 1]
        train = cast(pd.DataFrame, frame[frame["obs_date"] <= cutoff_date].copy())
        test = cast(pd.DataFrame, frame[frame["obs_date"] > cutoff_date].copy())
        if train.empty or test.empty:
            raise ValueError("Temporal split produced an empty train or test set")
        return train, test

    # ------------------------------------------------------------------
    # Training + evaluation (doc 13.5)
    # ------------------------------------------------------------------

    def run_retraining(
        self,
        agro_zone: str = "yavatmal-mh",
        fpr_threshold: float = DEFAULT_FPR_THRESHOLD,
    ) -> TrainingResult:
        """One full retrain cycle: dataset -> split -> fit -> evaluate -> gate -> persist."""
        frame = self.build_dataset()
        if len(frame) < MIN_LABELED_ROWS:
            return TrainingResult(
                status="skipped",
                labeled_rows=len(frame),
                message=(
                    f"Insufficient labeled rows ({len(frame)} < {MIN_LABELED_ROWS}); "
                    "run ingestion + water-balance weak-label job first"
                ),
            )

        try:
            train, test = self.temporal_split(frame)
        except ValueError as exc:
            return TrainingResult(status="skipped", labeled_rows=len(frame), message=str(exc))

        X_train = cast(pd.DataFrame, train[FEATURE_COLUMNS])
        y_train = train["label"].to_numpy()
        X_test = cast(pd.DataFrame, test[FEATURE_COLUMNS])
        y_test = test["label"].to_numpy()

        model = XGBRegressor(**XGB_PARAMS)
        model.fit(X_train, y_train, verbose=False)

        y_pred = np.clip(model.predict(X_test), 0.0, 1.0)

        # Stage-1 regression metrics (fraction scale == m3/m3, doc 13.6)
        rmse = float(np.sqrt(np.mean((y_test - y_pred) ** 2)))
        mae = float(np.mean(np.abs(y_test - y_pred)))
        ss_res = float(np.sum((y_test - y_pred) ** 2))
        ss_tot = float(np.sum((y_test - y_test.mean()) ** 2))
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        # Stage-2 classification metrics via the rule thresholds (doc 13.6)
        rainfall_test = test["rainfall_7d"].to_numpy()
        y_true_class = np.array(
            [_advisory_class_for_moisture(t, r) for t, r in zip(y_test, rainfall_test)]
        )
        y_pred_class = np.array(
            [_advisory_class_for_moisture(p, r) for p, r in zip(y_pred, rainfall_test)]
        )
        tp = int(np.sum((y_pred_class == "irrigate_now") & (y_true_class == "irrigate_now")))
        fp = int(np.sum((y_pred_class == "irrigate_now") & (y_true_class != "irrigate_now")))
        tn = int(np.sum((y_pred_class != "irrigate_now") & (y_true_class != "irrigate_now")))
        fn = int(np.sum((y_pred_class != "irrigate_now") & (y_true_class == "irrigate_now")))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        )
        total = tp + fp + tn + fn
        accuracy = (tp + tn) / total if total > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        model_version = f"xgb-{utc_now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:4]}"
        shap_importance = self._shap_importance(model, X_test)

        run = self._eval_service.log_evaluation(
            model_version,
            trained_at=utc_now(),
            agro_zone=agro_zone,
            rmse=rmse,
            mae=mae,
            r2=r2,
            accuracy=accuracy,
            precision_score=precision,
            recall=recall,
            f1=f1,
            tp=tp,
            fp=fp,
            tn=tn,
            fn=fn,
            shap_feature_importance=shap_importance,
            fpr_threshold=fpr_threshold,
            notes=(
                f"XGBoost Stage-1 retrain: {len(train)} train / {len(test)} test rows; "
                f"temporal split {train['obs_date'].min()}..{train['obs_date'].max()} -> "
                f"{test['obs_date'].min()}..{test['obs_date'].max()}"
            ),
        )

        artifact_path = self._persist_artifact(
            model,
            model_version=model_version,
            run=run,
            train=train,
            test=test,
            rmse=rmse,
            mae=mae,
            r2=r2,
        )

        result = TrainingResult(
            status="trained" if run.passed_fpr_threshold else "blocked",
            model_version=model_version,
            labeled_rows=len(frame),
            train_rows=len(train),
            test_rows=len(test),
            train_start=str(train["obs_date"].min()),
            train_end=str(train["obs_date"].max()),
            test_start=str(test["obs_date"].min()),
            test_end=str(test["obs_date"].max()),
            rmse=rmse,
            mae=mae,
            r2=r2,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1=f1,
            fpr=fpr,
            passed_fpr_threshold=bool(run.passed_fpr_threshold),
            shap_feature_importance=shap_importance,
            artifact_path=str(artifact_path) if artifact_path else None,
        )
        if result.status == "blocked":
            result.message = (
                f"FPR {fpr:.4f} exceeds threshold {fpr_threshold:.4f}; promotion BLOCKED "
                "(doc 13.5) -- model artifact saved for audit but not served"
            )
        else:
            result.message = "Model trained, passed FPR gate, and promoted for serving"
        return result

    # ------------------------------------------------------------------
    # SHAP feature importance (doc 12.4.4)
    # ------------------------------------------------------------------

    @staticmethod
    def _shap_importance(model: XGBRegressor, X_test: pd.DataFrame) -> dict[str, float]:
        try:
            import shap  # local import: optional dependency at runtime

            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_test)
            mean_abs = np.abs(shap_values).mean(axis=0)
            importance = {
                col: round(float(val), 6) for col, val in zip(X_test.columns, mean_abs)
            }
            # Keep the top contributors for the evaluation-run snapshot
            return dict(sorted(importance.items(), key=lambda kv: kv[1], reverse=True)[:10])
        except Exception as exc:  # pragma: no cover - SHAP is best-effort
            logger.warning("SHAP importance computation failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Artifact persistence + serving lookup
    # ------------------------------------------------------------------

    def _persist_artifact(
        self,
        model: XGBRegressor,
        *,
        model_version: str,
        run: ModelEvaluationRun,
        train: pd.DataFrame,
        test: pd.DataFrame,
        rmse: float,
        mae: float,
        r2: float,
    ) -> Path | None:
        """Save the trained model + metadata. Served only if the FPR gate passed."""
        try:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            path = self.artifacts_dir / f"{model_version}.joblib"
            payload = {
                "model": model,
                "model_version": model_version,
                "feature_columns": FEATURE_COLUMNS,
                "trained_at": utc_now().isoformat(),
                "run_id": run.run_id,
                "passed_fpr_threshold": bool(run.passed_fpr_threshold),
                "metrics": {"rmse": rmse, "mae": mae, "r2": r2},
                "train_window": [str(train["obs_date"].min()), str(train["obs_date"].max())],
                "test_window": [str(test["obs_date"].min()), str(test["obs_date"].max())],
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
            }
            joblib.dump(payload, path)
            return path
        except Exception as exc:  # pragma: no cover - persistence is best-effort
            logger.error("Failed to persist model artifact: %s", exc)
            return None

    def load_promoted_model(self) -> Optional[dict[str, Any]]:
        """
        Return the artifact for the latest FPR-passing model version, or None.

        Serving contract (doc 13.5): a model version is only served when its
        latest evaluation run has passed_fpr_threshold=True AND the artifact
        file exists on disk.
        """
        latest_pass = (
            self.db.query(ModelEvaluationRun)
            .filter(ModelEvaluationRun.passed_fpr_threshold.is_(True))
            .order_by(ModelEvaluationRun.trained_at.desc())
            .first()
        )
        if latest_pass is None:
            return None
        path = self.artifacts_dir / f"{latest_pass.model_version}.joblib"
        if not path.exists():
            logger.warning(
                "Evaluation run for %s passed the FPR gate but artifact %s is missing",
                latest_pass.model_version,
                path,
            )
            return None
        try:
            artifact = joblib.load(path)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to load model artifact %s: %s", path, exc)
            return None
        if not artifact.get("passed_fpr_threshold", False):
            return None
        return artifact