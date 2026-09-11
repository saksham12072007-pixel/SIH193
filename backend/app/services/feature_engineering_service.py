"""Feature engineering for satellite and weather data."""

from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models import Plot, PlotFeatures, SatelliteData
from app.utils.time import utc_now


class FeatureVector(NamedTuple):
    """Engineered features for ML model."""

    plot_id: str
    observation_date: datetime
    ndvi: float | None
    ndvi_trend: float | None
    sar_vv: float | None
    sar_vh: float | None
    rainfall_mm: float | None
    temperature_max: float | None
    temperature_min: float | None
    days_since_sowing: int | None


class FeatureEngineeringService:
    """Extract and compute engineered features from raw satellite/weather data."""

    def __init__(self, db: Session):
        self.db = db

    def get_features_for_plot(self, plot_id: str, observation_date: datetime | None = None) -> FeatureVector | None:
        """Extract engineered features for a plot."""
        if observation_date is None:
            observation_date = utc_now()

        plot = self.db.query(Plot).filter(Plot.plot_id == plot_id).first()
        if not plot:
            return None

        # The canonical feature store is the sole serving/training source.  Raw
        # readings remain available only for auditing and feature construction.
        canonical = (
            self.db.query(PlotFeatures)
            .filter(PlotFeatures.plot_id == plot_id, PlotFeatures.obs_date <= observation_date.date())
            .order_by(PlotFeatures.obs_date.desc())
            .first()
        )
        if canonical:
            days_since_sowing = None
            if plot.sowing_date:
                days_since_sowing = (canonical.obs_date - plot.sowing_date).days
            return FeatureVector(
                plot_id=plot_id,
                observation_date=datetime.combine(canonical.obs_date, datetime.min.time(), tzinfo=timezone.utc),
                ndvi=float(canonical.ndvi) if canonical.ndvi is not None else None,
                ndvi_trend=float(canonical.delta_ndvi_7d) if canonical.delta_ndvi_7d is not None else None,
                sar_vv=float(canonical.vv_db) if canonical.vv_db is not None else None,
                sar_vh=float(canonical.vh_db) if canonical.vh_db is not None else None,
                rainfall_mm=float(canonical.rainfall_7d) if canonical.rainfall_7d is not None else None,
                temperature_max=None,
                temperature_min=None,
                days_since_sowing=days_since_sowing,
            )

        # Get latest NDVI reading
        ndvi_data = (
            self.db.query(SatelliteData)
            .filter(
                SatelliteData.plot_id == plot_id,
                SatelliteData.data_source == "sentinel2",
                SatelliteData.data_type == "ndvi",
                SatelliteData.observation_date <= observation_date,
            )
            .order_by(SatelliteData.observation_date.desc())
            .all()
        )

        ndvi = None
        ndvi_trend = None
        if ndvi_data:
            first_ndvi = ndvi_data[0].value
            if first_ndvi is not None:
                ndvi = float(first_ndvi)
                # Compute 2-cycle trend if available
                if len(ndvi_data) >= 2 and ndvi_data[1].value is not None:
                    prev_ndvi = float(ndvi_data[1].value)
                    ndvi_trend = ndvi - prev_ndvi

        # Get latest SAR reading
        sar_data = (
            self.db.query(SatelliteData)
            .filter(
                SatelliteData.plot_id == plot_id,
                SatelliteData.data_source == "sentinel1",
                SatelliteData.data_type == "sar",
                SatelliteData.observation_date <= observation_date,
            )
            .order_by(SatelliteData.observation_date.desc())
            .first()
        )

        sar_vv = None
        sar_vh = None
        if sar_data and sar_data.value:
            parts = sar_data.value.split(",")
            for part in parts:
                if part.startswith("VV:"):
                    sar_vv = float(part.split(":")[1])
                elif part.startswith("VH:"):
                    sar_vh = float(part.split(":")[1])

        # Get latest weather reading
        weather_data = (
            self.db.query(SatelliteData)
            .filter(
                SatelliteData.plot_id == plot_id,
                SatelliteData.data_source == "weather",
                SatelliteData.data_type == "weather",
                SatelliteData.observation_date <= observation_date,
            )
            .order_by(SatelliteData.observation_date.desc())
            .first()
        )

        rainfall_mm = None
        temperature_max = None
        temperature_min = None
        if weather_data and weather_data.value:
            parts = weather_data.value.split(",")
            for part in parts:
                if part.startswith("rainfall:"):
                    rainfall_mm = float(part.split(":")[1])
                elif part.startswith("temp_max:"):
                    temperature_max = float(part.split(":")[1])
                elif part.startswith("temp_min:"):
                    temperature_min = float(part.split(":")[1])

        # Compute days since sowing
        days_since_sowing = None
        if plot.sowing_date:
            sowing_datetime = datetime.combine(plot.sowing_date, datetime.min.time(), tzinfo=timezone.utc)
            days_since_sowing = (observation_date - sowing_datetime).days

        return FeatureVector(
            plot_id=plot_id,
            observation_date=observation_date,
            ndvi=ndvi,
            ndvi_trend=ndvi_trend,
            sar_vv=sar_vv,
            sar_vh=sar_vh,
            rainfall_mm=rainfall_mm,
            temperature_max=temperature_max,
            temperature_min=temperature_min,
            days_since_sowing=days_since_sowing,
        )

    def compute_cloud_mask_quality(self, plot_id: str) -> float:
        """Compute average cloud coverage for recent observations (0-1)."""
        recent_data = (
            self.db.query(SatelliteData)
            .filter(
                SatelliteData.plot_id == plot_id,
                SatelliteData.data_source == "sentinel2",
                SatelliteData.observation_date >= utc_now() - timedelta(days=30),
            )
            .all()
        )

        if not recent_data:
            # No raw Sentinel-2 rows means there is no measured cloud penalty.
            # Canonical features may still be available from an upstream
            # ingestion job, so treat missing raw audit rows as neutral quality.
            return 0.0

        cloud_coverages = [float(d.cloud_coverage) for d in recent_data if d.cloud_coverage is not None]
        if not cloud_coverages:
            # The provider already filters Sentinel-2 scenes by cloud cover.
            # Missing metadata therefore means no measurable penalty, not 100%.
            return 0.0

        avg_coverage = sum(cloud_coverages) / len(cloud_coverages)
        return avg_coverage / 100.0  # Normalize to 0-1
