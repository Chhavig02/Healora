"""Covers Phase 14 item #11 — existing authentication still works after the
disease-knowledge-base changes (auth.py/models.py User table untouched)."""


def test_signup_and_login(client, unique_email):
    resp = client.post(
        "/api/auth/signup",
        json={"name": "Alice", "email": unique_email, "password": "password123"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["token"]
    assert data["user"]["email"] == unique_email

    resp = client.post(
        "/api/auth/login", json={"email": unique_email, "password": "password123"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["token"]


def test_login_wrong_password_rejected(client, unique_email):
    client.post(
        "/api/auth/signup",
        json={"name": "Bob", "email": unique_email, "password": "password123"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": unique_email, "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_me_requires_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_with_valid_token(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert "email" in resp.get_json()


def test_duplicate_signup_rejected(client, unique_email):
    payload = {"name": "Carl", "email": unique_email, "password": "password123"}
    assert client.post("/api/auth/signup", json=payload).status_code == 201
    resp = client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 409
