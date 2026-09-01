import uuid

from fastapi.testclient import TestClient

from app.google_identity import GoogleIdentity
from app.main import app, settings


def _credentials(prefix: str) -> dict[str, str]:
    return {
        "email": f"{prefix}-{uuid.uuid4().hex}@example.com",
        "password": "correct-horse-battery-staple",
        "display_name": f"{prefix} 创作者",
    }


def test_authentication_session_lifecycle() -> None:
    credentials = _credentials("session")
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401

        registered = client.post("/api/auth/register", json=credentials)
        assert registered.status_code == 201
        assert registered.json()["email"] == credentials["email"]
        assert "httponly" in registered.headers["set-cookie"].lower()
        assert client.get("/api/auth/me").status_code == 200

        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"email": credentials["email"], "password": "wrong-password"},
        ).status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"email": credentials["email"], "password": credentials["password"]},
        ).status_code == 200
        assert client.get("/api/auth/me").status_code == 200


def test_projects_are_isolated_between_users() -> None:
    first_credentials = _credentials("owner")
    second_credentials = _credentials("other")
    with TestClient(app) as first_client, TestClient(app) as second_client:
        assert first_client.post("/api/auth/register", json=first_credentials).status_code == 201
        project = first_client.post("/api/projects", json={"name": "私有项目"})
        assert project.status_code == 201
        project_id = project.json()["id"]

        assert second_client.post("/api/auth/register", json=second_credentials).status_code == 201
        assert second_client.get("/api/projects").json() == []
        assert second_client.get(f"/api/projects/{project_id}").status_code == 404


def test_duplicate_email_is_rejected_case_insensitively() -> None:
    credentials = _credentials("duplicate")
    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=credentials).status_code == 201
        duplicate = {**credentials, "email": credentials["email"].upper()}
        assert client.post("/api/auth/register", json=duplicate).status_code == 409


def test_google_login_creates_and_reuses_account(monkeypatch) -> None:
    unique = uuid.uuid4().hex
    google_identity = GoogleIdentity(
        subject=f"google-{unique}",
        email=f"google-{unique}@example.com",
        name="Google 创作者",
        picture="https://example.com/avatar.png",
    )
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr("app.main.verify_google_id_token", lambda *_: google_identity)

    with TestClient(app) as client:
        first = client.post("/api/auth/google", json={"credential": "x" * 120})
        assert first.status_code == 200
        assert first.json()["email"] == google_identity.email
        assert first.json()["display_name"] == google_identity.name
        assert "httponly" in first.headers["set-cookie"].lower()
        user_id = first.json()["id"]

        assert client.post("/api/auth/logout").status_code == 204
        second = client.post("/api/auth/google", json={"credential": "y" * 120})
        assert second.status_code == 200
        assert second.json()["id"] == user_id


def test_google_login_does_not_silently_link_password_account(monkeypatch) -> None:
    credentials = _credentials("google-collision")
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(
        "app.main.verify_google_id_token",
        lambda *_: GoogleIdentity(
            subject=f"google-{uuid.uuid4().hex}",
            email=credentials["email"],
            name="同邮箱用户",
            picture=None,
        ),
    )

    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=credentials).status_code == 201
        assert client.post("/api/auth/logout").status_code == 204
        response = client.post("/api/auth/google", json={"credential": "z" * 120})
        assert response.status_code == 409
        assert "密码账号" in response.json()["detail"]
