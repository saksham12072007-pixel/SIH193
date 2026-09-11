"""Audit logging for consent, deletions, and compliance tracking (DPDP Act 2023)."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.db.database import Base
from app.utils.time import utc_now


class AuditEventType(str, Enum):
    FARMER_REGISTERED = "farmer_registered"
    CONSENT_GIVEN = "consent_given"
    PLOT_CREATED = "plot_created"
    ADVISORY_SENT = "advisory_sent"
    FEEDBACK_RECEIVED = "feedback_received"
    DATA_DELETION_REQUESTED = "data_deletion_requested"
    DATA_ANONYMIZED = "data_anonymized"
    ALERT_STATUS_UPDATED = "alert_status_updated"
    ALERT_RULE_CREATED = "alert_rule_created"
    ALERT_RULE_TOGGLED = "alert_rule_toggled"
    FIELD_INSPECTION_SUBMITTED = "field_inspection_submitted"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id = Column(String(36), primary_key=True)
    event_type = Column(String(50), nullable=False)
    farmer_id = Column(String(36), nullable=True)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(36), nullable=True)
    details = Column(Text, nullable=True)
    # Who performed the action. "farmer" events are self-service (registration,
    # consent, deletion requests); "institutional" events are logged with the
    # acting officer's user id and a human-readable label (their derived name)
    # so the audit trail doesn't need a join to be readable.
    actor_type = Column(String(20), nullable=False, default="system")
    actor_id = Column(String(36), nullable=True)
    actor_label = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


def log_audit_event(
    db: Session,
    audit_id: str,
    event_type: AuditEventType,
    farmer_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    actor_label: str | None = None,
) -> None:
    """Log an audit event for compliance and institutional-action audit trails."""
    event = AuditLog(
        audit_id=audit_id,
        event_type=event_type.value,
        farmer_id=farmer_id,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
    )
    db.add(event)
    db.commit()
