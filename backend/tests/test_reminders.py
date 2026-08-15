"""Covers Phase 14 item #12 — existing reminders still work."""


def test_create_list_update_delete_reminder(client, auth_headers):
    resp = client.post(
        "/api/reminders",
        json={"medication_name": "Metformin", "dosage": "500mg", "time_of_day": "08:00"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    reminder_id = resp.get_json()["id"]

    resp = client.get("/api/reminders", headers=auth_headers)
    assert resp.status_code == 200
    assert any(r["id"] == reminder_id for r in resp.get_json()["reminders"])

    resp = client.put(
        f"/api/reminders/{reminder_id}", json={"active": False}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.get_json()["active"] is False

    resp = client.delete(f"/api/reminders/{reminder_id}", headers=auth_headers)
    assert resp.status_code == 204

    resp = client.get("/api/reminders", headers=auth_headers)
    assert not any(r["id"] == reminder_id for r in resp.get_json()["reminders"])


def test_reminders_require_auth(client):
    assert client.get("/api/reminders").status_code == 401


def test_reminders_are_scoped_per_user(client, auth_headers):
    client.post(
        "/api/reminders", json={"medication_name": "Aspirin"}, headers=auth_headers
    )
    signup = client.post(
        "/api/auth/signup",
        json={"name": "Other", "email": "other-scoped@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {signup.get_json()['token']}"}
    resp = client.get("/api/reminders", headers=other_headers)
    assert resp.get_json()["reminders"] == []
