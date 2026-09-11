from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class AdvisoryDecision(BaseModel):
    advisory_class: str = Field(..., examples=["monitor", "irrigate_soon", "irrigate_now"])
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reason_code: str
    model_version: str = "baseline-v1"


class AdvisoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    advisory_id: str
    plot_id: str
    prediction_id: str
    advisory_class: str
    language_used: str | None = None
    sms_sent: bool = False
    ivr_triggered: bool = False
    created_at: datetime
