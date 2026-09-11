"""Provider boundary for Earth observation and weather ingestion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.models import Plot, SatelliteData
from app.services.mock_data_generator import generate_mock_ndvi, generate_mock_sar, generate_mock_weather
from app.utils.time import utc_now

logger = logging.getLogger(__name__)


class IngestionProvider(Protocol):
    name: str

    def fetch_cycle(self, plot: Plot) -> list[SatelliteData]: ...


class MockIngestionProvider:
    name = "mock"

    def fetch_cycle(self, plot: Plot) -> list[SatelliteData]:
        # Stable historical observations ending near the current cycle.
        base_date = utc_now() - timedelta(days=24)
        return (
            generate_mock_ndvi(plot.plot_id, base_date, num_cycles=5)
            + generate_mock_sar(plot.plot_id, base_date, num_cycles=3)
            + generate_mock_weather(plot.plot_id, utc_now() - timedelta(days=4), num_cycles=5)
        )


class GeeOpenMeteoProvider:
    """Fetch plot observations from Earth Engine and Open-Meteo."""

    name = "gee-open-meteo"
    weather_url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self) -> None:
        settings = get_settings()
        self.project_id = settings.gee_project_id
        self.credentials_path = settings.google_application_credentials
        self.service_account = settings.gee_service_account
        self.lookback_days = settings.ingestion_lookback_days

    def _init_gee_service_account(self):
        """Initialize Earth Engine using the configured service-account key."""
        try:
            import ee
        except ImportError as exc:
            raise RuntimeError(
                "earthengine-api is required when INGESTION_PROVIDER=gee"
            ) from exc

        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or self.credentials_path
        if not key_path or not Path(key_path).is_file():
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS must point to a GEE service-account key file"
            )
        try:
            info = json.loads(Path(key_path).read_text(encoding="utf-8"))
            client_email = info["client_email"]
            private_key = info["private_key"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "The GEE credentials file must contain client_email and private_key"
            ) from exc

        credentials = ee.ServiceAccountCredentials(client_email, key_data=private_key)
        ee.Initialize(credentials=credentials, project=self.project_id)
        logger.info("GEE initialized with service account %s", client_email)
        return ee

    def fetch_cycle(self, plot: Plot) -> list[SatelliteData]:
        if not plot.location_point:
            raise RuntimeError(f"Plot {plot.plot_id} has no location for live ingestion")
        latitude, longitude = self._parse_location(plot.location_point)
        if self.project_id is None or self.credentials_path is None:
            raise RuntimeError(
                "GEE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS are required for live ingestion"
            )
        satellite_records = self._fetch_earth_engine(plot, latitude, longitude) or []
        return satellite_records + self._fetch_weather(plot, latitude, longitude)

    @staticmethod
    def _parse_location(location: str) -> tuple[float, float]:
        point_match = re.fullmatch(
            r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
            location.strip(),
            re.IGNORECASE,
        )
        if point_match:
            longitude, latitude = (float(value) for value in point_match.groups())
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise RuntimeError("Plot coordinates are outside valid latitude/longitude ranges")
            return latitude, longitude
        try:
            latitude, longitude = (float(value.strip()) for value in location.split(",", 1))
        except (ValueError, AttributeError) as exc:
            raise RuntimeError("Plot location_point must be stored as 'latitude,longitude'") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise RuntimeError("Plot coordinates are outside valid latitude/longitude ranges")
        return latitude, longitude

    def _fetch_earth_engine(
        self, plot: Plot, latitude: float, longitude: float
    ) -> list[SatelliteData] | None:
        try:
            return self._fetch_earth_engine_impl(plot, latitude, longitude)
        except Exception:
            logger.exception("Earth Engine fetch failed for plot=%s; using fallback", plot.plot_id)
            return None

    def _fetch_earth_engine_impl(
        self, plot: Plot, latitude: float, longitude: float
    ) -> list[SatelliteData]:
        if self.project_id is None or self.credentials_path is None:
            raise RuntimeError(
                "GEE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS are required for live ingestion"
            )
        try:
            import ee
        except ImportError as exc:
            raise RuntimeError(
                "earthengine-api is required when INGESTION_PROVIDER=gee"
            ) from exc

        ee = self._init_gee_service_account()
        point = ee.Geometry.Point([longitude, latitude])  # pyright: ignore[reportPrivateImportUsage]
        region = point.buffer(100)
        end = utc_now()
        start = end - timedelta(days=self.lookback_days)
        start_date = start.date().isoformat()
        end_date = (end + timedelta(days=1)).date().isoformat()
        records: list[SatelliteData] = []

        optical = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")  # pyright: ignore[reportPrivateImportUsage]
            .filterBounds(point)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 30))  # pyright: ignore[reportPrivateImportUsage]
            .map(
                lambda image: image.normalizedDifference(["B8", "B4"])
                .rename("ndvi")
                .copyProperties(image, image.propertyNames())
            )
            .sort("system:time_start", False)
            .limit(5)
            .toList(5)
        )
        optical_count = min(5, int(optical.size().getInfo()))
        for index in range(optical_count):
            image = ee.Image(optical.get(index))  # pyright: ignore[reportPrivateImportUsage]
            metadata = image.get("system:time_start").getInfo()
            if metadata is None:
                continue
            values = image.reduceRegion(
                reducer=ee.Reducer.median(), geometry=region, scale=10, maxPixels=1_000_000  # pyright: ignore[reportPrivateImportUsage]
            ).getInfo()
            if not values:
                continue
            ndvi = values.get("ndvi")
            if ndvi is not None:
                records.append(self._record(
                    plot, "sentinel2", "ndvi", float(ndvi), metadata, f"gee-s2-ndvi-{plot.plot_id}-{index}"
                ))

        radar = (
            ee.ImageCollection("COPERNICUS/S1_GRD")  # pyright: ignore[reportPrivateImportUsage]
            .filterBounds(point)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.eq("instrumentMode", "IW"))  # pyright: ignore[reportPrivateImportUsage]
            .select(["VV", "VH"])
            .sort("system:time_start", False)
            .limit(3)
            .toList(3)
        )
        radar_count = min(3, int(radar.size().getInfo()))
        for index in range(radar_count):
            image = ee.Image(radar.get(index))  # pyright: ignore[reportPrivateImportUsage]
            metadata = image.get("system:time_start").getInfo()
            if metadata is None:
                continue
            values = image.reduceRegion(
                reducer=ee.Reducer.median(), geometry=region, scale=10, maxPixels=1_000_000  # pyright: ignore[reportPrivateImportUsage]
            ).getInfo()
            if not values:
                continue
            if values.get("VV") is not None and values.get("VH") is not None:
                records.append(self._record(
                    plot,
                    "sentinel1",
                    "sar",
                    f"VV:{float(values['VV'])},VH:{float(values['VH'])}",
                    metadata,
                    f"gee-s1-sar-{plot.plot_id}-{index}",
                ))
        return records

    def _fetch_weather(self, plot: Plot, latitude: float, longitude: float) -> list[SatelliteData]:
        response = httpx.get(
            self.weather_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "past_days": self.lookback_days,
                "daily": "precipitation_sum,et0_fao_evapotranspiration,temperature_2m_max",
                "timezone": "UTC",
            },
            timeout=20,
        )
        response.raise_for_status()
        daily = response.json().get("daily") or {}
        dates = daily.get("time") or []
        rainfall = daily.get("precipitation_sum") or []
        et0 = daily.get("et0_fao_evapotranspiration") or []
        temperature = daily.get("temperature_2m_max") or []
        records: list[SatelliteData] = []
        for index, value in enumerate(dates):
            if index >= len(rainfall) or rainfall[index] is None:
                continue
            record_date = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            records.append(self._record(
                plot,
                "weather",
                "weather",
                (
                    f"rainfall:{float(rainfall[index])},"
                    f"et0:{float(et0[index]) if index < len(et0) and et0[index] is not None else ''},"
                    f"lst:{float(temperature[index]) if index < len(temperature) and temperature[index] is not None else ''},"
                    "kc:,etc:,rain_forecast_48h:"
                ),
                int(record_date.timestamp() * 1000),
                f"open-meteo-weather-{plot.plot_id}-{value}",
            ))
        return records

    @staticmethod
    def _record(
        plot: Plot, source: str, data_type: str, value: object, timestamp: int | float | datetime, satellite_id: str
    ) -> SatelliteData:
        if isinstance(timestamp, datetime):
            observation_date = timestamp
        else:
            observation_date = datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc)
        return SatelliteData(
            satellite_id=satellite_id,
            plot_id=plot.plot_id,
            observation_date=observation_date,
            data_source=source,
            data_type=data_type,
            value=str(value),
            quality_flag="good",
            cloud_coverage=0.0 if source == "sentinel1" else None,
        )


def get_ingestion_provider(name: str) -> IngestionProvider:
    if name.lower() == "mock":
        return MockIngestionProvider()
    if name.lower() in {"gee", "live"}:
        return GeeOpenMeteoProvider()
    raise ValueError(f"Unknown ingestion provider: {name}")
