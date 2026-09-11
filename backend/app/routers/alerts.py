import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.models import Advisory, Alert, Farmer, InstitutionalUser, Plot
from app.routers.institutional_auth import get_current_institutional_user
from app.schemas.alert import AlertRead, AlertStatusUpdate
from app.utils.time import utc_now

router = APIRouter(prefix="/institutional/alerts", tags=["institutional-alerts"])
VALID_STATUSES = {"GENERATED", "ACKNOWLEDGED", "ASSIGNED", "UNDER_INVESTIGATION", "RESOLVED", "CLOSED"}
SEVERITY = {"no_action": "SAFE", "monitor": "MODERATE", "irrigate_soon": "HIGH", "irrigate_now": "URGENT"}


def _allowed(user: InstitutionalUser, alert: Alert) -> bool:
    if user.role == "admin":
        return True
    geography = user.assigned_geography or {}
    farmer = alert.plot.farmer
    return (
        (not geography.get("states") or farmer.state in geography["states"])
        and (not geography.get("districts") or farmer.district in geography["districts"])
    )


def _sync_alerts(db: Session) -> None:
    advisories = (
        db.query(Advisory)
        .outerjoin(Alert, Alert.advisory_id == Advisory.advisory_id)
        .filter(Alert.alert_id.is_(None))
        .all()
    )
    for advisory in advisories:
        prediction = advisory.prediction
        advisory_class = advisory.advisory_class
        db.add(Alert(
            alert_id=str(uuid.uuid4()),
            advisory_id=advisory.advisory_id,
            plot_id=advisory.plot_id,
            severity=SEVERITY.get(advisory_class, "MODERATE"),
            title=f"{advisory_class.replace('_', ' ').title()} irrigation advisory",
            description=f"Backend advisory generated for plot {advisory.plot_id}.",
            trigger_metric="advisory_class",
            trigger_value=advisory_class,
            threshold="irrigate_now" if advisory_class == "irrigate_now" else None,
            status="GENERATED",
            created_at=advisory.created_at,
            updated_at=advisory.created_at,
        ))
    db.commit()


def _read(alert: Alert) -> AlertRead:
    return AlertRead(
        alert_id=alert.alert_id,
        plot_id=alert.plot_id,
        farmer_id=alert.plot.farmer_id,
        farmer_name=alert.plot.farmer.name or "Unnamed farmer",
        district=alert.plot.farmer.district,
        crop=alert.plot.crop_type,
        severity=alert.severity,
        title=alert.title,
        description=alert.description,
        trigger_metric=alert.trigger_metric,
        trigger_value=alert.trigger_value,
        threshold=alert.threshold,
        status=alert.status,
        assigned_user_id=alert.assigned_user_id,
        resolution_notes=alert.resolution_notes,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
        resolved_at=alert.resolved_at,
    )


@router.get("", response_model=list[AlertRead])
def list_alerts(
    state: str | None = None,
    district: str | None = None,
    crop: str | None = None,
    soil: str | None = None,
    status: str | None = Query(default=None),
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> list[AlertRead]:
    _sync_alerts(db)
    query = (
        db.query(Alert)
        .join(Alert.plot)
        .options(joinedload(Alert.plot).joinedload(Plot.farmer))
    )
    if state:
        query = query.filter(Alert.plot.has(Plot.farmer.has(Farmer.state == state)))
    if district:
        query = query.filter(Alert.plot.has(Plot.farmer.has(Farmer.district == district)))
    if crop:
        query = query.filter(Alert.plot.has(Plot.crop_type == crop))
    if soil:
        query = query.filter(Alert.plot.has(Plot.soil_texture == soil))
    if status:
        query = query.filter(Alert.status == status)
    rows = [alert for alert in query.order_by(Alert.created_at.desc()).all() if _allowed(current_user, alert)]
    return [_read(alert) for alert in rows]


@router.patch("/{alert_id}", response_model=AlertRead)
def update_alert(
    alert_id: str,
    payload: AlertStatusUpdate,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> AlertRead:
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid alert lifecycle status")
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _allowed(current_user, alert):
        raise HTTPException(status_code=403, detail="Alert is outside assigned geography")
    alert.status = payload.status
    alert.resolution_notes = payload.resolution_notes or alert.resolution_notes
    alert.assigned_user_id = payload.assigned_user_id or alert.assigned_user_id
    alert.resolved_at = utc_now() if payload.status in {"RESOLVED", "CLOSED"} else None
    alert.updated_at = utc_now()
    db.commit()
    db.refresh(alert)
    return _read(alert)
