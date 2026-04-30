from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
import uuid

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("unused-password-for-timing-balance")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def verify_password_with_dummy(plain_password: str, hashed_password: str | None) -> bool:
    if hashed_password is None:
        verify_password(plain_password, DUMMY_PASSWORD_HASH)
        return False
    return verify_password(plain_password, hashed_password)


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except InvalidTokenError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        return None


def generate_api_key() -> tuple[str, str]:
    key_prefix = f"tqk_live_{secrets.token_hex(4)}"
    secret = secrets.token_urlsafe(32)
    return f"{key_prefix}_{secret}", key_prefix


def hash_api_key(api_key: str) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac_sha256${digest}"
