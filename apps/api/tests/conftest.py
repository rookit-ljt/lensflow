import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.db_models import User
from app.main import app


@contextmanager
def authenticated_client(is_admin: bool = False) -> Iterator[TestClient]:
    with TestClient(app) as client:
        email = f"test-{uuid.uuid4().hex}@example.com"
        response = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "correct-horse-battery-staple",
                "display_name": "测试创作者",
            },
        )
        assert response.status_code == 201, response.text
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.email == email))
            if user and user.is_admin != is_admin:
                user.is_admin = is_admin
                session.commit()
        yield client


@contextmanager
def admin_client() -> Iterator[TestClient]:
    with authenticated_client(is_admin=True) as client:
        yield client
