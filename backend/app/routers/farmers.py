import uuid
from datetime import datetime

import phonenumbers
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import create_farmer_session_token
from app.core.auth import verify_farmer_session_token
from app.core.auth import verify_institutional_access_token
from app.db.database import get_db
from app.models import Farmer
from app.schemas.farmer import FarmerCreate, FarmerRead, FarmerSessionRequest, FarmerSessionResponse
from app.services.compliance_service import anonymize_farmer_data
from app.utils.audit import AuditEventType, log_audit_event
from app.utils.time import utc_now

router = APIRouter(prefix="/farmers", tags=["farmers"])


def normalize_phone_number(phone_number: str) -> str:
    parsed = phonenumbers.parse(phone_number, "IN")
    if not phonenumbers.is_valid_number(parsed):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def get_farmer_by_phone(db: Session, phone_number: str) -> Farmer | None:
    """Look up farmer by normalized phone number."""
    normalized_phone = normalize_phone_number(phone_number)
    return db.query(Farmer).filter(Farmer.phone_number == normalized_phone).first()


def _is_owner_session(session_token: str | None, farmer: Farmer) -> bool:
    if not session_token:
        return False
    try:
        payload = verify_farmer_session_token(session_token)
    except HTTPException:
        return False
    return payload.get("farmer_id") == farmer.farmer_id and payload.get("phone_number") == farmer.phone_number


def _mask_farmer(farmer: Farmer, *, anonymized: bool = False, include_name: bool = False) -> Farmer:
    return Farmer(
        farmer_id=farmer.farmer_id,
        phone_number=(f"ANON{farmer.farmer_id.replace('-', '')[:11]}" if anonymized else "REDACTED"),
        name=(farmer.name if include_name and not anonymized else None),
        preferred_language=farmer.preferred_language,
        state=None,
        district=None,
        consent_given_at=farmer.consent_given_at,
        registration_channel=farmer.registration_channel,
        created_at=farmer.created_at,
        updated_at=farmer.updated_at,
        status=farmer.status,
    )


@router.post("/register", response_model=FarmerRead, status_code=status.HTTP_201_CREATED)
def register_farmer(payload: FarmerCreate, db: Session = Depends(get_db)) -> Farmer:
    normalized_phone = normalize_phone_number(payload.phone_number)
    existing = db.query(Farmer).filter(Farmer.phone_number == normalized_phone).first()

    if existing:
        existing.name = payload.name or existing.name
        existing.preferred_language = payload.preferred_language or existing.preferred_language
        existing.state = payload.state or existing.state
        existing.district = payload.district or existing.district
        existing.registration_channel = payload.registration_channel
        if payload.consent_given:
            existing.consent_given_at = utc_now()
            log_audit_event(
                db,
                str(uuid.uuid4()),
                AuditEventType.CONSENT_GIVEN,
                farmer_id=existing.farmer_id,
                details=f"Consent updated via {payload.registration_channel}",
                actor_type="farmer",
                actor_id=existing.farmer_id,
                actor_label=existing.name or existing.phone_number,
            )
        existing.updated_at = utc_now()
        db.commit()
        db.refresh(existing)
        return existing

    if not payload.consent_given:
        raise HTTPException(status_code=400, detail="Farmer consent is required before registration")

    farmer = Farmer(
        farmer_id=str(uuid.uuid4()),
        phone_number=normalized_phone,
        name=payload.name,
        preferred_language=payload.preferred_language,
        state=payload.state,
        district=payload.district,
        consent_given_at=utc_now(),
        registration_channel=payload.registration_channel,
        status="active",
    )
    db.add(farmer)
    db.commit()
    db.refresh(farmer)

    log_audit_event(
        db,
        str(uuid.uuid4()),
        AuditEventType.FARMER_REGISTERED,
        farmer_id=farmer.farmer_id,
        details=f"Farmer registered via {payload.registration_channel}",
        actor_type="farmer",
        actor_id=farmer.farmer_id,
        actor_label=farmer.name or farmer.phone_number,
    )

    return farmer


@router.post("/session", response_model=FarmerSessionResponse)
def create_farmer_session(payload: FarmerSessionRequest, db: Session = Depends(get_db)) -> FarmerSessionResponse:
    if payload.origin_channel not in {"sms", "ussd"}:
        raise HTTPException(status_code=400, detail="Session origin must be sms or ussd")

    normalized_phone = normalize_phone_number(payload.phone_number)
    farmer = db.query(Farmer).filter(Farmer.phone_number == normalized_phone).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")
    if farmer.status != "active":
        raise HTTPException(status_code=403, detail="Farmer account is not active")

    token = create_farmer_session_token(farmer.farmer_id, farmer.phone_number)
    return FarmerSessionResponse(farmer_id=farmer.farmer_id, phone_number=farmer.phone_number, session_token=token)


@router.get("/{farmer_id}", response_model=FarmerRead)
def get_farmer(farmer_id: str, session_token: str | None = None, db: Session = Depends(get_db)) -> Farmer:
    farmer = db.query(Farmer).filter(Farmer.farmer_id == farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")
    if _is_owner_session(session_token, farmer):
        return farmer
    return _mask_farmer(farmer, anonymized=farmer.status != "active")


@router.get("/by-phone/{phone_number}", response_model=FarmerRead)
def get_farmer_by_phone_number(phone_number: str, session_token: str | None = None, db: Session = Depends(get_db)) -> Farmer:
    """Look up farmer by phone number for SMS-based auth."""
    normalized_phone = normalize_phone_number(phone_number)
    farmer = db.query(Farmer).filter(Farmer.phone_number == normalized_phone).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")
    if farmer.status != "active":
        raise HTTPException(status_code=403, detail="Farmer account is not active")
    # Never expose a phone number through a lookup endpoint without proving
    # ownership.  This endpoint is commonly called with untrusted user input.
    return farmer if _is_owner_session(session_token, farmer) else _mask_farmer(farmer, include_name=True)


def _is_admin_bearer(authorization: str | None) -> bool:
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    try:
        payload = verify_institutional_access_token(authorization.split(" ", 1)[1])
    except HTTPException:
        return False
    return payload.get("role") == "admin"


@router.delete("/{farmer_id}")
def delete_farmer_data(
    farmer_id: str,
    session_token: str | None = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """DPDP-style deletion request fulfillment via anonymization.

    Callable by the farmer themselves (session token) or an admin institutional
    user -- never anonymously, since this destroys the farmer's identifying data.
    """
    farmer = db.query(Farmer).filter(Farmer.farmer_id == farmer_id).first()
    if not farmer:
        raise HTTPException(status_code=404, detail="Farmer not found")
    if not (_is_owner_session(session_token, farmer) or _is_admin_bearer(authorization)):
        raise HTTPException(status_code=403, detail="Not authorized to delete this farmer record")
    try:
        return anonymize_farmer_data(db, farmer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
