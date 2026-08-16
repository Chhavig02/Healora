"""Multi-turn conversation tests — TEST A through H from the "build the
real context-aware conversational layer" brief's section 19, driven
through the real /api/chat Flask test client (deterministic-fallback
path, same as every other test in this suite — no GEMINI_API_KEY locally).
Complements test_semantic_interpreter.py's unit-level checks by exercising
the whole pipeline (semantic interpretation + orchestrator dispatch +
disease engine + state round-tripping) together, the same way
test_intent_switching.py/test_open_conversation.py already do for the
narrower cases they cover.
"""


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def _answer_all_questions(client, data):
    guard = 0
    while data["next_step"]["type"] == "question" and guard < 8:
        data = _post(client, "yes", data["answers"], data["state"])
        guard += 1
    return data


# --- TEST A: a pending duration question interrupted by an unrelated ------
# symptom — the symptom must be recorded and the duration question must
# still be pending afterward, not silently swallowed as the literal answer.


def test_A_unrelated_symptom_while_duration_pending_does_not_lose_either_fact(client):
    data = _post(client, "I have stomach pain", [])
    assert data["state"]["pending_history_slot"] == "duration"
    answers, state = data["answers"], data["state"]

    data = _post(client, "I am feeling tired.", answers, state)
    assert ["fatigue", True] in data["answers"]
    assert data["state"]["duration"] is None
    assert data["state"]["pending_history_slot"] == "duration"
    assert data["message"]


# --- TEST B: "how are you feeling now?" / "Now I am fine." is an update, --
# not a question — no generic advice, no disease re-match.


def test_B_feeling_fine_after_result_is_an_update_not_a_rematch(client):
    data = _post(client, "I have a headache", [])
    data = _answer_all_questions(client, data)
    assert data["next_step"]["type"] == "result"
    answers, state = data["answers"], data["state"]

    data = _post(client, "Now I am fine.", answers, state)
    assert data["next_step"]["type"] != "result"
    assert data["state"]["user_reported_improvement"] is True
    assert data["message"]


# --- TEST C: vague -> more detail -> transitions naturally into a --------
# structured assessment, without ever losing what was already said.


def test_C_vague_conversation_transitions_into_structured_assessment(client):
    data = _post(client, "I've been feeling weird lately.", [])
    assert data["answers"] == []
    assert data["next_step"]["type"] == "waiting"
    answers, state = data["answers"], data["state"]

    data = _post(client, "Mostly tired and weak.", answers, state)
    # fatigue is recorded, but still too vague on its own to formally start
    # structured history-taking.
    assert ["fatigue", True] in data["answers"]
    assert data["state"]["chief_complaint"] is None
    answers, state = data["answers"], data["state"]

    data = _post(client, "Also fever and headache since yesterday.", answers, state)
    assert data["state"]["chief_complaint"] is not None
    present = {a[0] for a in data["answers"] if a[1]}
    assert {"fatigue", "high_fever", "headache"} <= present


# --- TEST D: after a result, a general "why" question is answered --------
# directly — never re-runs the disease engine.


def test_D_general_question_after_result_does_not_rematch_disease(client):
    data = _post(client, "I have fever, headache and chills.", [])
    data = _answer_all_questions(client, data)
    assert data["next_step"]["type"] == "result"
    answers, state = data["answers"], data["state"]

    data = _post(client, "Why does fever make me weak?", answers, state)
    assert data["next_step"]["type"] != "result"
    assert data["message"]


# --- TEST E: emotional support, then a practical follow-up — both -------
# answered directly, neither forced back into the disease engine.


def test_E_emotional_concern_then_doctor_prep_question(client):
    data = _post(client, "I have fever, headache and chills.", [])
    data = _answer_all_questions(client, data)
    assert data["next_step"]["type"] == "result"
    answers, state = data["answers"], data["state"]

    data = _post(client, "I'm scared.", answers, state)
    assert data["next_step"]["type"] != "result"
    assert data["message"]
    answers, state = data["answers"], data["state"]

    data = _post(client, "What should I tell my doctor?", answers, state)
    assert data["next_step"]["type"] != "result"
    assert data["message"]


# --- TEST F: worsening after a result is recognized as its own thing, ----
# not silently absorbed into the generic post-result catch-all.


def test_F_worsening_after_result_is_recognized(client):
    data = _post(client, "I have a headache", [])
    data = _answer_all_questions(client, data)
    assert data["next_step"]["type"] == "result"
    answers, state = data["answers"], data["state"]

    data = _post(client, "Actually, I feel much worse now.", answers, state)
    assert data["next_step"]["type"] != "result"
    assert data["state"]["user_reported_worsening"] is True
    assert data["message"]


# --- TEST G: Hinglish is understood without requiring English medical ----
# terminology.


def test_G_hinglish_fever_and_headache_understood(client):
    data = _post(client, "mujhe kal se bukhar h aur sar dard ho rha h", [])
    present = {a[0] for a in data["answers"] if a[1]}
    assert {"high_fever", "headache"} <= present


# --- TEST H: a typo combined with Hinglish is still understood, and -----
# structured assessment starts once there's enough concrete detail.


def test_H_typo_plus_hinglish_understood_and_starts_assessment(client):
    data = _post(client, "tierd hu aur vomiting bhi ho rhi h", [])
    present = {a[0] for a in data["answers"] if a[1]}
    assert {"fatigue", "vomiting"} <= present
    assert data["state"]["chief_complaint"] is not None


# --- A full ~12-turn conversation exercising context retention, topic ----
# switching, and the assessment <-> open-conversation transition together,
# matching the acceptance criteria in section 21 of the brief.


def test_full_conversation_never_loses_context_or_gets_stuck(client):
    answers, state = [], None

    data = _post(client, "hi", answers, state)
    answers, state = data["answers"], data["state"]

    data = _post(client, "I've been feeling off lately.", answers, state)
    assert data["next_step"]["type"] == "waiting"
    answers, state = data["answers"], data["state"]

    data = _post(client, "I have a headache and a fever.", answers, state)
    assert data["state"]["chief_complaint"] is not None
    answers, state = data["answers"], data["state"]

    # Interrupt history-taking with an unrelated question — must not be
    # swallowed as the literal answer, and must not lose the pending slot.
    pending_slot = state["pending_history_slot"]
    data = _post(client, "What medicine should I take?", answers, state)
    assert "don't have verified medication" in data["message"]
    assert data["state"]["pending_history_slot"] == pending_slot
    answers, state = data["answers"], data["state"]

    data = _post(client, "since yesterday", answers, state)
    answers, state = data["answers"], data["state"]

    data = _answer_all_questions(client, {"next_step": {"type": "waiting"}, "answers": answers, "state": state})
    # Drive through any remaining history/symptom questions to a result.
    guard = 0
    while data["next_step"]["type"] in ("question", "waiting") and guard < 12:
        if data["next_step"]["type"] == "question":
            data = _post(client, "yes", data["answers"], data["state"])
        else:
            break
        guard += 1
    answers, state = data["answers"], data["state"]

    # Topic switch: an unrelated question must be answered on its own
    # terms, not forced back into "continue your assessment".
    data = _post(client, "By the way, why do people get hiccups?", answers, state)
    assert data["next_step"]["type"] != "result"
    assert data["message"]
    answers, state = data["answers"], data["state"]

    data = _post(client, "Thanks, that helps.", answers, state)
    assert data["message"]
    answers, state = data["answers"], data["state"]

    data = _post(client, "bye", answers, state)
    assert data["next_step"]["type"] == "reset"
