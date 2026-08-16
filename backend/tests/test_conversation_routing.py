"""Regression suite for the "Healora treats every message as a symptom"
bug — casual/affectionate small talk and pregnancy-related messages must
never fall through to symptom clarification or the disease engine, and a
real symptom must still win when one is actually present. Covers the full
test matrix from the bug report, end to end through the real /api/chat
endpoint (deterministic fallback path, same as every other test here).
"""

import intent_classifier as ic


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


# --- Intent classification matrix (unit-level, exact expected bucket) -----


def test_intent_matrix(app_ctx, seeded):
    import symptom_engine
    import conversation_state as cs

    vocab = symptom_engine.get_all_symptom_names()
    cases = [
        ("hi", "GREETING"),
        ("hello", "GREETING"),
        ("thanks", "CASUAL"),
        ("thank you", "CASUAL"),
        ("i love you", "CASUAL"),
        ("i want to marry you", "CASUAL"),
        ("pregnent", "PREGNANCY"),
        ("pregnant", "PREGNANCY"),
        ("i think i'm pregnant", "PREGNANCY"),
        ("pregnancy symptoms", "PREGNANCY"),
        ("what is pregnancy?", "PREGNANCY"),
        ("i have a headache", "NEW_SYMPTOM"),
        ("i have fever and cough", "NEW_SYMPTOM"),
        ("start over", "RESTART"),
    ]
    for message, expected in cases:
        local = symptom_engine.extract_symptoms_keyword(message.lower())
        state = cs.new_state()
        got = ic.classify(message, state, vocab, local)
        assert got == expected, f"{message!r} classified as {got!r}, expected {expected!r}"


def test_baby_is_not_a_symptom(app_ctx, seeded):
    import symptom_engine

    # "baby" is genuinely ambiguous — it must NOT resolve to any symptom,
    # and the classifier must not force it into NEW_SYMPTOM/UNCLEAR-as-symptom.
    assert symptom_engine.extract_symptoms_keyword("baby") == []


# --- End-to-end /api/chat behavior -----------------------------------------


def test_love_you_gets_a_warm_reply_not_symptom_clarification(client):
    data = _post(client, "I love you", [])
    assert data["answers"] == []
    assert "describe what you're feeling" not in data["message"].lower()
    assert data["next_step"]["type"] == "waiting"


def test_marry_you_gets_a_warm_reply_not_symptom_clarification(client):
    data = _post(client, "I want to marry you", [])
    assert data["answers"] == []
    assert "describe what you're feeling" not in data["message"].lower()


def test_baby_gets_neutral_clarification_not_symptom_framing(client):
    data = _post(client, "baby", [])
    assert data["answers"] == []
    # must not be the symptom-shaped fallback
    assert "describe what you're feeling" not in data["message"].lower()
    assert data["message"]


def test_pregnent_typo_is_understood_as_pregnancy(client):
    data = _post(client, "pregnent", [])
    assert data["answers"] == []
    assert "describe what you're feeling" not in data["message"].lower()
    assert "pregnan" in data["message"].lower() or "ob-gyn" in data["message"].lower() or "doctor" in data["message"].lower()


def test_i_think_im_pregnant_gets_pregnancy_conversation(client):
    data = _post(client, "I think I'm pregnant", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] == "waiting"
    assert "describe what you're feeling" not in data["message"].lower()


def test_pregnancy_with_real_symptom_still_reports_the_symptom(client):
    # A real symptom in the same message must still win — pregnancy talk
    # doesn't suppress genuine symptom reporting.
    data = _post(client, "I'm pregnant and have severe abdominal pain", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert "abdominal_pain" in names


def test_symptom_report_still_works_normally(client):
    data = _post(client, "I have a headache", [])
    assert ["headache", True] in data["answers"]
    assert data["next_step"]["type"] == "question"


def test_typo_stomache_pain_is_understood(client):
    data = _post(client, "I have stomache pain", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert "stomach_pain" in names


def test_thanks_during_pending_symptom_question_is_not_a_symptom_answer(client):
    data = _post(client, "I have a headache", [])
    answers, state = data["answers"], data["state"]
    for value in ("3 days", "6", "gradually"):
        data = _post(client, value, answers, state)
        answers, state = data["answers"], data["state"]
    # now at a yes/no symptom-clarification question
    assert state.get("pending_symptom_question")
    pending = state["pending_symptom_question"]

    data = _post(client, "thanks", answers, state)
    # the pending question must not have been silently answered False/True
    assert not any(a == [pending, False] for a in data["answers"] if a[0] == pending and a not in answers)
    # conversation must still be able to continue answering it afterward
    assert data["state"].get("pending_symptom_question") == pending


def test_medication_question_after_assessment_still_contextual(client):
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["chills", True],
        ["joint_pain", True],
    ]
    state = {"chief_complaint": "high_fever", "history_slots_asked": ["duration", "severity", "onset"]}
    data = _post(client, "", answers, state)
    assert data["next_step"]["type"] == "result"
    answers, state = data["answers"], data["state"]

    data = _post(client, "medicines?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert "don't have verified medication" in data["message"]


def test_emergency_still_overrides_everything(client):
    data = _post(client, "severe chest pain and difficulty breathing", [])
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


def test_greeting_with_extra_content_does_not_force_assessment_onboarding(client):
    # "hi baby" contains a greeting word but is not *just* a greeting — it
    # must not trigger the "let's perform a health assessment" onboarding
    # framing, and "baby" must not be read as a symptom either.
    data = _post(client, "hi baby", [])
    assert data["answers"] == []
    assert "describe your symptoms" not in data["message"].lower()
    assert "describe what you're feeling" not in data["message"].lower()


def test_pure_greeting_still_gets_the_onboarding_nudge(client):
    data = _post(client, "hi", [])
    assert "describe your symptoms" in data["message"].lower()
