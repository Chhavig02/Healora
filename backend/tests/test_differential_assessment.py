"""Differential assessment structure — spec section 7 and section 12.C
(follow-up memory: previously-answered slots are never re-asked)."""


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


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
    return data


def test_result_contains_full_differential_structure(client):
    data = _reach_a_result(client)
    step = data["next_step"]
    # short symptom summary
    assert step.get("symptom_summary")
    # positive symptoms
    assert step["symptoms_present"]
    # possible conditions, each with a reason ("why considered")
    assert step["possible_conditions"]
    for cond in step["possible_conditions"]:
        assert "matched_symptoms" in cond
    # severity/risk indicator
    assert step["severity"]
    # what's still uncertain
    assert "uncertain_symptoms" in step
    # recommended next step
    assert step.get("next_step_recommendation")
    # disclaimer, never a hard diagnosis claim
    assert step["disclaimer"]
    assert "you have" not in step["description"].lower()


def test_negative_symptoms_are_surfaced_in_the_result(client):
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["joint_pain", True],
        ["pain_behind_the_eyes", True],
        ["cough", False],
    ]
    state = {"chief_complaint": "high_fever", "history_slots_asked": ["duration", "severity", "onset"]}
    data = _post(client, "", answers, state)
    step = data["next_step"]
    assert "cough" in step["symptoms_denied"]


def test_conversation_summary_persists_in_state_after_result(client):
    data = _reach_a_result(client)
    assert data["state"]["conversation_summary"]


def test_history_slots_are_never_re_asked_once_answered(client):
    data = _post(client, "I have a headache", [])
    answers, state = data["answers"], data["state"]
    seen_slots = set()
    for _ in range(3):
        if state.get("pending_history_slot") is None:
            break
        slot = state["pending_history_slot"]
        assert slot not in seen_slots
        seen_slots.add(slot)
        data = _post(client, "some answer", answers, state)
        answers, state = data["answers"], data["state"]
    assert seen_slots == {"duration", "severity", "onset"}
