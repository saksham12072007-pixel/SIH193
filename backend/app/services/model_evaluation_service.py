"""
Model Evaluation Service -- sec 12.1 / 12.4 / 13.5

Provides:
  - FPR-constrained model promotion gate (sec 13.5 model-selection rule)
  - Temporal / spatial train-test split enforcement (sec 13.4)
  - Logging evaluation metrics to model_evaluation_runs table
  - SHAP feature importance snapshots (sec 12.4.4)

The promotion gate is enforced programmatically here so it is NEVER left as a
manual/notebook step in production (sec 12.2 retraining job requirement).

FPR is computed as:  FPR = FP / (FP + TN)
A false positive = unnecessary irrigation advisory (water/cost waste).
A false negative = missed crop stress (potential crop damage).
This asymmetry means Recall on 'Irrigate Now' is weighted above raw accuracy,
and FPR is a hard ceiling rather than a metric to be minimised to zero
(zero FPR usually means the model is too conservative -- high FN instead).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Advisory, AdvisoryFeedback, ModelEvaluationRun, Plot, PlotFeatures
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# Default FPR ceiling (can be overridden per deployment / agro-zone)
DEFAULT_FPR_THRESHOLD = 0.15  # 15% -- i.e. no more than 15 unnecessary advisories per 100 non-stress obs


class ModelEvaluationService:
    """Store, retrieve, and gate model versions via FPR-constrained promotion."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Metric logging
    # ------------------------------------------------------------------

    def log_evaluation(
        self,
        model_version: str,
        *,
        trained_at: Optional[datetime] = None,
        agro_zone: Optional[str] = None,
        # Stage 1 (regression)
        rmse: Optional[float] = None,
        mae: Optional[float] = None,
        r2: Optional[float] = None,
        # Stage 2 (classification)
        accuracy: Optional[float] = None,
        precision_score: Optional[float] = None,
        recall: Optional[float] = None,
        f1: Optional[float] = None,
        tp: Optional[int] = None,
        fp: Optional[int] = None,
        tn: Optional[int] = None,
        fn: Optional[int] = None,
        # SHAP
        shap_feature_importance: Optional[dict] = None,
        fpr_threshold: float = DEFAULT_FPR_THRESHOLD,
        notes: Optional[str] = None,
    ) -> ModelEvaluationRun:
        """
        Compute FPR from confusion-matrix counts (if provided), evaluate the
        FPR promotion gate, and persist the run to model_evaluation_runs.
        """
        fpr: Optional[float] = None
        if tp is not None and fp is not None and tn is not None and fn is not None:
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            if f1 is None and precision_score is not None and recall is not None:
                denom = precision_score + recall
                f1 = 2 * precision_score * recall / denom if denom > 0 else 0.0
            if precision_score is None:
                precision_score = tp / (tp + fp) if (tp + fp) > 0 else None
            if recall is None:
                recall = tp / (tp + fn) if (tp + fn) > 0 else None
            if accuracy is None:
                total = tp + fp + tn + fn
                accuracy = (tp + tn) / total if total > 0 else None

        passed = None
        if fpr is not None:
            passed = fpr <= fpr_threshold

        run = ModelEvaluationRun(
            run_id=str(uuid.uuid4()),
            model_version=model_version,
            trained_at=trained_at or utc_now(),
            agro_zone=agro_zone,
            rmse=rmse,
            mae=mae,
            r2=r2,
            accuracy=accuracy,
            precision_score=precision_score,
            recall=recall,
            f1=f1,
            fpr=fpr,
            passed_fpr_threshold=passed,
            shap_feature_importance=shap_feature_importance,
            notes=notes,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

        if passed is False:
            logger.warning(
                "Model version %s FAILED FPR gate: FPR=%.4f > threshold=%.4f. "
                "Promotion to production is BLOCKED.",
                model_version, fpr, fpr_threshold,
            )
        elif passed is True:
            logger.info(
                "Model version %s PASSED FPR gate: FPR=%.4f <= threshold=%.4f.",
                model_version, fpr, fpr_threshold,
            )

        return run

    # ------------------------------------------------------------------
    # Promotion gate
    # ------------------------------------------------------------------

    def is_promotable(self, model_version: str, fpr_threshold: float = DEFAULT_FPR_THRESHOLD) -> bool:
        """
        Return True only if the latest evaluation run for this model version
        has passed_fpr_threshold=True.  Raises ValueError if no evaluation
        run exists (cannot promote an un-evaluated model).
        """
        latest = (
            self.db.query(ModelEvaluationRun)
            .filter(ModelEvaluationRun.model_version == model_version)
            .order_by(ModelEvaluationRun.created_at.desc())
            .first()
        )
        if latest is None:
            raise ValueError(
                f"No evaluation run found for model version {model_version!r}. "
                "Run log_evaluation() before attempting promotion."
            )
        if latest.passed_fpr_threshold is None:
            raise ValueError(
                f"Evaluation run {latest.run_id} for model {model_version!r} has no FPR result. "
                "Provide confusion-matrix counts (tp/fp/tn/fn) to log_evaluation()."
            )
        return bool(latest.passed_fpr_threshold)

    # ------------------------------------------------------------------
    # Trend / monitoring queries
    # ------------------------------------------------------------------

    def get_runs_for_version(self, model_version: str) -> list[ModelEvaluationRun]:
        """Return all evaluation runs for a given model version, newest first."""
        return (
            self.db.query(ModelEvaluationRun)
            .filter(ModelEvaluationRun.model_version == model_version)
            .order_by(ModelEvaluationRun.created_at.desc())
            .all()
        )

    def get_latest_per_version(self, agro_zone: Optional[str] = None) -> list[ModelEvaluationRun]:
        """Return the latest run per model version (optionally filtered by agro_zone)."""
        query = self.db.query(ModelEvaluationRun)
        if agro_zone:
            query = query.filter(ModelEvaluationRun.agro_zone == agro_zone)
        # Group-by-latest using Python since SQLite doesn't support DISTINCT ON
        all_runs = query.order_by(ModelEvaluationRun.created_at.desc()).all()
        seen: set[str] = set()
        latest: list[ModelEvaluationRun] = []
        for run in all_runs:
            key = f"{run.model_version}:{run.agro_zone or ''}"
            if key not in seen:
                seen.add(key)
                latest.append(run)
        return latest

    def get_false_positive_drilldown(
        self, model_version: str, agro_zone: Optional[str] = None
    ) -> list[dict]:
        """
        Return evaluation runs where FPR exceeded the threshold -- useful for the
        KVK/admin 'false-positive drilldown' view (sec 12.5.3).
        """
        query = (
            self.db.query(AdvisoryFeedback, Plot)
            .join(Advisory, Advisory.advisory_id == AdvisoryFeedback.advisory_id)
            .join(Plot, Plot.plot_id == Advisory.plot_id)
            .filter(
                AdvisoryFeedback.model_version == model_version,
                AdvisoryFeedback.predicted_class == "irrigate_now",
                AdvisoryFeedback.reply_code == "not_needed",
            )
        )
        # A true agro-zone column is introduced with live GIS data; district is
        # the current safe pilot scope.
        if agro_zone:
            query = query.filter(Plot.village_name == agro_zone)
        records = query.order_by(AdvisoryFeedback.received_at.desc()).all()
        return [
            {
                "feedback_id": feedback.feedback_id,
                "plot_id": plot.plot_id,
                "observation_date": feedback.received_at.isoformat(),
                "model_version": feedback.model_version,
                "predicted_confidence": float(feedback.predicted_confidence) if feedback.predicted_confidence is not None else None,
                "outcome": feedback.reply_code,
            }
            for feedback, plot in records
        ]


# ------------------------------------------------------------------
# Train / Test Split Enforcement (sec 12.4.3 / 13.4)
# ------------------------------------------------------------------

def temporal_train_test_split(
    rows: list[Any],
    date_attr: str = "obs_date",
    train_end: Optional[date] = None,
    val_end: Optional[date] = None,
) -> tuple[list[Any], list[Any], list[Any]]:
    """
    Enforces a temporal holdout split -- NEVER random row-level split.

    Split strategy (sec 13.4 example: Jan-Jun = TRAIN, Jul = VAL, Aug = TEST):
      train_end: last date (inclusive) of the training set
      val_end:   last date (inclusive) of the validation set
                 (everything after = test set)

    If val_end is None, returns (train, [], test).

    Args:
        rows:       list of objects with a date field (PlotFeatures or dicts)
        date_attr:  name of the date attribute on each row
        train_end:  cutoff date for training set
        val_end:    cutoff date for validation set

    Returns:
        (train, val, test) -- never overlapping, never randomly shuffled.
    """
    if train_end is None:
        raise ValueError("train_end must be provided for temporal splitting")

    train, val, test = [], [], []
    for row in rows:
        d = getattr(row, date_attr, None) or row.get(date_attr) if isinstance(row, dict) else getattr(row, date_attr)
        if d is None:
            continue
        if isinstance(d, datetime):
            d = d.date()
        if d <= train_end:
            train.append(row)
        elif val_end is not None and d <= val_end:
            val.append(row)
        else:
            test.append(row)

    return train, val, test


def spatial_train_test_split(
    rows: list[Any],
    test_plot_ids: set[str],
    plot_id_attr: str = "plot_id",
) -> tuple[list[Any], list[Any]]:
    """
    Enforces a spatial holdout split -- NEVER random row-level split.

    Held-out test plots are completely unseen during training/validation.

    Args:
        rows:          list of objects with a plot_id field
        test_plot_ids: set of plot_ids reserved for the test set
        plot_id_attr:  attribute name for plot_id on each row

    Returns:
        (train, test)
    """
    train, test = [], []
    for row in rows:
        pid = getattr(row, plot_id_attr) if not isinstance(row, dict) else row.get(plot_id_attr)
        (test if pid in test_plot_ids else train).append(row)
    return train, test
