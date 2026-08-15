"""Intent switching / interruption — spec section 2 (natural interruption)
and section 12.D.

Covers the exact example from the task brief:

    Bot: "Does the pain get worse after eating?"
    User: "What medicine should I take?"

...and the general symptom -> medication / general-health / new-symptom
switches, all via the real /api/chat endpoint so the whole pipeline
(intent classification + routing) is exercised together, not just the
classifier in isolation.
"""


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def _reach_pending_history_question(client):
    """Establishes a chief complaint, landing on the first (duration)
    history-taking question — mirrors _establish_complaint_then_answer_history
    in test_conversation.py but stops after the first question so a slot is
    still pending."""
    data = _post(client, "I have stomach pain", [])
    assert data["next_step"]["type"] == "question"
    assert data["next_step"]["answer_mode"] == "open"
    assert data["state"]["pending_history_slot"] is not None
    return data["answers"], data["state"]


def test_medication_question_interrupts_pending_history_question(client):
    answers, state = _reach_pending_history_question(client)
    data = _post(client, "What medicine should I take?", answers, state)
    assert "don't have verified medication" in data["message"]
    # The interrupted question isn't lost — it's still pending afterward.
    assert data["state"]["pending_history_slot"] == state["pending_history_slot"]
    # And the response reminds the user what was being asked.
    assert "?" in data["message"]


def test_plain_history_answer_still_works_even_though_it_contains_trigger_words(client):
    # "severe" would match the SEVERITY_QUESTION keyword regex — this must
    # still be read as an answer to the severity question, not a new
    # question, when it isn't phrased as one.
    data = _post(client, "I have a headache", [])
    answers, state = data["answers"], data["state"]
    data = _post(client, "since yesterday", answers, state)  # duration
    answers, state = data["answers"], data["state"]
    assert state["pending_history_slot"] == "severity"
    data = _post(client, "it's pretty severe", answers, state)
    assert data["state"].get("severity") == "it's pretty severe"
    assert data["state"]["pending_history_slot"] != "severity"


def test_symptom_report_then_medication_question_does_not_lose_the_symptom(client):
    data = _post(client, "I have a headache", [])
    assert ["headache", True] in data["answers"]
    answers, state = data["answers"], data["state"]

    data = _post(client, "What medicine should I take?", answers, state)
    assert "don't have verified medication" in data["message"]
    # Symptom recorded earlier in the conversation must still be there.
    assert ["headache", True] in data["answers"]


def test_general_health_question_without_any_prior_context(client):
    data = _post(client, "What is migraine?", [])
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert data["answers"] == []


def test_general_health_question_unrelated_to_a_named_disease(client):
    data = _post(client, "Why does fever happen?", [])
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    # Must not be misread as a fresh fever complaint just because the word
    # "fever" appears in the question.
    assert data["answers"] == []


def test_prevention_question_without_prior_context(client):
    data = _post(client, "What should I do for dehydration?", [])
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]


def test_restart_resets_conversation(client):
    data = _post(client, "I have a headache", [])
    answers, state = data["answers"], data["state"]
    assert answers  # something was captured

    data = _post(client, "restart", answers, state)
    assert data["next_step"]["type"] == "reset"
    assert data["state"]["chief_complaint"] is None
