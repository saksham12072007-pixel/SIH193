import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.auth import (
    create_institutional_access_token,
    hash_password,
    verify_institutional_access_token,
    verify_password,
)
from app.db.database import get_db
from app.models import InstitutionalUser
from app.utils.time import utc_now

router = APIRouter(prefix="/institutional", tags=["institutional-auth"])
# auto_error=False so a missing Authorization header produces a proper 401
# (with WWW-Authenticate) instead of FastAPI's legacy 403 default.
bearer_scheme = HTTPBearer(auto_error=False)

# Mirrors the frontend's UserRole union (src/types/index.ts), lowercased.
InstitutionalRole = Literal["admin", "district_officer", "field_officer", "analyst"]
SELF_SERVE_ROLE: InstitutionalRole = "field_officer"


class InstitutionalSignupRequest(BaseModel):
    """Public self-signup. Role is never taken from the caller -- see SELF_SERVE_ROLE --
    to close a privilege-escalation path where any caller could request role=admin."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    assigned_geography: dict | None = None


class InstitutionalUserCreateRequest(BaseModel):
    """Admin-only user provisioning, where an elevated role is legitimate."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    role: InstitutionalRole = SELF_SERVE_ROLE
    assigned_geography: dict | None = None


class InstitutionalUserUpdateRequest(BaseModel):
    """Admin-only edit of an existing user's role/geography (e.g. promoting a
    self-signed-up field_officer, or scoping their assigned districts)."""

    role: InstitutionalRole | None = None
    assigned_geography: dict | None = None


class InstitutionalLoginRequest(BaseModel):
    email: EmailStr
    password: str


def get_current_institutional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> InstitutionalUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_institutional_access_token(credentials.credentials)
    user = db.query(InstitutionalUser).filter(InstitutionalUser.user_id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Institutional user not found")
    return user


def require_admin(
    current_user: InstitutionalUser = Depends(get_current_institutional_user),
) -> InstitutionalUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user


def _create_user(db: Session, email: str, password: str, role: str, assigned_geography: dict | None) -> InstitutionalUser:
    existing = db.query(InstitutionalUser).filter(InstitutionalUser.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = InstitutionalUser(
        user_id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        role=role,
        assigned_geography=assigned_geography or {},
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup_institutional_user(payload: InstitutionalSignupRequest, db: Session = Depends(get_db)) -> dict:
    user = _create_user(db, payload.email, payload.password, SELF_SERVE_ROLE, payload.assigned_geography)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "assigned_geography": user.assigned_geography,
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_institutional_user(
    payload: InstitutionalUserCreateRequest,
    current_user: InstitutionalUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Admin-only provisioning for elevated roles (admin/district_officer/analyst)."""
    user = _create_user(db, payload.email, payload.password, payload.role, payload.assigned_geography)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "assigned_geography": user.assigned_geography,
    }


@router.patch("/users/{user_id}")
def update_institutional_user(
    user_id: str,
    payload: InstitutionalUserUpdateRequest,
    current_user: InstitutionalUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Admin-only edit of an existing user's role/geography."""
    user = db.query(InstitutionalUser).filter(InstitutionalUser.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Institutional user not found")
    if payload.role is not None:
        user.role = payload.role
    if payload.assigned_geography is not None:
        user.assigned_geography = payload.assigned_geography
    db.commit()
    db.refresh(user)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "assigned_geography": user.assigned_geography,
    }


@router.get("/users")
def list_institutional_users(
    current_user: InstitutionalUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    users = db.query(InstitutionalUser).order_by(InstitutionalUser.created_at.desc()).all()
    return [
        {
            "user_id": user.user_id,
            "email": user.email,
            "role": user.role,
            "assigned_geography": user.assigned_geography,
            "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }
        for user in users
    ]


@router.post("/login")
def login_institutional_user(payload: InstitutionalLoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(InstitutionalUser).filter(InstitutionalUser.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login_at = utc_now()
    db.commit()

    token = create_institutional_access_token(
        user_id=user.user_id,
        role=user.role,
        assigned_geography=user.assigned_geography,
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def institutional_me(current_user: InstitutionalUser = Depends(get_current_institutional_user)) -> dict:
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "role": current_user.role,
        "assigned_geography": current_user.assigned_geography,
    }
