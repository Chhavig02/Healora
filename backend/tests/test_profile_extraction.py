"""Profile-context extraction (age, sex, medications, allergies, existing
conditions volunteered by the user) — spec section 1 state fields, tested
both as pure functions and wired through /api/chat."""

import profile_extraction as pe


def test_extract_age():
    assert pe.extract_age("I'm 34 years old") == "34"
    assert pe.extract_age("28 yo") == "28"
    assert pe.extract_age("no age mentioned here") is None


def test_extract_sex():
    assert pe.extract_sex("I'm a woman") == "female"
    assert pe.extract_sex("I am male") == "male"
    assert pe.extract_sex("nothing relevant") is None


def test_extract_medication_mention():
    assert pe.extract_medication_mention("I'm taking metformin") == "metformin"
    assert pe.extract_medication_mention("no meds here") is None


def test_extract_allergy_mention():
    assert pe.extract_allergy_mention("I'm allergic to penicillin") == "penicillin"
    assert pe.extract_allergy_mention("nothing about allergies") is None


def test_extract_existing_condition():
    assert pe.extract_existing_condition("I have asthma") == "asthma"
    assert pe.extract_existing_condition("history of diabetes") == "diabetes"
    assert pe.extract_existing_condition("just a headache") is None


def test_apply_to_state_never_overwrites_existing_value():
    state = {"age": "40", "medications": [], "allergies": [], "existing_conditions": []}
    pe.apply_to_state(state, "I'm 25 years old")
    assert state["age"] == "40"


def test_apply_to_state_accumulates_without_duplicating():
    state = {"medications": [], "allergies": [], "existing_conditions": []}
    pe.apply_to_state(state, "I'm taking ibuprofen")
    pe.apply_to_state(state, "I'm taking ibuprofen")
    assert state["medications"] == ["ibuprofen"]


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def test_chat_remembers_volunteered_age_and_allergy(client):
    data = _post(client, "I'm 29 years old and allergic to penicillin", [])
    assert data["state"]["age"] == "29"
    assert "penicillin" in data["state"]["allergies"]


def test_chat_remembers_existing_condition_across_turns(client):
    data = _post(client, "I have asthma", [])
    assert "asthma" in data["state"]["existing_conditions"]
    data = _post(client, "I also have a headache", data["answers"], data["state"])
    # Still remembered on the next turn without being re-mentioned.
    assert "asthma" in data["state"]["existing_conditions"]
