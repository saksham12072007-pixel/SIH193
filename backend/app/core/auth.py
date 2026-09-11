"""Authentication and authorization utilities for farmers and institutional users."""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()


def create_farmer_session_token(farmer_id: str, phone_number: str, expires_in_minutes: int = 1440) -> str:
    """Create a JWT session token for a farmer (valid for 24 hours by default)."""
    payload = {
        "farmer_id": farmer_id,
        "phone_number": phone_number,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_farmer_session_token(token: str) -> dict:
    """Verify a farmer session token and return the payload."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt_hex, digest_hex = password_hash.split(":", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return hmac.compare_digest(expected, computed)


def create_institutional_access_token(user_id: str, role: str, assigned_geography: dict | None, expires_in_minutes: int = 60) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "assigned_geography": assigned_geography or {},
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_institutional_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        if "sub" not in payload:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
