from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator


class PlotCreate(BaseModel):
    farmer_id: str
    plot_nickname: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_precision: str = "gps"
    village_name: str | None = None
    crop_type: str = Field(..., min_length=2)
    plot_size_declared: float | None = Field(default=None, gt=0, le=10000)
    sowing_date: date | None = None
    soil_texture: str | None = None
    irrigation_type: str | None = None

    @model_validator(mode="after")
    def validate_location(self) -> "PlotCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be provided together")
        if self.latitude is not None and not (-90 <= self.latitude <= 90):
            raise ValueError("Latitude must be between -90 and 90")
        if self.longitude is not None and not (-180 <= self.longitude <= 180):
            raise ValueError("Longitude must be between -180 and 180")
        if self.latitude is None and not self.village_name:
            raise ValueError("Latitude/longitude or village fallback is required")
        return self


class PlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plot_id: str
    farmer_id: str
    plot_nickname: str | None = None
    location_precision: str
    village_name: str | None = None
    buffer_polygon: str | None = None
    crop_type: str
    plot_size_declared: float | None = None
    sowing_date: date | None = None
    soil_texture: str | None = None
    irrigation_type: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
