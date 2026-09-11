"""
Plot Features Service -- sec 12.1 / 12.3 / 11.4

Builds canonical per-plot-per-date feature rows using the "nearest valid observation
per source" join logic defined in 11_Complete_Architecture.md sec 11.4.

Date-snapping rules:
  Sentinel-1 (SAR): nearest available pass within +/-3 days of obs_date
  Sentinel-2 (optical): nearest cloud-free pass within +/-5 days of obs_date
  Weather: exact date (cumulative windows 1/3/7/14d ending on obs_date)

SMAP ENFORCEMENT (sec 12.3.2):
  smap_sm is populated ONLY from SMAP-sourced satellite records.
  soil_moisture_label MUST NEVER receive SMAP values -- this is validated
  at write time to prevent circular evaluation (model reproducing SMAP).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import Plot, PlotFeatures, SatelliteData
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# Date-snapping tolerances per data source (sec 11.4 / 12.3.1)
SAR_SNAP_DAYS = 3       # Sentinel-1: +/-3 days
OPTICAL_SNAP_DAYS = 5   # Sentinel-2: +/-5 days (cloud-free)
WEATHER_SNAP_DAYS = 0   # exact date


VALID_LABEL_SOURCES = frozenset({"water_balance", "ismn", "farmer_feedback", "smap"})


def _days_delta(reference: date, dt: datetime) -> int:
    """Absolute day difference between a reference date and a datetime."""
    ref_dt = datetime.combine(reference, datetime.min.time(), tzinfo=timezone.utc)
    return abs((dt.replace(tzinfo=timezone.utc) - ref_dt).days)


class PlotFeaturesService:
    """Build and persist canonical PlotFeatures rows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_and_upsert(self, plot_id: str, obs_date: date) -> PlotFeatures:
        """
        Build (or update) the canonical feature row for (plot_id, obs_date).

        Calls each source-specific method with the appropriate snap tolerance
        and merges them into a single PlotFeatures row.  Safe to call
        idempotently -- existing rows are updated in place.
        """
        plot = self.db.query(Plot).filter(Plot.plot_id == plot_id).first()
        if not plot:
            raise ValueError(f"Plot {plot_id} not found")

        sar_features = self._snap_sar(plot_id, obs_date)
        optical_features = self._snap_optical(plot_id, obs_date)
        weather_features = self._snap_weather(plot_id, obs_date)
        smap_sm = self._snap_smap(plot_id, obs_date)
        crop_stage = self._derive_crop_stage(plot, obs_date)

        existing = (
            self.db.query(PlotFeatures)
            .filter(PlotFeatures.plot_id == plot_id, PlotFeatures.obs_date == obs_date)
            .first()
        )

        if existing is None:
            row = PlotFeatures(plot_id=plot_id, obs_date=obs_date)
            self.db.add(row)
        else:
            row = existing

        # SAR
        row.vv_db = sar_features.get("vv_db")
        row.vh_db = sar_features.get("vh_db")
        row.delta_vv_7d = sar_features.get("delta_vv_7d")
        row.delta_vh_7d = sar_features.get("delta_vh_7d")

        # Optical
        row.ndvi = optical_features.get("ndvi")
        row.ndwi = optical_features.get("ndwi")
        row.evi = optical_features.get("evi")
        row.savi = optical_features.get("savi")
        row.delta_ndvi_7d = optical_features.get("delta_ndvi_7d")
        row.delta_ndvi_14d = optical_features.get("delta_ndvi_14d")

        # Weather
        row.rainfall_1d = weather_features.get("rainfall_1d")
        row.rainfall_3d = weather_features.get("rainfall_3d")
        row.rainfall_7d = weather_features.get("rainfall_7d")
        row.rainfall_14d = weather_features.get("rainfall_14d")
        row.rain_forecast_48h = weather_features.get("rain_forecast_48h")
        row.et0 = weather_features.get("et0")
        row.kc = weather_features.get("kc")
        row.etc = weather_features.get("etc")
        row.lst = weather_features.get("lst")

        # SMAP (context feature only)
        row.smap_sm = smap_sm

        # Context
        row.crop_stage = crop_stage

        self.db.commit()
        self.db.refresh(row)

        # Log rejected-observation counts for monitoring (sec 12.3.3)
        logger.info(
            "PlotFeatures upsert complete: plot=%s date=%s sar_ok=%s optical_ok=%s weather_ok=%s",
            plot_id, obs_date,
            row.vv_db is not None,
            row.ndvi is not None,
            row.rainfall_7d is not None,
        )

        return row

    def write_label(
        self,
        plot_id: str,
        obs_date: date,
        soil_moisture_label: float,
        label_source: str,
    ) -> PlotFeatures:
        """
        Write a soil-moisture label to an existing PlotFeatures row.

        ENFORCEMENT (sec 12.3.2):
          label_source='smap' is only permitted when smap_sm is NOT populated
          in the same row (i.e., SMAP is not being used as an input feature).
          Violating this constraint raises ValueError to prevent circular leakage.
        """
        if label_source not in VALID_LABEL_SOURCES:
            raise ValueError(f"label_source must be one of {VALID_LABEL_SOURCES}, got: {label_source!r}")

        row = (
            self.db.query(PlotFeatures)
            .filter(PlotFeatures.plot_id == plot_id, PlotFeatures.obs_date == obs_date)
            .first()
        )
        if row is None:
            raise ValueError(f"No PlotFeatures row for plot={plot_id} date={obs_date}; call build_and_upsert first.")

        # Anti-leakage check (sec 12.3.2)
        if label_source == "smap" and row.smap_sm is not None:
            raise ValueError(
                "SMAP leakage guard: label_source='smap' is forbidden when smap_sm is also populated "
                "as an input feature in the same row.  Use label_source='water_balance' or 'ismn' instead."
            )

        row.soil_moisture_label = soil_moisture_label
        row.label_source = label_source
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_for_plot(self, plot_id: str, obs_date: date) -> Optional[PlotFeatures]:
        """Retrieve a canonical feature row by (plot_id, obs_date)."""
        return (
            self.db.query(PlotFeatures)
            .filter(PlotFeatures.plot_id == plot_id, PlotFeatures.obs_date == obs_date)
            .first()
        )

    def get_recent(self, plot_id: str, n: int = 30) -> list[PlotFeatures]:
        """Retrieve the N most-recent feature rows for a plot."""
        return (
            self.db.query(PlotFeatures)
            .filter(PlotFeatures.plot_id == plot_id)
            .order_by(PlotFeatures.obs_date.desc())
            .limit(n)
            .all()
        )

    # ------------------------------------------------------------------
    # Source-specific snapping helpers
    # ------------------------------------------------------------------

    def _snap_sar(self, plot_id: str, obs_date: date) -> dict:
        """
        Snap Sentinel-1 SAR data within +/-3 days of obs_date.
        Returns VV, VH and 7-day change-detection deltas.
        """
        anchor = self._nearest_obs(
            plot_id, data_source="sentinel1", data_type="sar",
            obs_date=obs_date, max_days=SAR_SNAP_DAYS, cloud_filter=False,
        )
        if anchor is None:
            return {}

        vv, vh = self._parse_sar_value(anchor.value)

        # Delta: find pass ~7 days prior
        prior_date = obs_date - timedelta(days=7)
        prior = self._nearest_obs(
            plot_id, data_source="sentinel1", data_type="sar",
            obs_date=prior_date, max_days=SAR_SNAP_DAYS, cloud_filter=False,
        )
        delta_vv = delta_vh = None
        if prior is not None:
            prior_vv, prior_vh = self._parse_sar_value(prior.value)
            if vv is not None and prior_vv is not None:
                delta_vv = vv - prior_vv
            if vh is not None and prior_vh is not None:
                delta_vh = vh - prior_vh

        return {"vv_db": vv, "vh_db": vh, "delta_vv_7d": delta_vv, "delta_vh_7d": delta_vh}

    def _snap_optical(self, plot_id: str, obs_date: date) -> dict:
        """
        Snap Sentinel-2 optical data within +/-5 days of obs_date (cloud-free only).
        Returns NDVI, NDWI, EVI, SAVI and 7/14-day NDVI deltas.
        """
        anchor = self._nearest_obs(
            plot_id, data_source="sentinel2", data_type="ndvi",
            obs_date=obs_date, max_days=OPTICAL_SNAP_DAYS, cloud_filter=True,
        )
        if anchor is None:
            return {}

        ndvi = self._safe_float(anchor.value)

        # 7-day and 14-day NDVI trends
        prior_7d = self._nearest_obs(
            plot_id, data_source="sentinel2", data_type="ndvi",
            obs_date=obs_date - timedelta(days=7), max_days=OPTICAL_SNAP_DAYS, cloud_filter=True,
        )
        prior_14d = self._nearest_obs(
            plot_id, data_source="sentinel2", data_type="ndvi",
            obs_date=obs_date - timedelta(days=14), max_days=OPTICAL_SNAP_DAYS, cloud_filter=True,
        )
        prior_7d_ndvi = self._safe_float(prior_7d.value) if prior_7d else None
        prior_14d_ndvi = self._safe_float(prior_14d.value) if prior_14d else None
        delta_7d = (ndvi - prior_7d_ndvi) if prior_7d_ndvi is not None and ndvi is not None else None
        delta_14d = (ndvi - prior_14d_ndvi) if prior_14d_ndvi is not None and ndvi is not None else None

        # Attempt to get NDWI, EVI, SAVI from separate data_type rows
        ndwi = self._snap_single_value(plot_id, "sentinel2", "ndwi", obs_date, OPTICAL_SNAP_DAYS)
        evi = self._snap_single_value(plot_id, "sentinel2", "evi", obs_date, OPTICAL_SNAP_DAYS)
        savi = self._snap_single_value(plot_id, "sentinel2", "savi", obs_date, OPTICAL_SNAP_DAYS)

        return {
            "ndvi": ndvi, "ndwi": ndwi, "evi": evi, "savi": savi,
            "delta_ndvi_7d": delta_7d, "delta_ndvi_14d": delta_14d,
        }

    def _snap_weather(self, plot_id: str, obs_date: date) -> dict:
        """
        Aggregate weather data for windows ending on obs_date (exact date).
        Returns rainfall windows, ET0, Kc, ETc, LST.
        """
        def _sum_rainfall(days: int) -> Optional[float]:
            start = obs_date - timedelta(days=days - 1)
            start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            end_dt = datetime.combine(obs_date, datetime.max.time(), tzinfo=timezone.utc)
            rows = (
                self.db.query(SatelliteData)
                .filter(
                    SatelliteData.plot_id == plot_id,
                    SatelliteData.data_source == "weather",
                    SatelliteData.data_type == "weather",
                    SatelliteData.observation_date >= start_dt,
                    SatelliteData.observation_date <= end_dt,
                )
                .all()
            )
            values = [self._parse_weather_key(r.value, "rainfall") for r in rows]
            values = [v for v in values if v is not None]
            return round(sum(values), 2) if values else None

        # Get the latest weather record for ET0, Kc, ETc, LST, forecast
        latest_weather = self._nearest_obs(
            plot_id, data_source="weather", data_type="weather",
            obs_date=obs_date, max_days=1, cloud_filter=False,
        )

        et0 = kc = etc = lst = rain_forecast_48h = None
        if latest_weather:
            et0 = self._parse_weather_key(latest_weather.value, "et0")
            kc = self._parse_weather_key(latest_weather.value, "kc")
            etc = self._parse_weather_key(latest_weather.value, "etc")
            lst = self._parse_weather_key(latest_weather.value, "lst")
            rain_forecast_48h = self._parse_weather_key(latest_weather.value, "rain_forecast_48h")

        return {
            "rainfall_1d": _sum_rainfall(1),
            "rainfall_3d": _sum_rainfall(3),
            "rainfall_7d": _sum_rainfall(7),
            "rainfall_14d": _sum_rainfall(14),
            "rain_forecast_48h": rain_forecast_48h,
            "et0": et0,
            "kc": kc,
            "etc": etc,
            "lst": lst,
        }

    def _snap_smap(self, plot_id: str, obs_date: date) -> Optional[float]:
        """
        Retrieve SMAP regional soil moisture as a context feature only.
        Must NOT be written to soil_moisture_label (enforced in write_label).
        """
        row = self._nearest_obs(
            plot_id, data_source="smap", data_type="soil_moisture",
            obs_date=obs_date, max_days=5, cloud_filter=False,
        )
        return self._safe_float(row.value) if row else None

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _nearest_obs(
        self,
        plot_id: str,
        data_source: str,
        data_type: str,
        obs_date: date,
        max_days: int,
        cloud_filter: bool,
    ) -> Optional[SatelliteData]:
        """
        Find the nearest SatelliteData record within max_days of obs_date.
        If cloud_filter=True, only returns records where cloud_masked=False
        or cloud_coverage < 30%.
        """
        ref_dt = datetime.combine(obs_date, datetime.min.time(), tzinfo=timezone.utc)
        low = ref_dt - timedelta(days=max_days)
        high = ref_dt + timedelta(days=max_days)

        query = (
            self.db.query(SatelliteData)
            .filter(
                SatelliteData.plot_id == plot_id,
                SatelliteData.data_source == data_source,
                SatelliteData.data_type == data_type,
                SatelliteData.observation_date >= low,
                SatelliteData.observation_date <= high,
            )
        )
        if cloud_filter:
            query = query.filter(
                and_(
                    SatelliteData.cloud_masked == False,  # noqa: E712
                    (SatelliteData.cloud_coverage == None) | (SatelliteData.cloud_coverage < 30),  # noqa: E711
                )
            )

        candidates = query.all()
        if not candidates:
            return None

        # Sort by absolute distance from obs_date ascending
        return min(candidates, key=lambda r: _days_delta(obs_date, r.observation_date))

    def _snap_single_value(
        self, plot_id: str, data_source: str, data_type: str, obs_date: date, max_days: int
    ) -> Optional[float]:
        row = self._nearest_obs(plot_id, data_source, data_type, obs_date, max_days, cloud_filter=True)
        return self._safe_float(row.value) if row else None

    @staticmethod
    def _parse_sar_value(raw: Optional[str]) -> tuple[Optional[float], Optional[float]]:
        """Parse 'VV:-12.3,VH:-18.7' format into (vv, vh)."""
        if not raw:
            return None, None
        vv = vh = None
        for part in raw.split(","):
            if part.startswith("VV:"):
                vv = PlotFeaturesService._safe_float(part.split(":", 1)[1])
            elif part.startswith("VH:"):
                vh = PlotFeaturesService._safe_float(part.split(":", 1)[1])
        return vv, vh

    @staticmethod
    def _parse_weather_key(raw: Optional[str], key: str) -> Optional[float]:
        """Parse 'key1:val1,key2:val2' format and return float for given key."""
        if not raw:
            return None
        for part in raw.split(","):
            if part.startswith(f"{key}:"):
                return PlotFeaturesService._safe_float(part.split(":", 1)[1])
        return None

    @staticmethod
    def _safe_float(value: Optional[str]) -> Optional[float]:
        """Safely convert a string to float, returning None on failure."""
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _derive_crop_stage(plot: Plot, obs_date: date) -> Optional[str]:
        """Map days-after-sowing to crop stage string."""
        if not plot.sowing_date:
            return None
        days = (obs_date - plot.sowing_date).days
        if days < 0:
            return None
        if days < 20:
            return "initial"
        if days < 60:
            return "development"
        if days < 120:
            return "mid_season"
        return "late_season"
