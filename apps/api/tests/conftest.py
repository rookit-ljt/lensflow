import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi.testclient import TestClient

from app.main import app


@contextmanager
def authenticated_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "email": f"test-{uuid.uuid4().hex}@example.com",
                "password": "correct-horse-battery-staple",
                "display_name": "测试创作者",
            },
        )
        assert response.status_code == 201, response.text
        yield client
