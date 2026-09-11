"""Compliance helpers for deletion and anonymization workflows."""

import uuid

from sqlalchemy.orm import Session

from app.models import AdvisoryFeedback, Farmer, Plot, SmsLog
from app.utils.audit import AuditEventType, log_audit_event
from app.utils.time import utc_now


def _anonymized_phone(farmer_id: str) -> str:
    return f"ANON{farmer_id.replace('-', '')[:11]}"


def anonymize_farmer_data(db: Session, farmer_id: str) -> dict[str, int | str]:
    farmer = db.query(Farmer).filter(Farmer.farmer_id == farmer_id).first()
    if not farmer:
        raise ValueError("Farmer not found")

    log_audit_event(
        db,
        str(uuid.uuid4()),
        AuditEventType.DATA_DELETION_REQUESTED,
        farmer_id=farmer_id,
        details="Farmer data deletion/anonymization requested",
    )

    plot_count = 0
    for plot in db.query(Plot).filter(Plot.farmer_id == farmer_id).all():
        plot.status = "deactivated"
        plot.plot_nickname = None
        plot.location_point = None
        plot.village_name = None
        plot.buffer_polygon = None
        plot.location_precision = "redacted"
        plot.updated_at = utc_now()
        plot_count += 1

    sms_logs_updated = 0
    for sms_log in db.query(SmsLog).filter(SmsLog.farmer_id == farmer_id).all():
        sms_log.message_body = None
        sms_logs_updated += 1

    feedback_updated = 0
    for feedback in db.query(AdvisoryFeedback).filter(AdvisoryFeedback.farmer_id == farmer_id).all():
        feedback.raw_reply_text = None
        feedback_updated += 1

    farmer.phone_number = _anonymized_phone(farmer_id)
    farmer.name = None
    farmer.state = None
    farmer.district = None
    farmer.consent_given_at = None
    farmer.status = "deactivated"
    farmer.updated_at = utc_now()

    db.commit()

    log_audit_event(
        db,
        str(uuid.uuid4()),
        AuditEventType.DATA_ANONYMIZED,
        farmer_id=farmer_id,
        details="Farmer PII redacted and operational records anonymized",
    )

    return {
        "status": "anonymized",
        "farmer_id": farmer_id,
        "plots_redacted": plot_count,
        "sms_logs_redacted": sms_logs_updated,
        "feedback_rows_redacted": feedback_updated,
    }