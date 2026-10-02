import json
import os
from datetime import datetime, timedelta, timezone

# env has to be set before the app is imported
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.security import sign_webhook


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def register(client, email, password="password123", name="Test User"):
    res = client.post("/auth/signup", json={"email": email, "full_name": name, "password": password})
    assert res.status_code == 201, res.text
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def user_headers(client):
    return register(client, "user@example.com")


@pytest.fixture()
def other_headers(client):
    return register(client, "other@example.com")


@pytest.fixture()
def admin_headers(client):
    return register(client, "admin@example.com")


@pytest.fixture()
def seeded(client, admin_headers):
    # one centre offering one test at 499.00
    centre = client.post(
        "/centres", json={"name": "Apollo Diagnostics", "location": "Ranchi"}, headers=admin_headers
    ).json()
    offering = client.post(
        f"/centres/{centre['id']}/tests",
        json={"name": "CBC", "description": "Complete blood count", "price": "499.00"},
        headers=admin_headers,
    ).json()
    return {"centre_id": centre["id"], "test_id": offering["test"]["id"]}


def future_time(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture()
def booking(client, user_headers, seeded):
    res = client.post(
        "/bookings",
        json={**seeded, "appointment_at": future_time()},
        headers=user_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def send_webhook(client, payload, signature=None):
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature if signature is not None else sign_webhook(body),
    }
    return client.post("/payments/webhook/", content=body, headers=headers)
