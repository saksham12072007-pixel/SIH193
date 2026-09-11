"""Messaging provider boundary and bounded retry handling."""
from __future__ import annotations

from dataclasses import dataclass
import httpx
from typing import Protocol
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import SmsLog
from app.core.config import get_settings
from app.utils.time import utc_now

MAX_SMS_ATTEMPTS = 2
DEFAULT_DAILY_SMS_CAP = 5


@dataclass
class MockMessagingProvider:
    name: str = "mock"

    def send_sms(self, farmer_phone: str, message_body: str) -> dict[str, str]:
        return {"status": "queued", "gateway": self.name, "message": message_body, "recipient": farmer_phone}

    def send_ivr(self, farmer_phone: str, script: str) -> dict[str, str]:
        return {"status": "queued", "gateway": self.name, "script": script, "recipient": farmer_phone}

    def send_whatsapp(self, farmer_phone: str, message_body: str) -> dict[str, str]:
        return {"status": "queued", "gateway": self.name, "message": message_body, "recipient": farmer_phone}


class MessagingProvider(Protocol):
    name: str
    def send_sms(self, farmer_phone: str, message_body: str) -> dict[str, str]: ...
    def send_ivr(self, farmer_phone: str, script: str) -> dict[str, str]: ...
    def send_whatsapp(self, farmer_phone: str, message_body: str) -> dict[str, str]: ...


class TwilioMessagingProvider:
    """Twilio REST adapter for SMS, WhatsApp, and outbound voice calls."""

    name = "twilio"
    api_url = "https://api.twilio.com/2010-04-01"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required for Twilio")
        self.account_sid = settings.twilio_account_sid
        self.auth = (settings.twilio_account_sid, settings.twilio_auth_token)
        self.sms_from = settings.twilio_sms_from
        self.whatsapp_from = settings.twilio_whatsapp_from
        self.voice_from = settings.twilio_voice_from
        self.callback_url = settings.twilio_status_callback_url

    def _send(self, path: str, data: dict[str, str]) -> dict[str, str]:
        response = httpx.post(
            f"{self.api_url}/Accounts/{self.account_sid}{path}",
            data=data,
            auth=self.auth,
            timeout=15,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Twilio request failed ({response.status_code}): {response.text[:300]}")
        body = response.json()
        return {"status": "queued", "gateway": self.name, "message_id": body["sid"]}

    def send_sms(self, farmer_phone: str, message_body: str) -> dict[str, str]:
        if not self.sms_from:
            raise RuntimeError("TWILIO_SMS_FROM is required for SMS")
        data = {"To": farmer_phone, "From": self.sms_from, "Body": message_body}
        if self.callback_url:
            data["StatusCallback"] = self.callback_url
        return self._send("/Messages.json", data)

    def send_whatsapp(self, farmer_phone: str, message_body: str) -> dict[str, str]:
        if not self.whatsapp_from:
            raise RuntimeError("TWILIO_WHATSAPP_FROM is required for WhatsApp")
        data = {"To": f"whatsapp:{farmer_phone}", "From": f"whatsapp:{self.whatsapp_from}", "Body": message_body}
        if self.callback_url:
            data["StatusCallback"] = self.callback_url
        return self._send("/Messages.json", data)

    def send_ivr(self, farmer_phone: str, script: str) -> dict[str, str]:
        if not self.voice_from:
            raise RuntimeError("TWILIO_VOICE_FROM is required for IVR")
        twiml = f"<Response><Say language=\"en-IN\">{_xml_escape(script)}</Say></Response>"
        return self._send("/Calls.json", {"To": farmer_phone, "From": self.voice_from, "Twiml": twiml})


def _xml_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def get_messaging_provider(name: str | None = None) -> MessagingProvider:
    provider_name = (name or get_settings().sms_provider).lower()
    if provider_name == "mock":
        return MockMessagingProvider()
    if provider_name == "twilio":
        return TwilioMessagingProvider()
    raise ValueError(f"Unknown messaging provider: {provider_name}")


class MessagingService:
    def __init__(self, db: Session | None = None, provider: MessagingProvider | None = None):
        self.db = db
        self.provider = provider or get_messaging_provider()

    def count_outbound_sms(self, farmer_id: str, window_hours: int = 24) -> int:
        if self.db is None:
            return 0
        window_start = utc_now() - timedelta(hours=window_hours)
        return (
            self.db.query(SmsLog)
            .filter(
                SmsLog.farmer_id == farmer_id,
                SmsLog.direction == "outbound",
                SmsLog.sent_at.isnot(None),
                SmsLog.sent_at >= window_start,
            )
            .count()
        )

    def ensure_sms_capacity(self, farmer_id: str, daily_cap: int = DEFAULT_DAILY_SMS_CAP) -> None:
        if self.db is None:
            return
        if self.count_outbound_sms(farmer_id) >= daily_cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily SMS limit reached for this farmer",
            )

    def send_sms(self, farmer_phone: str, message_body: str) -> dict[str, str]:
        return self.provider.send_sms(farmer_phone, message_body)

    def send_whatsapp(self, farmer_phone: str, message_body: str) -> dict[str, str]:
        return self.provider.send_whatsapp(farmer_phone, message_body)

    def send_ivr(self, farmer_phone: str, script: str) -> dict[str, str]:
        return self.provider.send_ivr(farmer_phone, script)

    def retry_failed(self) -> int:
        if self.db is None:
            raise ValueError("A database session is required to retry SMS messages")
        logs = self.db.query(SmsLog).filter(
            SmsLog.delivery_status == "failed",
            SmsLog.retry_count < MAX_SMS_ATTEMPTS - 1,
            SmsLog.direction == "outbound",
        ).all()
        for log in logs:
            try:
                result = self.send_sms(log.farmer.phone_number, log.message_body or "")
                log.gateway_message_id = result.get("message_id")
                log.retry_count += 1
                log.delivery_status = "queued"
                log.sent_at = utc_now()
            except (RuntimeError, httpx.HTTPError):
                log.retry_count += 1
        self.db.commit()
        return len(logs)
