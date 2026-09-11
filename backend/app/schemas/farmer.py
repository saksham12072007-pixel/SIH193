from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class FarmerCreate(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=15)
    name: str | None = None
    preferred_language: str = "hi"
    state: str | None = None
    district: str | None = None
    registration_channel: str = "sms"
    consent_given: bool = False


class FarmerSessionRequest(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=15)
    origin_channel: str = Field(default="sms")


class FarmerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farmer_id: str
    phone_number: str
    name: str | None = None
    preferred_language: str
    state: str | None = None
    district: str | None = None
    consent_given_at: datetime | None = None
    registration_channel: str
    status: str
    created_at: datetime
    updated_at: datetime


class FarmerSessionResponse(BaseModel):
    farmer_id: str
    phone_number: str
    session_token: str
    token_type: str = "bearer"
