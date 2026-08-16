"""Open-ended health conversation — Healora should feel like a
conversational assistant that can invoke the disease engine when useful,
not a bounded "pick from 188 diseases" chatbot. Covers spec section 16's
test matrix: messages that must NOT enter the disease engine unnecessarily,
messages that DO enter assessment, and the conversation <-> assessment
transition itself.
"""


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


# --- Must NOT enter the disease engine unnecessarily -----------------------


def test_vague_feeling_weird_does_not_start_assessment(client):
    data = _post(client, "I've been feeling weird lately.", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] not in ("question", "result")


def test_tired_all_the_time_alone_does_not_start_structured_assessment(client):
    data = _post(client, "I'm tired all the time.", [])
    # the symptom is still recorded (remembered, not lost)...
    assert ["fatigue", True] in data["answers"]
    # ...but structured history-taking hasn't formally begun yet.
    assert data["state"]["chief_complaint"] is None
    assert data["next_step"]["type"] == "waiting"


def test_why_does_fever_make_me_weak_is_a_general_question(client):
    data = _post(client, "Why does fever make me weak?", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] == "waiting"


def test_what_is_dehydration_is_a_general_question(client):
    data = _post(client, "What is dehydration?", [])
    assert data["next_step"]["type"] == "waiting"


def test_scared_does_not_start_assessment(client):
    data = _post(client, "I'm scared.", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] == "waiting"


def test_love_you_does_not_start_assessment(client):
    data = _post(client, "I love you.", [])
    assert data["answers"] == []


def test_thanks_does_not_start_assessment(client):
    data = _post(client, "Thanks.", [])
    assert data["answers"] == []


def test_what_should_i_tell_my_doctor_does_not_start_assessment(client):
    data = _post(client, "What should I tell my doctor?", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] == "waiting"


def test_what_happens_during_pregnancy_does_not_use_disease_matcher(client):
    data = _post(client, "What happens during pregnancy?", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] == "waiting"


# --- Must enter assessment when appropriate ---------------------------------


def test_fever_and_headache_enters_assessment(client):
    data = _post(client, "I have fever and headache.", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert {"high_fever", "headache"} <= names
    assert data["state"]["chief_complaint"] is not None
    assert data["next_step"]["type"] == "question"


def test_cough_for_three_days_enters_assessment(client):
    data = _post(client, "I've had a cough for three days.", [])
    assert ["cough", True] in data["answers"]
    assert data["state"]["chief_complaint"] is not None


def test_stomach_hurts_and_nauseous_enters_assessment(client):
    data = _post(client, "My stomach hurts and I feel nauseous.", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert "stomach_pain" in names
    assert data["state"]["chief_complaint"] is not None


# --- Transition: vague -> concrete crosses into structured assessment -----


def test_vague_then_concrete_symptoms_transitions_into_assessment(client):
    data = _post(client, "I've been feeling awful for three days.", [])
    answers, state = data["answers"], data["state"]
    assert state["chief_complaint"] is None  # still just conversation

    data = _post(client, "Fever, headache and chills.", answers, state)
    names = {a[0] for a in data["answers"] if a[1]}
    assert {"high_fever", "headache", "chills"} <= names
    assert data["state"]["chief_complaint"] is not None
    assert data["next_step"]["type"] in ("question", "result")


def test_explicit_assessment_request_after_vague_symptom_starts_it(client):
    data = _post(client, "I'm tired all the time.", [])
    answers, state = data["answers"], data["state"]
    assert state["chief_complaint"] is None

    data = _post(client, "Can you check my symptoms?", answers, state)
    assert data["state"]["chief_complaint"] is not None
    assert data["next_step"]["type"] in ("question", "result")


# --- Post-assessment: explain / worried / doctor-prep / topic switch ------


def _reach_a_result(client):
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


def test_what_does_that_mean_after_result_is_contextual(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    condition = state["current_primary_condition"]

    data = _post(client, "What does that result mean?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    assert data["state"]["current_primary_condition"] == condition


def test_worried_after_result_is_contextual_not_reassessed(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    condition = state["current_primary_condition"]

    data = _post(client, "I'm worried.", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["state"]["current_primary_condition"] == condition


def test_doctor_prep_after_result_is_contextual(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]

    data = _post(client, "What should I tell my doctor?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]


def test_topic_switch_mid_assessment_answers_the_new_topic(client):
    # Start an assessment (mid history-taking, no result yet).
    data = _post(client, "I have a headache", [])
    answers, state = data["answers"], data["state"]
    assert state.get("pending_history_slot")  # still mid-assessment

    data = _post(client, "Actually, why do people get hiccups?", answers, state)
    assert data["next_step"]["type"] == "waiting"
    assert data["message"]
    # the pending history question must still be there afterward, not lost
    assert data["state"].get("pending_history_slot") == state["pending_history_slot"]


def test_new_emergency_symptom_still_overrides_post_assessment_chat(client):
    data = _reach_a_result(client)
    answers, state = data["answers"], data["state"]
    data = _post(client, "Now I also have severe chest pain and can't breathe.", answers, state)
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


def test_emergency_overrides_open_conversation_too(client):
    data = _post(client, "I'm just chatting, but suddenly I have severe chest pain and can't breathe.", [])
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"
