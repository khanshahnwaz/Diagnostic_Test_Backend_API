from tests.conftest import register


def test_signup_and_login(client):
    headers = register(client, "a@example.com")
    res = client.get("/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["email"] == "a@example.com"
    assert res.json()["is_admin"] is False


def test_signup_duplicate_email(client):
    register(client, "a@example.com")
    res = client.post(
        "/auth/signup", json={"email": "A@example.com", "full_name": "x", "password": "password123"}
    )
    assert res.status_code == 409


def test_signup_validation(client):
    bad_email = client.post("/auth/signup", json={"email": "nope", "full_name": "x", "password": "password123"})
    short_pw = client.post("/auth/signup", json={"email": "a@example.com", "full_name": "x", "password": "short"})
    blank_name = client.post(
        "/auth/signup", json={"email": "a@example.com", "full_name": "   ", "password": "password123"}
    )
    assert bad_email.status_code == 422
    assert short_pw.status_code == 422
    assert blank_name.status_code == 422


def test_login_wrong_password(client):
    register(client, "a@example.com")
    res = client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpass1"})
    assert res.status_code == 401


def test_login_unknown_user(client):
    res = client.post("/auth/login", json={"email": "ghost@example.com", "password": "password123"})
    assert res.status_code == 401


def test_me_requires_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_admin_email_gets_admin_flag(client):
    headers = register(client, "admin@example.com")
    assert client.get("/auth/me", headers=headers).json()["is_admin"] is True
