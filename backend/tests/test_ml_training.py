"""Tests for the XGBoost Stage-1 training pipeline (doc 13 model flowchart)."""

from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.models import Farmer, ModelEvaluationRun, Plot, PlotFeatures
from app.services.ml_prediction_service import SoilMoistureModel
from app.services.ml_training_service import (
    FEATURE_COLUMNS,
    MIN_LABELED_ROWS,
    MLTrainingService,
)


def _make_farmer_plot(db: Session, idx: int) -> tuple[Farmer, Plot]:
    farmer = Farmer(
        farmer_id=f"train-farmer-{idx}",
        phone_number=f"+91980000{idx:04d}",
        name=f"Train Farmer {idx}",
        preferred_language="en",
        state="Maharashtra",
        district="Yavatmal",
        consent_given_at=__import__("app.utils.time", fromlist=["utc_now"]).utc_now(),
        registration_channel="web",
        status="active",
    )
    db.add(farmer)
    plot = Plot(
        plot_id=f"train-plot-{idx}",
        farmer_id=farmer.farmer_id,
        plot_nickname=f"Plot {idx}",
        crop_type="cotton",
        sowing_date=date(2026, 6, 1),
        status="active",
    )
    db.add(plot)
    return farmer, plot


def _seed_labeled_rows(db: Session, n_plots: int, n_days: int) -> None:
    """Create deterministic synthetic labeled feature rows for training."""
    rng = np.random.default_rng(42)
    base_date = date(2026, 7, 1)
    for i in range(n_plots):
        _, plot = _make_farmer_plot(db, i)
        for d in range(n_days):
            obs_date = base_date + timedelta(days=d)
            # Synthetic moisture signal correlated with rainfall/NDVI so the
            # model has learnable structure.
            rainfall_7d = float(rng.uniform(0, 40))
            ndvi = float(rng.uniform(0.2, 0.7))
            label = round(
                min(1.0, max(0.0, 0.25 + ndvi * 0.5 + rainfall_7d / 200.0 + rng.normal(0, 0.03))),
                4,
            )
            db.add(
                PlotFeatures(
                    plot_id=plot.plot_id,
                    obs_date=obs_date,
                    vv_db=float(rng.uniform(-20, -8)),
                    vh_db=float(rng.uniform(-28, -14)),
                    delta_vv_7d=float(rng.normal(0, 1.5)),
                    delta_vh_7d=float(rng.normal(0, 1.5)),
                    ndvi=ndvi,
                    ndwi=float(rng.uniform(-0.3, 0.3)),
                    evi=float(rng.uniform(0.1, 0.8)),
                    savi=float(rng.uniform(0.1, 0.7)),
                    delta_ndvi_7d=float(rng.normal(0, 0.03)),
                    delta_ndvi_14d=float(rng.normal(0, 0.05)),
                    rainfall_1d=float(rng.uniform(0, 15)),
                    rainfall_3d=rainfall_7d * 0.4,
                    rainfall_7d=rainfall_7d,
                    rainfall_14d=rainfall_7d * 1.6,
                    rain_forecast_48h=float(rng.uniform(0, 10)),
                    et0=float(rng.uniform(3, 7)),
                    kc=1.05,
                    etc=float(rng.uniform(4, 8)),
                    lst=float(rng.uniform(25, 38)),
                    smap_sm=float(rng.uniform(0.1, 0.5)),
                    crop_stage="vegetative",
                    label_source="water_balance",
                    soil_moisture_label=label,
                )
            )
    db.commit()


def test_temporal_split_is_deterministic_and_ordered(db_session: Session) -> None:
    """The split must be temporal (recent dates held out), never random (doc 13.4)."""
    _seed_labeled_rows(db_session, n_plots=8, n_days=10)
    service = MLTrainingService(db_session, artifacts_dir="/tmp/ml_artifacts_test")
    frame = service.build_dataset()
    assert not frame.empty
    train, test = service.temporal_split(frame)
    assert not train.empty and not test.empty
    assert train["obs_date"].max() <= test["obs_date"].min()
    # Deterministic: same input -> same split
    train2, test2 = service.temporal_split(frame)
    assert train["obs_date"].min() == train2["obs_date"].min()
    assert test["obs_date"].min() == test2["obs_date"].min()
    # Overlap guard
    assert set(train.index).isdisjoint(set(test.index))


def test_retraining_trains_logs_evaluation_and_passes_gate(db_session: Session) -> None:
    """A full retrain cycle produces metrics, an evaluation run, and an artifact."""
    _seed_labeled_rows(db_session, n_plots=10, n_days=14)
    service = MLTrainingService(db_session, artifacts_dir="/tmp/ml_artifacts_test")
    result = service.run_retraining(agro_zone="test-zone")

    assert result.status == "trained", result.message
    assert result.model_version is not None
    assert result.train_rows + result.test_rows >= MIN_LABELED_ROWS
    assert result.rmse is not None and result.rmse >= 0
    assert result.fpr is not None and result.passed_fpr_threshold is True

    # Evaluation run persisted with the FPR gate verdict
    run = (
        db_session.query(ModelEvaluationRun)
        .filter(ModelEvaluationRun.model_version == result.model_version)
        .first()
    )
    assert run is not None
    assert run.passed_fpr_threshold is True
    assert run.rmse is not None
    # SHAP importance snapshot present (doc 12.4.4)
    assert run.shap_feature_importance

    # Artifact persisted and loadable via the promotion lookup
    artifact = service.load_promoted_model()
    assert artifact is not None
    assert artifact["model_version"] == result.model_version
    assert artifact["feature_columns"] == FEATURE_COLUMNS


def test_retraining_skips_when_insufficient_data(db_session: Session) -> None:
    """Below MIN_LABELED_ROWS the cycle is skipped, not failed (fail-safe principle)."""
    _seed_labeled_rows(db_session, n_plots=2, n_days=3)  # 6 rows << minimum
    service = MLTrainingService(db_session, artifacts_dir="/tmp/ml_artifacts_test")
    result = service.run_retraining()
    assert result.status == "skipped"
    assert "Insufficient labeled rows" in result.message


def test_stage1_serves_promoted_model_over_fallback(db_session: Session) -> None:
    """After a successful retrain, Stage 1 serves the XGBoost model version."""
    _seed_labeled_rows(db_session, n_plots=10, n_days=14)
    service = MLTrainingService(db_session, artifacts_dir="/tmp/ml_artifacts_test")
    result = service.run_retraining()
    assert result.status == "trained"

    stage1 = SoilMoistureModel(db_session, artifacts_dir="/tmp/ml_artifacts_test")
    soil = stage1.predict("train-plot-0")
    assert soil.model_version == result.model_version
    assert 0.0 <= soil.soil_moisture_pct <= 100.0
    assert 0.0 <= soil.cwsi <= 1.0
    assert soil.feature_snapshot["model_type"] == "xgboost-stage1"