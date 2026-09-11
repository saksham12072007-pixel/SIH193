from pydantic import BaseModel


class CommandRequest(BaseModel):
    farmer_phone: str
    command: str
    payload: dict | None = None
    session_token: str | None = None
    trusted_origin: bool = False


class CommandResponse(BaseModel):
    ok: bool
    message: str
    data: dict | None = None
