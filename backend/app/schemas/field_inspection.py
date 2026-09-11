from datetime import datetime

from pydantic import BaseModel


class FieldInspectionCreate(BaseModel):
    plot_id: str
    issue_type: str
    observed_condition: str
    severity: str
    farmer_comments: str | None = None
    officer_comments: str | None = None
    gps_lat: float | None = None
    gps_lng: float | None = None
    gps_accuracy_m: float | None = None
    photos: list[str] = []
    recommended_action: str | None = None
    status: str = "PENDING"


class FieldInspectionRead(BaseModel):
    inspection_id: str
    plot_id: str
    farmer_name: str
    district: str | None
    crop: str
    officer_name: str
    issue_type: str
    observed_condition: str | None
    severity: str
    farmer_comments: str | None
    officer_comments: str | None
    gps_lat: float | None
    gps_lng: float | None
    gps_accuracy_m: float | None
    photos: list[str]
    recommended_action: str | None
    status: str
    inspection_date: datetime
