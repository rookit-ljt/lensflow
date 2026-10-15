from __future__ import annotations

import sys

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..auth import (
    CurrentUser,
    clear_auth_cookie,
    create_auth_session,
    hash_password,
    normalize_email,
    session_token_hash,
    set_auth_cookie,
    verify_password,
)
from ..config import get_settings
from ..credits_service import get_or_create_wallet
from ..db_models import AuthSession, Project, User, UserIdentity
from ..deps import DatabaseSession
from ..google_identity import GoogleIdentityError
from ..google_identity import verify_google_id_token as default_verify_google_id_token
from ..schemas import AuthGoogleCredential, AuthLogin, AuthRegister, UserRead

settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _verify_google_token(credential: str, client_id: str):
    main_mod = sys.modules.get("app.main")
    verifier = getattr(main_mod, "verify_google_id_token", default_verify_google_id_token) if main_mod else default_verify_google_id_token
    return verifier(credential, client_id)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: AuthRegister,
    response: Response,
    session: DatabaseSession,
) -> User:
    email = normalize_email(payload.email)
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="该邮箱已经注册")
    is_first_user = int(session.scalar(select(func.count(User.id))) or 0) == 0
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        is_admin=is_first_user,
    )
    session.add(user)
    try:
        session.flush()
        if is_first_user:
            session.execute(
                update(Project).where(Project.user_id.is_(None)).values(user_id=user.id)
            )
        get_or_create_wallet(session, user)
        token = create_auth_session(session, user, settings)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已经注册") from exc
    session.refresh(user)
    set_auth_cookie(response, token, settings)
    return user


@router.post("/login", response_model=UserRead)
def login_user(payload: AuthLogin, response: Response, session: DatabaseSession) -> User:
    user = session.scalar(select(User).where(User.email == normalize_email(payload.email)))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    token = create_auth_session(session, user, settings)
    session.commit()
    set_auth_cookie(response, token, settings)
    return user


@router.post("/google", response_model=UserRead)
def login_with_google(
    payload: AuthGoogleCredential,
    response: Response,
    session: DatabaseSession,
) -> User:
    if not settings.google_client_id.strip():
        raise HTTPException(status_code=503, detail="Google 登录尚未配置")
    try:
        google_identity = _verify_google_token(
            payload.credential,
            settings.google_client_id,
        )
    except GoogleIdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    identity = session.scalar(
        select(UserIdentity)
        .where(
            UserIdentity.provider == "google",
            UserIdentity.provider_subject == google_identity.subject,
        )
        .options(selectinload(UserIdentity.user))
    )
    if identity is not None:
        user = identity.user
        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被停用")
        identity.provider_email = google_identity.email
        identity.profile_name = google_identity.name
        identity.avatar_url = google_identity.picture
    else:
        existing_user = session.scalar(select(User).where(User.email == google_identity.email))
        if existing_user is not None:
            raise HTTPException(
                status_code=409,
                detail="该邮箱已有密码账号，请继续使用邮箱密码登录",
            )
        is_first_user = int(session.scalar(select(func.count(User.id))) or 0) == 0
        display_name = (google_identity.name or google_identity.email.split("@", 1)[0])[:80]
        user = User(
            email=google_identity.email,
            display_name=display_name,
            password_hash="external$google",
        )
        session.add(user)
        session.flush()
        session.add(
            UserIdentity(
                user_id=user.id,
                provider="google",
                provider_subject=google_identity.subject,
                provider_email=google_identity.email,
                profile_name=google_identity.name,
                avatar_url=google_identity.picture,
            )
        )
        if is_first_user:
            session.execute(
                update(Project).where(Project.user_id.is_(None)).values(user_id=user.id)
            )

    try:
        token = create_auth_session(session, user, settings)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Google 账号关联冲突，请重试") from exc
    session.refresh(user)
    set_auth_cookie(response, token, settings)
    return user


@router.get("/me", response_model=UserRead)
def get_current_user(user: CurrentUser) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(request: Request, response: Response, session: DatabaseSession) -> Response:
    token = request.cookies.get(settings.auth_cookie_name)
    if token:
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == session_token_hash(token))
        )
        if auth_session is not None:
            session.delete(auth_session)
            session.commit()
    clear_auth_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
