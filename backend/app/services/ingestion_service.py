"""
Ingestion service -- sec 12.3

Implements:
  1. Date-snapping logic per source before writing plot_features rows (sec 12.3.1 / 11.4)
  2. SMAP separation: smap_sm feature column only, NEVER soil_moisture_label (sec 12.3.2)
  3. Cloud/quality masking + outlier rejection as a discrete pipeline step (sec 12.3.3)
  4. Water-balance weak-label generator as a scheduled job (sec 12.3.4)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Plot, SatelliteData
from app.core.config import get_settings
from app.services.ingestion_providers import IngestionProvider, get_ingestion_provider
from app.services.ml_prediction_service import MLPredictionService, PredictionResult
from app.services.plot_features_service import PlotFeaturesService
from app.services.water_balance_model import WaterBalanceBucketModel
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# Outlier thresholds for quality rejection (sec 12.3.3)
NDVI_RANGE = (-0.2, 1.0)
SAR_VV_RANGE = (-30.0, 5.0)  # dB
SAR_VH_RANGE = (-35.0, 0.0)  # dB
CLOUD_COVERAGE_MAX = 30.0    # % -- reject Sentinel-2 readings above this


@dataclass
class IngestionResult:
    plot_id: str
    source: str
    status: str
    value: Optional[float] = None


class IngestionService:
    """Service for ingesting satellite data and building canonical plot_features rows."""

    def __init__(self, db: Session, provider: IngestionProvider | None = None):
        self.db = db
        self._plot_features_service = PlotFeaturesService(db)
        self._rejected_count: int = 0  # monitoring counter reset per fetch cycle
        self.provider = provider or get_ingestion_provider(get_settings().ingestion_provider)
        self.last_prediction_result: PredictionResult | None = None

    def fetch_plot_cycle(self, plot_id: str, use_mock: bool | None = None) -> list[SatelliteData]:
        """
        Fetch satellite data for a plot cycle (most recent observation period).

        After persisting raw SatelliteData records, triggers a plot_features
        upsert for today using the date-snapping join logic (sec 11.4 / 12.3.1).
        """
        plot = self.db.query(Plot).filter(Plot.plot_id == plot_id).first()
        if not plot:
            return []

        self._rejected_count = 0  # reset monitoring counter
        self.last_prediction_result = None

        if use_mock is not None:
            # Compatibility for existing callers; explicit injected providers are preferred.
            self.provider = get_ingestion_provider("mock" if use_mock else "live")
        try:
            raw_data = self.provider.fetch_cycle(plot)
        except Exception as exc:
            logger.exception("Ingestion provider %s failed for plot=%s", self.provider.name, plot_id)
            self._record_cycle_failure(plot, str(exc))
            return []

        # Cloud/quality masking + outlier rejection (sec 12.3.3)
        accepted = self._apply_quality_filter(raw_data)
        self._persist_raw_data(raw_data)
        self._record_cycle_success(plot)

        if self._rejected_count > 0:
            logger.warning(
                "Ingestion: plot=%s rejected %d observations (cloud/outlier) out of %d total",
                plot_id, self._rejected_count, len(raw_data),
            )

        # Build canonical plot_features row for today via date-snapping (sec 11.4)
        try:
            today = utc_now().date()
            self._plot_features_service.build_and_upsert(plot_id, today)
        except Exception as exc:
            logger.error("Failed to build plot_features for plot=%s date=%s: %s", plot_id, date.today(), exc)
            return accepted

        self._trigger_prediction(plot_id)

        return accepted

    def _trigger_prediction(self, plot_id: str) -> None:
        """
        Auto-chain a fresh ML prediction after new data lands (live-update wiring).

        Non-fatal by design: insufficient data or a transient model-API failure
        must not fail the ingestion call itself -- ingestion has already
        succeeded and the caller/UI is waiting on that response.
        """
        try:
            service = MLPredictionService(self.db)
            result = service.predict_irrigation_stress(plot_id)
            service.save_prediction(result)
            self.last_prediction_result = result
        except ValueError as exc:
            logger.info("No prediction generated for plot=%s after ingestion: %s", plot_id, exc)
        except Exception as exc:
            logger.warning("Auto-prediction failed for plot=%s after ingestion: %s", plot_id, exc)

    def _persist_raw_data(self, records: list[SatelliteData]) -> None:
        for data in records:
            existing = self.db.query(SatelliteData).filter(
                SatelliteData.satellite_id == data.satellite_id
            ).first()
            if not existing:
                self.db.add(data)

        self.db.commit()

    def _record_cycle_success(self, plot: Plot) -> None:
        plot.ingestion_failure_count = 0
        plot.data_status = "available"
        plot.last_ingestion_at = utc_now()
        self.db.commit()

    def _record_cycle_failure(self, plot: Plot, reason: str) -> None:
        threshold = get_settings().data_unavailable_after_failures
        plot.ingestion_failure_count = (plot.ingestion_failure_count or 0) + 1
        plot.last_ingestion_at = utc_now()
        if plot.ingestion_failure_count >= threshold:
            plot.data_status = "data_unavailable"
        logger.warning("Ingestion failed for plot=%s: %s", plot.plot_id, reason)
        self.db.commit()

    def _apply_quality_filter(self, records: list[SatelliteData]) -> list[SatelliteData]:
        """
        Discrete cloud/quality masking + outlier rejection step (sec 12.3.3).
        Sets ingestion_status='rejected' and cloud_masked=True on rejected records.
        Logs rejected-observation counts for monitoring.
        """
        accepted = []
        for rec in records:
            reject_reason = self._check_quality(rec)
            if reject_reason:
                rec.ingestion_status = "rejected"
                if rec.data_source == "sentinel2":
                    rec.cloud_masked = True
                self._rejected_count += 1
                logger.debug(
                    "Rejected observation: satellite_id=%s reason=%s", rec.satellite_id, reject_reason
                )
            else:
                rec.ingestion_status = "success"
                accepted.append(rec)
        self.db.commit()
        return accepted

    def _check_quality(self, rec: SatelliteData) -> Optional[str]:
        """Return a rejection reason string, or None if the record is acceptable."""
        # Cloud coverage check for Sentinel-2
        if rec.data_source == "sentinel2":
            if rec.cloud_coverage is not None and rec.cloud_coverage > CLOUD_COVERAGE_MAX:
                return f"cloud_coverage={rec.cloud_coverage}% > {CLOUD_COVERAGE_MAX}%"

        # Outlier range checks
        if rec.data_type == "ndvi" and rec.value:
            try:
                v = float(rec.value)
                if not (NDVI_RANGE[0] <= v <= NDVI_RANGE[1]):
                    return f"ndvi={v} out of range {NDVI_RANGE}"
            except ValueError:
                return "ndvi_parse_error"

        if rec.data_type == "sar" and rec.value:
            vv, vh = None, None
            for part in rec.value.split(","):
                if part.startswith("VV:"):
                    try:
                        vv = float(part.split(":", 1)[1])
                    except ValueError:
                        pass
                elif part.startswith("VH:"):
                    try:
                        vh = float(part.split(":", 1)[1])
                    except ValueError:
                        pass
            if vv is not None and not (SAR_VV_RANGE[0] <= vv <= SAR_VV_RANGE[1]):
                return f"sar_vv={vv} out of range {SAR_VV_RANGE}"
            if vh is not None and not (SAR_VH_RANGE[0] <= vh <= SAR_VH_RANGE[1]):
                return f"sar_vh={vh} out of range {SAR_VH_RANGE}"

        return None

    def get_latest_satellite_data(
        self, plot_id: str, data_source: str | None = None, data_type: str | None = None
    ) -> list[SatelliteData]:
        """Query latest satellite data for a plot."""
        query = self.db.query(SatelliteData).filter(SatelliteData.plot_id == plot_id)

        if data_source:
            query = query.filter(SatelliteData.data_source == data_source)
        if data_type:
            query = query.filter(SatelliteData.data_type == data_type)

        return query.order_by(SatelliteData.observation_date.desc()).all()

    def handle_cloud_mask(self, plot_id: str) -> None:
        """Placeholder for cloud-mask fallback logic."""
        return None


class WaterBalanceLabelJob:
    """
    sec 12.3.4 -- Water-balance weak-label generator as a scheduled job.

    Writes soil_moisture_label with label_source='water_balance' for all
    PlotFeatures rows that don't yet have a label, running automatically
    per plot rather than as a one-off script.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._wb_model = WaterBalanceBucketModel(db)
        self._features_service = PlotFeaturesService(db)

    def run_for_plot(self, plot_id: str, lookback_days: int = 30) -> int:
        """
        Assign water-balance labels to unlabeled plot_features rows for the
        given plot, for the past `lookback_days` days.

        Returns the number of rows labelled.
        """
        from app.models import PlotFeatures  # local import to avoid circular at module level

        cutoff = utc_now().date() - timedelta(days=lookback_days)
        unlabeled = (
            self.db.query(PlotFeatures)
            .filter(
                PlotFeatures.plot_id == plot_id,
                PlotFeatures.soil_moisture_label == None,  # noqa: E711
                PlotFeatures.obs_date >= cutoff,
            )
            .all()
        )

        labelled = 0
        for row in unlabeled:
            try:
                wb = self._wb_model.estimate_stress(plot_id, observation_date=row.obs_date)
                # Normalize soil_moisture_pct to [0, 1] fraction for the label
                label_value = round(wb.soil_moisture_pct / 100.0, 4)
                self._features_service.write_label(
                    plot_id=plot_id,
                    obs_date=row.obs_date,
                    soil_moisture_label=label_value,
                    label_source="water_balance",
                )
                labelled += 1
            except Exception as exc:
                logger.warning("Water-balance label failed: plot=%s date=%s: %s", plot_id, row.obs_date, exc)

        logger.info("WaterBalanceLabelJob: plot=%s labelled=%d rows", plot_id, labelled)
        return labelled
