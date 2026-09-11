from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AlertRuleMetric = Literal["NIR", "NDVI", "RAINFALL", "SOIL_MOISTURE", "TEMPERATURE"]
AlertRuleOperator = Literal["<", ">", "DECREASE_PERCENT"]
AlertRuleSeverity = Literal["SAFE", "MODERATE", "HIGH", "URGENT"]


class AlertRuleCreate(BaseModel):
    name: str
    metric: AlertRuleMetric
    operator: AlertRuleOperator
    value: float
    severity: AlertRuleSeverity
    district: str | None = None
    crop: str | None = None
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    enabled: bool


class AlertRuleRead(BaseModel):
    rule_id: str
    name: str
    metric: str
    operator: str
    value: float
    severity: str
    district: str | None
    crop: str | None
    enabled: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime
