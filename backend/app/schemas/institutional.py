from datetime import date, datetime

from pydantic import BaseModel


class PlotHistoryPoint(BaseModel):
    date: date
    ndvi: float | None = None
    nir: float | None = None
    rainfall_7d: float | None = None


class InstitutionalPlotMarker(BaseModel):
    plot_id: str
    farmer_id: str
    crop: str
    state: str | None = None
    district: str | None = None
    village: str | None = None
    latitude: float
    longitude: float
    location_precision: str
    observed_at: datetime | None = None
    ndvi: float | None = None
    nir: float | None = None
    status: str
    urgency: str | None = None


class PlotHistoryResponse(BaseModel):
    plot_id: str
    crop: str
    location_precision: str
    series: list[PlotHistoryPoint]
