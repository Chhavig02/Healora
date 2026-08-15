"""Integration tests against the real /api/chat HTTP endpoint.

Covers Phase 14 items #6 (Gemini unavailable -> deterministic fallback),
#7 (Gemini failing -> graceful fallback), #13 (existing frontend chat still
works, i.e. the answers=[[name,bool]] contract), and #14 (API response
format stays valid).

No test in this file makes a real network call to Gemini — GEMINI_API_KEY
is unset in the test environment (see conftest.py), so every request here
already exercises the local deterministic fallback path by default. A
couple of tests monkeypatch gemini_client to simulate "key present but the
call fails", without hitting the network.
"""

import gemini_client


def test_chat_emergency_short_circuits_before_anything_else(client):
    resp = client.post(
        "/api/chat", json={"message": "I have severe chest pain", "answers": []}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


def test_chat_greeting_with_no_answers(client):
    resp = client.post("/api/chat", json={"message": "hello", "answers": []})
    data = resp.get_json()
    assert data["next_step"]["type"] == "waiting"


def test_chat_extracts_symptom_and_asks_question(client):
    resp = client.post(
        "/api/chat", json={"message": "my joints hurt", "answers": []}
    )
    data = resp.get_json()
    assert ["joint_pain", True] in data["answers"]
    assert data["next_step"]["type"] == "question"
    assert data["emergency"] is False


def test_chat_reaches_result_with_enough_symptoms(client):
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["joint_pain", True],
        ["pain_behind_the_eyes", True],
    ]
    resp = client.post("/api/chat", json={"message": "", "answers": answers})
    data = resp.get_json()
    step = data["next_step"]
    assert step["type"] == "result"
    assert step["disease"]
    assert step["description"]
    assert "possible_conditions" in step
    assert "disclaimer" in step
    assert "confidence" not in step  # no numeric probability exposed


def test_chat_unrecognized_symptoms_asks_for_more_detail(client):
    resp = client.post(
        "/api/chat", json={"message": "qwerty zzz nonsense", "answers": []}
    )
    data = resp.get_json()
    assert data["next_step"]["type"] == "waiting"


def test_chat_gemini_unavailable_still_returns_valid_response(client):
    # GEMINI_API_KEY is unset in the test env — this is the default fallback
    # path, exercised implicitly by every test above too.
    assert gemini_client.is_available() is False
    resp = client.post("/api/chat", json={"message": "headache", "answers": []})
    assert resp.status_code == 200


def test_chat_gemini_failing_falls_back_gracefully(client, monkeypatch):
    # Simulate "key present but every call fails" without any network call.
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)
    monkeypatch.setattr(
        gemini_client, "generate_text", lambda prompt, fallback=None, **kw: fallback
    )
    monkeypatch.setattr(
        gemini_client, "generate_json", lambda prompt, fallback=None, **kw: fallback
    )

    resp = client.post(
        "/api/chat", json={"message": "my joints hurt", "answers": []}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # still got a usable question even though Gemini "failed" every call
    assert data["next_step"]["type"] in ("question", "result")


def test_symptoms_endpoint(client):
    resp = client.get("/api/symptoms")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data["symptoms"], list)
    assert len(data["symptoms"]) == 131


def test_tips_endpoint_returns_a_tip(client):
    resp = client.get("/api/tips")
    assert resp.status_code == 200
    assert resp.get_json()["tip"]


def test_diseases_list_endpoint(client):
    resp = client.get("/api/diseases?page_size=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 41
    assert len(data["diseases"]) == 5


def test_diseases_search_endpoint(client):
    resp = client.get("/api/diseases?q=dengue")
    data = resp.get_json()
    assert data["total"] == 1
    assert data["diseases"][0]["name"] == "Dengue"


def test_disease_detail_endpoint(client):
    listing = client.get("/api/diseases?q=dengue").get_json()
    disease_id = listing["diseases"][0]["id"]
    resp = client.get(f"/api/diseases/{disease_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Dengue"
    assert isinstance(data["symptoms"], list)
    assert len(data["symptoms"]) > 0


def test_disease_detail_404_for_unknown_id(client):
    resp = client.get("/api/diseases/999999")
    assert resp.status_code == 404
