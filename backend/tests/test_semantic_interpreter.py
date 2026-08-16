"""Unit tests for the deterministic no-LLM floor of semantic_interpreter.py
(`_fallback_interpret`) — what every other test in this suite exercises,
since conftest.py sets GEMINI_API_KEY="" for the whole session. Mirrors
test_conversation_routing.py::test_intent_matrix's style (exact-bucket
assertions against the real seeded vocabulary), extended to check the new
structured fields this module adds on top of intent_classifier's existing
`meaning`/intent buckets.
"""

import conversation_state as cs
import semantic_interpreter as si
import symptom_engine


def _interp(message, state=None, extra_state=None):
    state = state or cs.new_state()
    if extra_state:
        state.update(extra_state)
    vocab = symptom_engine.get_all_symptom_names()
    local = symptom_engine.extract_symptoms_keyword(message.lower())
    return si._fallback_interpret(message, state, vocab, local), state


def test_semantic_interpreter_is_available_returns_full_shape_without_gemini(app_ctx, seeded):
    interp, _ = _interp("I have a headache")
    assert interp["meaning"] in si.MEANINGS
    for key in ("answers_pending_question", "user_reported_improvement", "user_reported_worsening"):
        assert isinstance(interp[key], bool)


# --- Worsening: a new bucket for language that previously had none --------


def test_worsening_recognized_as_meaning_when_nothing_else_fits(app_ctx, seeded):
    # None of these phrases happen to contain a real symptom-vocabulary
    # word, so nothing more specific outranks the worsening signal.
    for message in [
        "I feel much worse now.",
        "It's getting worse.",
        "My pain is getting stronger.",
        "I'm not getting any better.",
    ]:
        interp, _ = _interp(message)
        assert interp["meaning"] == "SYMPTOMS_WORSENING", message
        assert interp["user_reported_worsening"] is True, message


def test_worsening_flag_independent_of_new_symptom_meaning(app_ctx, seeded):
    # "fever"/"chills" are real symptom-vocabulary words, so a plain
    # keyword match routes this to NEW_SYMPTOM (same precedence
    # intent_classifier._fallback_classify already gives a real symptom
    # over everything else) — fever gets reasserted and, if there's an
    # active assessment, reassessed. But worsening is still flagged as an
    # independent signal, not discarded just because something more
    # specific matched the routing.
    state = cs.new_state()
    state["chief_complaint"] = "fever"
    interp, _ = _interp("The fever's back and I also have chills.", state=state)
    assert interp["meaning"] == "NEW_SYMPTOM"
    assert interp["user_reported_worsening"] is True

    interp2, _ = _interp("The fever came back.")
    assert interp2["meaning"] == "NEW_SYMPTOM"
    assert interp2["user_reported_worsening"] is True


def test_worsening_does_not_fire_on_unrelated_messages(app_ctx, seeded):
    interp, _ = _interp("Thanks, that's helpful.")
    assert interp["user_reported_worsening"] is False


# --- Improvement: still recognized, now via the shared interpreter --------


def test_improvement_still_recognized(app_ctx, seeded):
    for message in ["I'm fine now.", "I am feeling better.", "It's gone now."]:
        interp, _ = _interp(message)
        assert interp["meaning"] == "FEELING_BETTER", message
        assert interp["user_reported_improvement"] is True, message


# --- answers_pending_question: the generalized "does this look like an
# answer to whatever's pending" signal ---------------------------------


def test_answers_pending_question_true_for_duration_cue_words(app_ctx, seeded):
    state = cs.new_state()
    state["chief_complaint"] = "stomach_pain"
    state["pending_history_slot"] = "duration"
    interp, _ = _interp("since yesterday", state=state)
    assert interp["answers_pending_question"] is True


def test_answers_pending_question_false_when_message_is_actually_a_new_symptom(app_ctx, seeded):
    state = cs.new_state()
    state["chief_complaint"] = "stomach_pain"
    state["pending_history_slot"] = "duration"
    interp, _ = _interp("i am feeling tierd", state=state)
    assert interp["answers_pending_question"] is False
    # local keyword match on the seeded "tierd" alias routes this straight
    # to NEW_SYMPTOM, same as intent_classifier's own behavior — this
    # module doesn't change that routing, only exposes the extra signal.
    assert interp["meaning"] == "NEW_SYMPTOM"


def test_answers_pending_question_true_for_symptom_yes_no(app_ctx, seeded):
    state = cs.new_state()
    state["pending_symptom_question"] = "nausea"
    interp, _ = _interp("yes", state=state)
    assert interp["answers_pending_question"] is True
    assert interp["meaning"] == "SYMPTOM_ANSWER"


def test_answers_pending_question_false_with_nothing_pending(app_ctx, seeded):
    interp, _ = _interp("hello")
    assert interp["answers_pending_question"] is False


# --- A question-shaped interruption must never be swallowed as the -------
# literal pending-slot answer, even though intent_classifier._fallback_classify
# uses HISTORY_ANSWER as its own catch-all when nothing more specific
# matched (see semantic_interpreter._reconcile).


def test_question_shaped_message_while_pending_is_not_history_answer(app_ctx, seeded):
    state = cs.new_state()
    state["chief_complaint"] = "headache"
    state["pending_history_slot"] = "duration"
    interp, _ = _interp("What should I tell my doctor?", state=state)
    assert interp["meaning"] != "HISTORY_ANSWER"
    assert interp["answers_pending_question"] is False


def test_genuinely_ambiguous_answer_still_stored_via_original_floor(app_ctx, seeded):
    # Not question-shaped, so the original "store it anyway" floor for a
    # genuinely odd-but-real free-text answer still applies unchanged —
    # this reconciliation only targets question-shaped interruptions.
    state = cs.new_state()
    state["chief_complaint"] = "headache"
    state["pending_history_slot"] = "duration"
    interp, _ = _interp("I don't really know", state=state)
    assert interp["meaning"] == "HISTORY_ANSWER"


# --- interpret() itself falls back cleanly with no provider configured ----


def test_interpret_falls_back_without_gemini(app_ctx, seeded):
    import gemini_client

    assert gemini_client.is_available() is False
    state = cs.new_state()
    vocab = symptom_engine.get_all_symptom_names()
    local = symptom_engine.extract_symptoms_keyword("i have a headache")
    interp = si.interpret("I have a headache", state, vocab, local)
    assert interp["meaning"] == "NEW_SYMPTOM"
