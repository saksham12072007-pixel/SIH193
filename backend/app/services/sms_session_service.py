"""SMS/USSD onboarding state machine."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Farmer, Plot, SmsConversationSession
from app.routers.farmers import normalize_phone_number
from app.utils.time import utc_now


LANGUAGE_MAP = {
    "1": "hi",
    "2": "mr",
    "3": "te",
    "4": "en",
    "HINDI": "hi",
    "MARATHI": "mr",
    "TELUGU": "te",
    "ENGLISH": "en",
    "HI": "hi",
    "MR": "mr",
    "TE": "te",
    "EN": "en",
}


def _language_name(code: str) -> str:
    return {"hi": "Hindi", "mr": "Marathi", "te": "Telugu", "en": "English"}.get(code, code)


def _parse_date(text: str) -> datetime | None:
    cleaned = text.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d/%m"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if fmt == "%d/%m":
                parsed = parsed.replace(year=utc_now().year)
            return parsed
        except ValueError:
            continue
    return None


def _parse_location(message_text: str) -> tuple[str | None, str | None, float | None, float | None]:
    text = message_text.strip()
    gps_match = re.match(r"^GPS\s*:?\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)$", text, flags=re.IGNORECASE)
    if gps_match:
        return None, "gps", float(gps_match.group(1)), float(gps_match.group(2))
    if text.upper().startswith("VILLAGE:"):
        return text.split(":", 1)[1].strip(), "village_fallback", None, None
    return text, "village_fallback", None, None


class SmsSessionService:
    def __init__(self, db: Session):
        self.db = db

    def get_session(self, phone_number: str) -> SmsConversationSession | None:
        normalized_phone = normalize_phone_number(phone_number)
        return (
            self.db.query(SmsConversationSession)
            .filter(SmsConversationSession.phone_number == normalized_phone)
            .first()
        )

    def start_session(self, phone_number: str, channel: str = "sms") -> SmsConversationSession:
        normalized_phone = normalize_phone_number(phone_number)
        session = self.get_session(normalized_phone)
        if not session:
            session = SmsConversationSession(
                session_id=str(uuid.uuid4()),
                phone_number=normalized_phone,
                channel=channel,
                current_state="awaiting_name",
                context={},
                is_active=True,
            )
            self.db.add(session)
        else:
            session.channel = channel
            session.current_state = "awaiting_name"
            session.context = {}
            session.is_active = True
            session.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(session)
        return session

    def handle_inbound(self, phone_number: str, message_text: str) -> dict | None:
        normalized_phone = normalize_phone_number(phone_number)
        message = message_text.strip()
        message_upper = message.upper()

        session = self.get_session(normalized_phone)
        if message_upper in {"JOIN", "START"}:
            session = self.start_session(normalized_phone, channel="sms")
            return {"ok": True, "message": "Welcome! Reply with your name.", "data": {"session_state": session.current_state}}

        if not session or not session.is_active or session.current_state == "idle":
            return None

        context = dict(session.context or {})

        if session.current_state == "awaiting_name":
            context["name"] = message
            session.context = context
            session.current_state = "awaiting_language"
            session.updated_at = utc_now()
            self.db.commit()
            return {"ok": True, "message": "Choose language: 1-Hindi 2-Marathi 3-Telugu 4-English", "data": {"session_state": session.current_state}}

        if session.current_state == "awaiting_language":
            language = LANGUAGE_MAP.get(message_upper)
            if not language:
                return {"ok": False, "message": "Choose 1-Hindi 2-Marathi 3-Telugu 4-English", "data": {"session_state": session.current_state}}
            context["preferred_language"] = language
            session.context = context
            session.current_state = "awaiting_consent"
            session.updated_at = utc_now()
            self.db.commit()
            return {"ok": True, "message": "Do you consent to share your phone number and plot location for crop advisories? Reply YES to continue.", "data": {"session_state": session.current_state}}

        if session.current_state == "awaiting_consent":
            if message_upper not in {"YES", "Y", "CONSENT"}:
                session.current_state = "cancelled"
                session.is_active = False
                session.updated_at = utc_now()
                self.db.commit()
                return {"ok": False, "message": "Registration cancelled. Text JOIN anytime to restart.", "data": {"session_state": session.current_state}}
            context["consent_given"] = True
            session.context = context
            session.current_state = "awaiting_location"
            session.updated_at = utc_now()
            self.db.commit()
            return {"ok": True, "message": "Share your plot location (reply with GPS:lat,lon or village name).", "data": {"session_state": session.current_state}}

        if session.current_state == "awaiting_location":
            village_name, location_precision, latitude, longitude = _parse_location(message)
            context["village_name"] = village_name
            context["location_precision"] = location_precision
            context["latitude"] = latitude
            context["longitude"] = longitude
            session.context = context
            session.current_state = "awaiting_crop"
            session.updated_at = utc_now()
            self.db.commit()
            return {"ok": True, "message": "What crop is growing on this plot? Reply with crop name.", "data": {"session_state": session.current_state}}

        if session.current_state == "awaiting_crop":
            context["crop_type"] = message.lower().strip()
            session.context = context
            session.current_state = "awaiting_sowing_date"
            session.updated_at = utc_now()
            self.db.commit()
            return {"ok": True, "message": "When did you sow this crop? Reply DD/MM or DD/MM/YYYY.", "data": {"session_state": session.current_state}}

        if session.current_state == "awaiting_sowing_date":
            sowing_date = _parse_date(message)
            if not sowing_date:
                return {"ok": False, "message": "Please reply with sowing date in DD/MM or DD/MM/YYYY format.", "data": {"session_state": session.current_state}}
            context["sowing_date"] = sowing_date.date().isoformat()
            session.context = context
            farmer = self._upsert_farmer(normalized_phone, context)
            plot = self._create_plot(farmer, context)
            session.farmer_id = farmer.farmer_id
            session.current_state = "completed"
            session.is_active = False
            session.updated_at = utc_now()
            self.db.commit()
            return {
                "ok": True,
                "message": f"Registration complete! You'll get advisories for your {plot.crop_type} plot in {farmer.preferred_language}.",
                "data": {"farmer_id": farmer.farmer_id, "plot_id": plot.plot_id, "session_state": session.current_state},
            }

        return None

    def _upsert_farmer(self, phone_number: str, context: dict) -> Farmer:
        farmer = self.db.query(Farmer).filter(Farmer.phone_number == phone_number).first()
        if farmer:
            farmer.name = context.get("name") or farmer.name
            farmer.preferred_language = context.get("preferred_language") or farmer.preferred_language
            farmer.consent_given_at = farmer.consent_given_at or utc_now()
            farmer.status = "active"
            farmer.updated_at = utc_now()
        else:
            farmer = Farmer(
                farmer_id=str(uuid.uuid4()),
                phone_number=phone_number,
                name=context.get("name"),
                preferred_language=context.get("preferred_language") or "hi",
                state=None,
                district=None,
                consent_given_at=utc_now(),
                registration_channel="sms",
                status="active",
            )
            self.db.add(farmer)
        self.db.commit()
        self.db.refresh(farmer)
        return farmer

    def _create_plot(self, farmer: Farmer, context: dict) -> Plot:
        plot = Plot(
            plot_id=str(uuid.uuid4()),
            farmer_id=farmer.farmer_id,
            plot_nickname=f"Plot {len(farmer.plots) + 1}",
            location_point=None,
            location_precision=context.get("location_precision") or "village_fallback",
            village_name=context.get("village_name"),
            buffer_polygon=None,
            crop_type=(context.get("crop_type") or "rice").lower(),
            plot_size_declared=None,
            sowing_date=datetime.fromisoformat(context["sowing_date"]).date(),
            status="active",
        )
        self.db.add(plot)
        self.db.commit()
        self.db.refresh(plot)
        return plot