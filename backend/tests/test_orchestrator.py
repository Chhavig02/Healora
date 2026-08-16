"""Multi-turn conversation orchestration tests — spec section 16's ten
required scenarios, covering the root bug this refactor fixes: a message
that doesn't match a narrow intent regex used to fall through and
re-invoke the disease engine on unchanged `answers`, which either
regenerated the same question or re-showed the same result card. These
tests exercise the real /api/chat endpoint end to end (deterministic
fallback path — no GEMINI_API_KEY in the test environment), the same way
every other conversation test in this codebase does.
"""


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def _walk_history(client, complaint_message, values=("3 days", "6", "gradually")):
    """Establishes a chief complaint and answers all three history-taking
    slots, returning the response that follows (a yes/no symptom question,
    or a result if the matcher was already confident)."""
    data = _post(client, complaint_message, [])
    answers, state = data["answers"], data["state"]
    for value in values:
        data = _post(client, value, answers, state)
        answers, state = data["answers"], data["state"]
    return data, answers, state


def _reach_a_result(client):
    """Fast path to a result card without walking the full history-taking
    sequence — mirrors the helper used elsewhere in this test suite."""
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["chills", True],
        ["joint_pain", True],
    ]
    state = {"chief_complaint": "high_fever", "history_slots_asked": ["duration", "severity", "onset"]}
    data = _post(client, "", answers, state)
    assert data["next_step"]["type"] == "result"
    return data


# TEST 1 — normal conversation ------------------------------------------


def test_normal_conversation_does_not_jump_to_a_result_card(client):
    data = _post(client, "I've been feeling tired lately.", [])
    assert data["next_step"]["type"] != "result"
    assert data["message"] or data["next_step"].get("symptom")


# TEST 2 — symptom assessment --------------------------------------------


def test_symptom_assessment_begins(client):
    data = _post(client, "I have fever, headache and chills.", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert {"high_fever", "headache", "chills"} <= names
    assert data["next_step"]["type"] in ("question", "result")


# TEST 3 — follow-up answer applied without restarting -------------------


def test_followup_answer_applies_without_restarting(client):
    data, answers, state = _walk_history(client, "I have fever, headache and chills.")
    assert state.get("pending_symptom_question") or data["next_step"]["type"] == "result"
    if data["next_step"]["type"] == "question":
        raw = data["next_step"]["raw_symptom"]
        data = _post(client, "yes", answers, state)
        assert [raw, True] in data["answers"]
        # every symptom answered before this turn must still be present
        assert ["high_fever", True] in data["answers"]


# TEST 4 — post-assessment question: medication ---------------------------


def test_medication_question_after_assessment_is_contextual(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    condition = state["current_primary_condition"]

    data = _post(client, "medicines?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert "couldn't" not in data["message"].lower()
    assert "don't have verified medication" in data["message"]
    # names the possible condition rather than a flat generic string
    assert condition in data["message"]
    # must not have silently regenerated another result card
    assert data["state"]["current_primary_condition"] == condition


# TEST 5 — precautions -----------------------------------------------------


def test_precaution_question_after_assessment_is_contextual(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    data = _post(client, "what precautions should I take?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert data["state"]["current_primary_condition"] == state["current_primary_condition"]


# TEST 6 — general question using assessment context -----------------------


def test_is_this_serious_uses_assessment_context(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    data = _post(client, "is this serious?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert data["state"]["current_primary_condition"] == state["current_primary_condition"]


# TEST 7 — new symptom after assessment updates it --------------------------


def test_new_symptom_after_assessment_triggers_reassessment_note(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    data = _post(client, "now I'm vomiting", answers, state)
    assert ["vomiting", True] in data["answers"]
    assert "reassess" in (data["message"] or "").lower()


# TEST 8 — emergency overrides everything, even mid-assessment -------------


def test_emergency_overrides_post_assessment_conversation(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    data = _post(client, "I suddenly have severe chest pain and difficulty breathing", answers, state)
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


# TEST 9 — start over --------------------------------------------------------


def test_start_over_clears_state(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    data = _post(client, "start over.", answers, state)
    assert data["next_step"]["type"] == "reset"
    assert data["state"]["chief_complaint"] is None
    assert data["state"]["current_primary_condition"] is None


# TEST 10 — no context, general educational question ------------------------


def test_general_question_with_no_context_does_not_trigger_assessment(client):
    data = _post(client, "what is typhoid?", [])
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert data["answers"] == []


# Root-bug regression: an unrecognized follow-up must never silently
# regenerate the same result card by re-running the disease engine on
# unchanged answers.
def test_unrecognized_followup_never_regenerates_the_result_card(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    baseline_condition = state["current_primary_condition"]

    data = _post(client, "what does that mean for my daily life", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert "couldn't" not in data["message"].lower()
    assert data["state"]["current_primary_condition"] == baseline_condition


def test_diet_and_home_care_and_recovery_questions_are_contextual(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]

    for message in ("what should I eat?", "what can I do at home?", "can I go to work?"):
        resp = _post(client, message, answers, state)
        assert resp["next_step"]["type"] == "waiting"
        assert resp["message"]
        assert "couldn't" not in resp["message"].lower()


# Regression: a pending duration/severity/onset question must never
# swallow an unrelated statement verbatim as the literal answer — "i am
# feeling tierd" (a typo of "tired") was previously stored as the literal
# duration.
def test_typo_symptom_during_pending_duration_is_not_stored_as_duration(client):
    data = _post(client, "I have stomach pain", [])
    answers, state = data["answers"], data["state"]
    assert state.get("pending_history_slot") == "duration"

    data = _post(client, "i am feeling tierd", answers, state)
    assert ["fatigue", True] in data["answers"]
    # duration must still be pending, not corrupted with the typo message
    assert data["state"].get("pending_history_slot") == "duration"
    assert data["state"].get("duration") is None


def test_llm_recognized_symptom_during_pending_history_is_not_stored_as_the_answer(client, monkeypatch):
    import llm.gemini_provider as gemini_provider

    data = _post(client, "I have stomach pain", [])
    answers, state = data["answers"], data["state"]
    assert state.get("pending_history_slot") == "duration"

    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        gemini_provider,
        "generate_json",
        lambda *a, **kw: {"symptoms": [{"name": "fatigue", "present": True}]},
    )
    data = _post(client, "i am feeling xhausted", answers, state)
    assert ["fatigue", True] in data["answers"]
    assert data["state"].get("pending_history_slot") == "duration"
    assert data["state"].get("duration") is None
