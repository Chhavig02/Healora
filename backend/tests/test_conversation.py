"""Tests for the conversational chat layer added on top of the existing
single-turn symptom-matching pipeline: conversation state, intent
classification, history-taking, follow-up question answering, ambiguous-term
clarification, and cross-turn memory.

Runs against the local deterministic fallback (no GEMINI_API_KEY in the test
environment, same as every other test file) — every behavior here has to
hold up without a single real model call, since that's the always-available
floor the app is designed to guarantee.
"""


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


# 1. Greeting -----------------------------------------------------------


def test_greeting(client):
    data = _post(client, "hi", [])
    assert data["next_step"]["type"] == "waiting"


# 2. New symptom ----------------------------------------------------------


def test_new_symptom_starts_history_taking(client):
    data = _post(client, "I have a headache", [])
    assert ["headache", True] in data["answers"]
    assert data["next_step"]["type"] == "question"
    # First question after a fresh chief complaint is history-taking, not
    # a diagnosis dump — this is the core behavior change from the old
    # single-turn pipeline.
    assert data["next_step"]["answer_mode"] == "open"
    assert data["state"]["conversation_stage"] == "HISTORY_TAKING"
    assert data["state"]["chief_complaint"] == "headache"


def _establish_complaint_then_answer_history(
    client, complaint_message, values=("since yesterday", "7", "gradually")
):
    """Sends the initial complaint (which triggers the first history
    question), then answers each of the three history slots in turn,
    threading `answers`/`state` through every call exactly as a real
    client would."""
    data = _post(client, complaint_message, [])
    answers, state = data["answers"], data["state"]
    for value in values:
        data = _post(client, value, answers, state)
        answers, state = data["answers"], data["state"]
    return data, answers, state


# 3. Clarification (answering a yes/no symptom question) ------------------


def test_symptom_yes_no_question_then_free_text_no(client):
    data, answers, state = _establish_complaint_then_answer_history(client, "I have a headache")
    assert data["next_step"]["type"] == "question"
    assert data["next_step"]["answer_mode"] == "yes_no"
    raw = data["next_step"]["raw_symptom"]

    data = _post(client, "No", answers, state)
    assert [raw, False] in data["answers"]


# 4. Multiple symptoms ------------------------------------------------------


def test_multiple_symptoms_in_one_message(client):
    data = _post(client, "I have fever and headache", [])
    names = {a[0] for a in data["answers"]}
    assert {"high_fever", "headache"} <= names
    # Still goes through history-taking rather than an instant result card.
    assert data["next_step"]["type"] == "question"
    assert data["next_step"]["answer_mode"] == "open"


# 5. Ambiguous symptom --------------------------------------------------


def test_ambiguous_term_gets_clarifying_question_not_generic_error(client):
    data = _post(client, "I have cold", [])
    assert data["next_step"]["type"] == "waiting"
    assert "cold" in data["message"].lower()
    assert "runny nose" in data["message"].lower() or "chills" in data["message"].lower()
    # No symptom should have been guessed from "cold" alone.
    assert data["answers"] == []


# 6/7/8. Follow-up, medication, and condition questions after a result ----


def _reach_a_result(client):
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["joint_pain", True],
        ["pain_behind_the_eyes", True],
    ]
    state = {"chief_complaint": "high_fever", "history_slots_asked": ["duration", "severity", "onset"]}
    data = _post(client, "", answers, state)
    assert data["next_step"]["type"] == "result"
    return data["answers"], data["state"], data["next_step"]


def test_followup_is_this_serious(client):
    answers, state, _ = _reach_a_result(client)
    data = _post(client, "Is this serious?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    # Must not restart symptom extraction / lose the result context.
    assert data["state"]["current_primary_condition"] == state["current_primary_condition"]


def test_medication_question_never_names_a_drug(client):
    answers, state, _ = _reach_a_result(client)
    data = _post(client, "What medicine should I take?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert "don't have verified medication" in data["message"]


def test_condition_question_about_unrelated_disease(client):
    answers, state, _ = _reach_a_result(client)
    data = _post(client, "What is pneumonia?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert "lung" in data["message"].lower() or "air sac" in data["message"].lower()


# 9/10. New symptom after a result, and emergency detection --------------


def test_new_symptom_after_result_does_not_restart_matching(client):
    answers, state, _ = _reach_a_result(client)
    data = _post(client, "I also have vomiting", answers, state)
    assert ["vomiting", True] in data["answers"]
    # existing confirmed symptoms from the earlier result are preserved
    assert ["high_fever", True] in data["answers"]


def test_new_symptom_after_result_triggers_emergency_if_urgent(client):
    answers, state, _ = _reach_a_result(client)
    data = _post(client, "Now I also have chest pain", answers, state)
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


def test_emergency_short_circuits_everything(client):
    data = _post(client, "severe chest pain and difficulty breathing", [])
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"
    assert data["answers"] == []


# 11. Conversation memory across turns ------------------------------------


def test_conversation_memory_cough_then_fever(client):
    data, answers, state = _establish_complaint_then_answer_history(
        client, "I have a cough", values=("3 days", "5", "gradually")
    )
    data = _post(client, "I also have a fever", answers, state)
    names = {a[0] for a in data["answers"]}
    assert {"cough", "high_fever"} <= names


# 12. Explicitly denied symptom -------------------------------------------


def test_explicitly_denied_symptom_is_stored_as_false_not_dropped(client):
    data, answers, state = _establish_complaint_then_answer_history(
        client, "I have a cough", values=("2 days", "4", "gradual")
    )
    data = _post(client, "No fever", answers, state)
    assert ["high_fever", False] in data["answers"]
    # The symptom question that was actually pending must not be silently
    # marked False just because unrelated text arrived.
    pending_before = state.get("pending_symptom_question")
    if pending_before:
        assert not any(a == [pending_before, False] for a in data["answers"]) or pending_before == "high_fever"


# 13. Genuinely unknown term ------------------------------------------------


def test_unknown_term_gets_clarification_not_a_broken_search(client):
    data = _post(client, "qwerty zzz nonsense", [])
    assert data["next_step"]["type"] == "waiting"
    assert data["answers"] == []
    assert data["message"]


# Gemini boundary: intent classification must degrade safely -------------


def test_intent_classification_falls_back_without_gemini(client, monkeypatch):
    import gemini_client

    assert gemini_client.is_available() is False
    data = _post(client, "I have a headache", [])
    assert data["next_step"]["type"] == "question"
