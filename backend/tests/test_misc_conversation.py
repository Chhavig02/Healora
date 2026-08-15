"""Remaining spec section 12 coverage not covered elsewhere: empty/unclear
messages (I), long natural-language descriptions (J), common spelling
variations (K), and confirmation that Gemini can never override emergency
detection (part of section 9 / F)."""

import gemini_client


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


# I. Empty / unclear messages ------------------------------------------------


def test_empty_message_with_no_prior_state_does_not_crash(client):
    data = _post(client, "", [])
    assert data["next_step"]["type"] == "waiting"


def test_whitespace_only_message(client):
    data = _post(client, "   ", [])
    assert data["next_step"]["type"] == "waiting"


def test_gibberish_message_gets_clarification_not_a_crash(client):
    data = _post(client, "asdkjhasdkjh 12312 !!!", [])
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]


# J. Long natural-language descriptions --------------------------------------


def test_long_rambling_symptom_description_still_extracts_symptoms(client):
    message = (
        "So basically it started a few days ago, I was fine in the morning "
        "but by evening I noticed my head was pounding, like a really bad "
        "headache, and then last night I also started running a temperature, "
        "felt really hot and just generally awful, and my joints have been "
        "aching too, it's honestly been a rough few days"
    )
    data = _post(client, message, [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert {"headache", "high_fever", "joint_pain"} <= names


# K. Common spelling variations -----------------------------------------------


def test_typo_haedache_still_matches_headache(app_ctx, seeded):
    import symptom_engine

    assert "headache" in symptom_engine.extract_symptoms_keyword("I have a haedache")


def test_typo_via_chat_endpoint(client):
    data = _post(client, "I have a bad haedache today", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert "headache" in names


# Emergency always wins, even if Gemini is "available" -----------------------


def test_emergency_overrides_even_when_gemini_is_available(client, monkeypatch):
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)
    monkeypatch.setattr(
        gemini_client,
        "generate_text",
        lambda prompt, fallback=None, **kw: "This is fine, no emergency here.",
    )
    monkeypatch.setattr(
        gemini_client,
        "generate_json",
        lambda prompt, fallback=None, **kw: {"intent": "CASUAL"},
    )
    data = _post(client, "I have severe chest pain and can't breathe", [])
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"
    assert "emergency" in data["message"].lower() or "911" in data["message"]
