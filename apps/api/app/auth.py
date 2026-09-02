import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .database import get_session
from .db_models import AuthSession, User

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 64

DatabaseSession = Annotated[Session, Depends(get_session)]


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_BYTES,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
            maxmem=64 * 1024 * 1024,
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(derived.hex(), expected_hex)


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_auth_session(session: Session, user: User, settings: Settings) -> str:
    now = datetime.now(UTC)
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    raw_token = secrets.token_urlsafe(48)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=session_token_hash(raw_token),
            expires_at=now + timedelta(days=settings.auth_session_days),
            last_seen_at=now,
        )
    )
    return raw_token


def set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def require_user(request: Request, session: DatabaseSession) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        if not settings.auth_required:
            return get_or_create_local_user(session)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    auth_session = session.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == session_token_hash(token))
        .options(selectinload(AuthSession.user))
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if expires_at <= now or not auth_session.user.is_active:
        session.delete(auth_session)
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效")
    last_seen_at = auth_session.last_seen_at
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=UTC)
    if now - last_seen_at >= timedelta(minutes=5):
        auth_session.last_seen_at = now
        session.commit()
    return auth_session.user


def get_or_create_local_user(session: Session) -> User:
    """Return the stable local owner used by the single-user distribution."""
    local_email = "local@localhost.invalid"
    user = session.scalar(select(User).where(User.email == local_email))
    if user is None:
        user = User(
            email=local_email,
            display_name="本地用户",
            password_hash="local-only",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


CurrentUser = Annotated[User, Depends(require_user)]
