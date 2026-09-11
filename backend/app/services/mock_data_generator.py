"""Mock EO data generator for testing satellite data ingestion."""

import random
from datetime import datetime, timedelta

from app.models import SatelliteData
from app.utils.time import utc_now


def generate_mock_ndvi(
    plot_id: str, base_date: datetime | None = None, num_cycles: int = 5
) -> list[SatelliteData]:
    """Generate synthetic NDVI readings for a plot."""
    if base_date is None:
        base_date = utc_now() - timedelta(days=30)

    ndvi_readings = []
    for i in range(num_cycles):
        observation_date = base_date + timedelta(days=i * 6)
        ndvi_value = round(random.uniform(0.3, 0.8), 3)
        satellite_data = SatelliteData(
            satellite_id=f"ndvi-{plot_id}-{i}",
            plot_id=plot_id,
            observation_date=observation_date,
            data_source="sentinel2",
            data_type="ndvi",
            value=ndvi_value,
            quality_flag="good",
            cloud_coverage=round(random.uniform(0, 20), 1),
        )
        ndvi_readings.append(satellite_data)

    return ndvi_readings


def generate_mock_sar(plot_id: str, base_date: datetime | None = None, num_cycles: int = 5) -> list[SatelliteData]:
    """Generate synthetic SAR (Sentinel-1) readings for a plot."""
    if base_date is None:
        base_date = utc_now() - timedelta(days=30)

    sar_readings = []
    for i in range(num_cycles):
        observation_date = base_date + timedelta(days=i * 12)
        vv_value = round(random.uniform(-15, -5), 2)
        vh_value = round(random.uniform(-25, -15), 2)
        satellite_data = SatelliteData(
            satellite_id=f"sar-{plot_id}-{i}",
            plot_id=plot_id,
            observation_date=observation_date,
            data_source="sentinel1",
            data_type="sar",
            value=f"VV:{vv_value},VH:{vh_value}",
            quality_flag="good",
            cloud_coverage=0.0,
        )
        sar_readings.append(satellite_data)

    return sar_readings


def generate_mock_weather(
    plot_id: str, base_date: datetime | None = None, num_cycles: int = 5
) -> list[SatelliteData]:
    """Generate synthetic weather data for a plot."""
    if base_date is None:
        base_date = utc_now() - timedelta(days=30)

    weather_readings = []
    for i in range(num_cycles):
        observation_date = base_date + timedelta(days=i)
        rainfall = round(random.uniform(0, 50), 1)
        temp_max = round(random.uniform(25, 38), 1)
        temp_min = round(random.uniform(15, 25), 1)
        satellite_data = SatelliteData(
            satellite_id=f"weather-{plot_id}-{i}",
            plot_id=plot_id,
            observation_date=observation_date,
            data_source="weather",
            data_type="weather",
            value=f"rainfall:{rainfall},temp_max:{temp_max},temp_min:{temp_min}",
            quality_flag="good",
            cloud_coverage=None,
        )
        weather_readings.append(satellite_data)

    return weather_readings
