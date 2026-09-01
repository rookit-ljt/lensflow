from dataclasses import dataclass

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token


class GoogleIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str
    picture: str | None


def verify_google_id_token(credential: str, client_id: str) -> GoogleIdentity:
    if not client_id.strip():
        raise GoogleIdentityError("Google 登录尚未配置")
    try:
        claims = id_token.verify_oauth2_token(credential, Request(), client_id)
    except (GoogleAuthError, ValueError) as exc:
        raise GoogleIdentityError("Google 登录凭证无效或已过期") from exc

    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    if not subject or not email or claims.get("email_verified") is not True:
        raise GoogleIdentityError("Google 账号没有可验证的邮箱")

    name = str(claims.get("name") or "").strip()
    picture = str(claims.get("picture") or "").strip() or None
    return GoogleIdentity(subject=subject, email=email, name=name, picture=picture)
