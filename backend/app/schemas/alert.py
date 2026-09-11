from datetime import datetime

from pydantic import BaseModel


class AlertStatusUpdate(BaseModel):
    status: str
    resolution_notes: str | None = None
    assigned_user_id: str | None = None


class AlertRead(BaseModel):
    alert_id: str
    plot_id: str
    farmer_id: str
    farmer_name: str
    district: str | None
    crop: str
    severity: str
    title: str
    description: str
    trigger_metric: str | None
    trigger_value: str | None
    threshold: str | None
    status: str
    assigned_user_id: str | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
