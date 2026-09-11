from datetime import timedelta
import base64
import hashlib
import hmac
import uuid
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.config import get_settings
from app.models import AdvisoryFeedback, MlPrediction, SmsLog
from app.routers.commands import parse_command
from app.routers.farmers import get_farmer_by_phone
from app.schemas.command import CommandRequest, CommandResponse
from app.services.messaging_service import MessagingService
from app.services.sms_session_service import SmsSessionService
from app.utils.time import utc_now

router = APIRouter(prefix="/sms", tags=["sms"])


class SmsSendRequest(BaseModel):
    farmer_phone: str | None = None
    message_body: str | None = None
    advisory_id: str | None = None
    gateway_message_id: str | None = None


class DeliveryReceiptRequest(BaseModel):
    gateway_message_id: str | None = None
    sms_log_id: str | None = None
    status: str = Field(default="delivered")


class InboundSmsRequest(BaseModel):
    farmer_phone: str
    message_body: str


class IvrRequest(BaseModel):
    farmer_phone: str
    script: str | None = None


class WhatsAppSendRequest(BaseModel):
    farmer_phone: str
    message_body: str


FEEDBACK_WINDOW_HOURS = 72
FEEDBACK_REPLY_MAP = {"1": "irrigated", "2": "not_needed", "3": "crop_damaged"}


@router.post("/send")
def send_sms(payload: SmsSendRequest | None = None, db: Session = Depends(get_db)) -> dict[str, str]:
    if payload is None or not payload.farmer_phone or not payload.message_body:
        return {"status": "queued", "provider": get_settings().sms_provider}

    farmer = get_farmer_by_phone(db, payload.farmer_phone)
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")

    MessagingService(db).ensure_sms_capacity(farmer.farmer_id)

    result = MessagingService(db).send_sms(farmer.phone_number, payload.message_body)
    sms_log = SmsLog(
        sms_log_id=str(uuid.uuid4()),
        advisory_id=payload.advisory_id,
        farmer_id=farmer.farmer_id,
        direction="outbound",
        message_body=payload.message_body,
        gateway_message_id=result.get("message_id") or payload.gateway_message_id,
        delivery_status=result.get("status", "queued"),
        retry_count=0,
        sent_at=utc_now(),
    )
    db.add(sms_log)
    db.commit()

    return {
        "status": "queued",
        "provider": result.get("gateway", get_settings().sms_provider),
        "message_id": sms_log.sms_log_id,
        "recipient": farmer.phone_number,
    }


@router.post("/whatsapp/send")
def send_whatsapp(payload: WhatsAppSendRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    farmer = get_farmer_by_phone(db, payload.farmer_phone)
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")
    MessagingService(db).ensure_sms_capacity(farmer.farmer_id)
    result = MessagingService(db).send_whatsapp(farmer.phone_number, payload.message_body)
    log = SmsLog(
        sms_log_id=str(uuid.uuid4()), farmer_id=farmer.farmer_id, direction="outbound",
        message_body=payload.message_body, gateway_message_id=result.get("message_id"),
        delivery_status=result.get("status", "queued"), retry_count=0, sent_at=utc_now(),
    )
    db.add(log)
    db.commit()
    return {"status": log.delivery_status, "provider": result.get("gateway", get_settings().sms_provider),
            "message_id": log.sms_log_id, "gateway_message_id": log.gateway_message_id or ""}


def _verify_twilio_signature(request: Request, body: bytes) -> None:
    settings = get_settings()
    if settings.sms_provider.lower() != "twilio":
        return
    signature = request.headers.get("X-Twilio-Signature")
    if not signature or not settings.twilio_auth_token:
        raise HTTPException(status_code=403, detail="Invalid Twilio webhook signature")
    params = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    expected = hmac.new(
        settings.twilio_auth_token.encode("utf-8"),
        (str(request.url) + "".join(f"{key}{params[key]}" for key in sorted(params))).encode("utf-8"),
        hashlib.sha1,
    ).digest()
    if not hmac.compare_digest(signature, base64.b64encode(expected).decode("ascii")):
        raise HTTPException(status_code=403, detail="Invalid Twilio webhook signature")


@router.post("/webhook/delivery")
async def delivery_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    body = await request.body()
    _verify_twilio_signature(request, body)
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        values = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
        payload = DeliveryReceiptRequest(
            gateway_message_id=values.get("MessageSid") or values.get("SmsSid"),
            status=values.get("MessageStatus") or values.get("SmsStatus") or "delivered",
        )
    elif body:
        payload = DeliveryReceiptRequest.model_validate_json(body)
    else:
        return {"status": "received"}

    query = db.query(SmsLog)
    if payload.sms_log_id:
        query = query.filter(SmsLog.sms_log_id == payload.sms_log_id)
    elif payload.gateway_message_id:
        query = query.filter(SmsLog.gateway_message_id == payload.gateway_message_id)
    else:
        raise HTTPException(status_code=400, detail="sms_log_id or gateway_message_id is required")

    sms_log = query.first()
    if not sms_log:
        raise HTTPException(status_code=404, detail="SMS log not found")

    status_map = {"queued": "queued", "accepted": "queued", "sending": "queued",
                  "sent": "sent", "delivered": "delivered", "failed": "failed",
                  "undelivered": "failed", "canceled": "failed"}
    sms_log.delivery_status = status_map.get(payload.status.lower(), "failed")
    if sms_log.delivery_status == "delivered":
        sms_log.delivered_at = utc_now()
    db.commit()

    return {"status": "received"}


@router.post("/inbound", response_model=CommandResponse)
def inbound_sms(payload: InboundSmsRequest | None = None, db: Session = Depends(get_db)) -> CommandResponse:
    if payload is None:
        return CommandResponse(ok=True, message="Inbound SMS processed", data={})

    session_result = SmsSessionService(db).handle_inbound(payload.farmer_phone, payload.message_body)
    if session_result is not None:
        return CommandResponse(
            ok=session_result.get("ok", True),
            message=session_result["message"],
            data=session_result.get("data", {}),
        )

    farmer = get_farmer_by_phone(db, payload.farmer_phone)
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")

    inbound_log = SmsLog(
        sms_log_id=str(uuid.uuid4()),
        farmer_id=farmer.farmer_id,
        direction="inbound",
        message_body=payload.message_body,
        delivery_status="delivered",
        retry_count=0,
        sent_at=utc_now(),
        delivered_at=utc_now(),
    )
    db.add(inbound_log)
    db.commit()

    normalized_message = payload.message_body.strip()
    if normalized_message in FEEDBACK_REPLY_MAP:
        window_start = utc_now() - timedelta(hours=FEEDBACK_WINDOW_HOURS)
        latest_advisory_log = (
            db.query(SmsLog)
            .filter(
                SmsLog.farmer_id == farmer.farmer_id,
                SmsLog.direction == "outbound",
                SmsLog.advisory_id.isnot(None),
                SmsLog.sent_at.isnot(None),
                SmsLog.sent_at >= window_start,
            )
            .order_by(SmsLog.sent_at.desc())
            .first()
        )
        if latest_advisory_log and latest_advisory_log.advisory_id:
            feedback = AdvisoryFeedback(
                feedback_id=str(uuid.uuid4()),
                advisory_id=latest_advisory_log.advisory_id,
                farmer_id=farmer.farmer_id,
                reply_code=FEEDBACK_REPLY_MAP[normalized_message],
                raw_reply_text=normalized_message,
                received_at=utc_now(),
                predicted_class=(latest_advisory_log.advisory.prediction.advisory_class if latest_advisory_log.advisory and latest_advisory_log.advisory.prediction else None),
                predicted_confidence=(float(latest_advisory_log.advisory.prediction.confidence_score) if latest_advisory_log.advisory and latest_advisory_log.advisory.prediction and latest_advisory_log.advisory.prediction.confidence_score is not None else None),
                predicted_soil_moisture=(float(latest_advisory_log.advisory.prediction.stage1_soil_moisture_estimate) if latest_advisory_log.advisory and latest_advisory_log.advisory.prediction and latest_advisory_log.advisory.prediction.stage1_soil_moisture_estimate is not None else None),
                model_version=(latest_advisory_log.advisory.prediction.model_version if latest_advisory_log.advisory and latest_advisory_log.advisory.prediction else None),
            )
            db.add(feedback)
            db.commit()
            return CommandResponse(
                ok=True,
                message="Feedback recorded successfully",
                data={"advisory_id": latest_advisory_log.advisory_id, "reply_code": FEEDBACK_REPLY_MAP[normalized_message]},
            )
        return CommandResponse(
            ok=False,
            message="We could not match this feedback to a recent advisory. Please reply to an advisory within 72 hours.",
            data={},
        )

    if normalized_message.isdigit():
        return CommandResponse(
            ok=False,
            message="Unrecognized reply. Please send 1 for irrigated, 2 for not needed, or 3 for crop damaged.",
            data={},
        )

    try:
        command_response = parse_command(
            CommandRequest(farmer_phone=payload.farmer_phone, command=payload.message_body, trusted_origin=True),
            db,
        )
        return command_response
    except HTTPException as exc:
        if exc.status_code == 400:
            return CommandResponse(
                ok=False,
                message="Unrecognized command. Send HELP to view available commands.",
                data={},
            )
        raise


@router.post("/ivr")
def trigger_ivr(payload: IvrRequest | None = None) -> dict[str, str]:
    if payload is None or not payload.farmer_phone:
        return {"status": "queued", "provider": get_settings().ivr_provider}
    result = MessagingService().send_ivr(payload.farmer_phone, payload.script or "")
    return {"status": result.get("status", "queued"), "provider": result.get("gateway", get_settings().ivr_provider),
            "recipient": payload.farmer_phone, "message_id": result.get("message_id", "")}
