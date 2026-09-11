import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import AlertRule, InstitutionalUser
from app.routers.institutional_auth import get_current_institutional_user
from app.schemas.alert_rule import AlertRuleCreate, AlertRuleRead, AlertRuleUpdate

router = APIRouter(prefix="/institutional/alert-rules", tags=["institutional-alert-rules"])


def _allowed(user: InstitutionalUser, rule: AlertRule) -> bool:
    if user.role == "admin":
        return True
    if rule.district is None:
        return True
    geography = user.assigned_geography or {}
    districts = geography.get("districts")
    return not districts or rule.district in districts


@router.get("", response_model=list[AlertRuleRead])
def list_alert_rules(
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> list[AlertRule]:
    rules = db.query(AlertRule).order_by(AlertRule.created_at.desc()).all()
    return [rule for rule in rules if _allowed(current_user, rule)]


@router.post("", response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
def create_alert_rule(
    payload: AlertRuleCreate,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> AlertRule:
    if payload.district and current_user.role != "admin":
        geography = current_user.assigned_geography or {}
        districts = geography.get("districts")
        if districts and payload.district not in districts:
            raise HTTPException(status_code=403, detail="Cannot create a rule outside your assigned geography")

    rule = AlertRule(
        rule_id=str(uuid.uuid4()),
        name=payload.name,
        metric=payload.metric,
        operator=payload.operator,
        value=payload.value,
        severity=payload.severity,
        district=payload.district,
        crop=payload.crop,
        enabled=payload.enabled,
        created_by=current_user.user_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=AlertRuleRead)
def update_alert_rule(
    rule_id: str,
    payload: AlertRuleUpdate,
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
    db: Session = Depends(get_db),
) -> AlertRule:
    rule = db.query(AlertRule).filter(AlertRule.rule_id == rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    if not _allowed(current_user, rule):
        raise HTTPException(status_code=403, detail="Alert rule is outside assigned geography")
    rule.enabled = payload.enabled
    db.commit()
    db.refresh(rule)
    return rule
