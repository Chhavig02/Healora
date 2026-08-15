"""Negation handling — spec section 4 (English + Hinglish) and section 12.B.

Split between direct unit tests of negation.split_negated_symptoms (needs
an app context because it queries the Symptom table through
symptom_engine, but no HTTP round trip) and end-to-end /api/chat tests
that confirm the whole pipeline — extraction, negation, and `answers` —
comes out right together.
"""

import negation


def test_positive_conjunction_both_present(app_ctx, seeded):
    positive, neg = negation.split_negated_symptoms("I have fever and cough")
    assert "high_fever" in positive
    assert "cough" in positive
    assert neg == []


def test_but_no_negates_only_the_second_symptom(app_ctx, seeded):
    positive, neg = negation.split_negated_symptoms("I have fever but no cough")
    assert "high_fever" in positive
    assert "cough" in neg
    assert "cough" not in positive


def test_dont_have_lead_in(app_ctx, seeded):
    positive, neg = negation.split_negated_symptoms("I don't have chest pain")
    assert "chest_pain" in neg
    assert "chest_pain" not in positive


def test_hinglish_nahi_hai_trailing_negation(app_ctx, seeded):
    positive, neg = negation.split_negated_symptoms("Chest pain nahi hai")
    assert "chest_pain" in neg


def test_hinglish_khansi_nahi_hai(app_ctx, seeded):
    positive, neg = negation.split_negated_symptoms("khansi nahi hai")
    assert "cough" in neg
    assert "cough" not in positive


def test_hinglish_positive_statements_not_misread_as_negated(app_ctx, seeded):
    positive, neg = negation.split_negated_symptoms("mujhe bukhar hai")
    assert "high_fever" in positive
    assert neg == []

    positive2, neg2 = negation.split_negated_symptoms("sir dard ho raha hai")
    assert "headache" in positive2
    assert neg2 == []

    positive3, neg3 = negation.split_negated_symptoms("saans lene me dikkat hai")
    assert "breathlessness" in positive3
    assert neg3 == []


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def test_chat_records_positive_and_negative_symptom_from_one_message(client):
    data = _post(client, "I have fever but no cough", [])
    assert ["high_fever", True] in data["answers"]
    assert ["cough", False] in data["answers"]


def test_chat_hinglish_negation_end_to_end(client):
    data = _post(client, "mujhe bukhar hai, khansi nahi hai", [])
    assert ["high_fever", True] in data["answers"]
    assert ["cough", False] in data["answers"]


def test_chat_hinglish_headache_and_breathlessness(client):
    data = _post(client, "sir dard ho raha hai aur saans lene me dikkat hai", [])
    names_present = {a[0] for a in data["answers"] if a[1]}
    assert {"headache", "breathlessness"} <= names_present
