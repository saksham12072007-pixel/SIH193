import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.models import FieldInspection, InstitutionalUser, Plot
from app.routers.institutional_auth import get_current_institutional_user
from app.schemas.field_inspection import FieldInspectionCreate, FieldInspectionRead

router = APIRouter(prefix="/institutional/inspections", tags=["institutional-inspections"])


def _officer_display_name(email: str) -> str:
    local_part = email.split("@")[0]
    return " ".join(part.capitalize() for part in local_part.replace(".", " ").replace("_", " ").split()) or email


def _read(inspection: FieldInspection, officer_email: str) -> FieldInspectionRead:
    plot = inspection.plot
    return FieldInspectionRead(
        inspection_id=inspection.inspection_id,
        plot_id=inspection.plot_id,
        farmer_name=plot.farmer.name or "Unnamed farmer",
        district=plot.farmer.district,
        crop=plot.crop_type,
        officer_name=_officer_display_name(officer_email),
        issue_type=inspection.issue_type,
        observed_condition=inspection.observed_condition,
        severity=inspection.severity,
        farmer_comments=inspection.farmer_comments,
        officer_comments=inspection.officer_comments,
        gps_lat=float(inspection.gps_lat) if inspection.gps_lat is not None else None,
        gps_lng=float(inspection.gps_lng) if inspection.gps_lng is not None else None,
        gps_accuracy_m=float(inspection.gps_accuracy_m) if inspection.gps_accuracy_m is not None else None,
        photos=inspection.photos or [],
        recommended_action=inspection.recommended_action,
        status=inspection.status,
        inspection_date=inspection.inspection_date,
    )


def _allowed(user: InstitutionalUser, plot: Plot) -> bool:
    if user.role == "admin":
        return True
    geography = user.assigned_geography or {}
    farmer = plot.farmer
    return (
        (not geography.get("states") or farmer.state in geography["states"])
        and (not geography.get("districts") or farmer.district in geography["districts"])
    )


@router.get("", response_model=list[FieldInspectionRead])
def list_inspections(
    plot_id: str | None = None,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> list[FieldInspectionRead]:
    query = (
        db.query(FieldInspection)
        .join(FieldInspection.plot)
        .options(joinedload(FieldInspection.plot).joinedload(Plot.farmer))
    )
    if plot_id:
        query = query.filter(FieldInspection.plot_id == plot_id)
    officers = {u.user_id: u.email for u in db.query(InstitutionalUser).all()}
    rows = query.order_by(FieldInspection.inspection_date.desc()).all()
    return [
        _read(inspection, officers.get(inspection.officer_user_id, "unknown@officer"))
        for inspection in rows
        if _allowed(current_user, inspection.plot)
    ]


@router.post("", response_model=FieldInspectionRead, status_code=201)
def create_inspection(
    payload: FieldInspectionCreate,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> FieldInspectionRead:
    plot = db.query(Plot).filter(Plot.plot_id == payload.plot_id).first()
    if plot is None:
        raise HTTPException(status_code=404, detail="Plot not found")
    if not _allowed(current_user, plot):
        raise HTTPException(status_code=403, detail="Plot is outside assigned geography")

    inspection = FieldInspection(
        inspection_id=str(uuid.uuid4()),
        plot_id=payload.plot_id,
        officer_user_id=current_user.user_id,
        issue_type=payload.issue_type,
        observed_condition=payload.observed_condition,
        severity=payload.severity,
        farmer_comments=payload.farmer_comments,
        officer_comments=payload.officer_comments,
        gps_lat=payload.gps_lat,
        gps_lng=payload.gps_lng,
        gps_accuracy_m=payload.gps_accuracy_m,
        photos=payload.photos or None,
        recommended_action=payload.recommended_action,
        status=payload.status,
    )
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return _read(inspection, current_user.email)
