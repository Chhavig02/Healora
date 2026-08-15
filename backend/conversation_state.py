"""Structured, stateless conversation state for the /api/chat conversational
flow.

Healora's backend has always been stateless across requests — the frontend
round-trips whatever state it needs each turn (the `answers` list already
worked this way). This module extends that same pattern with a richer
`state` dict, rather than introducing a server-side session store: no new
persistence system, just a second JSON blob the client already carries
alongside `answers`.

`answers` (`[[symptom_name, bool], ...]`) remains the single source of
truth for which canonical symptoms are confirmed/denied — this module never
duplicates that list. `symptoms_present` / `symptoms_denied` below are
computed views over `answers`, not a second copy that could drift out of
sync with it.
"""

STAGES = (
    "GREETING",
    "CHIEF_COMPLAINT",
    "HISTORY_TAKING",
    "SYMPTOM_CLARIFICATION",
    "SAFETY_TRIAGE",
    "POSSIBLE_CONDITIONS",
    "EDUCATIONAL_GUIDANCE",
    "FOLLOW_UP",
    # Added for full-conversation phase tracking (see conversation phases in
    # the module docstring / README): EMERGENCY and GENERAL_QUESTION are
    # transient markers stamped on the state returned for that one turn;
    # COMPLETED marks a user-initiated goodbye/restart.
    "EMERGENCY",
    "GENERAL_QUESTION",
    "COMPLETED",
)

# Asked once per new chief complaint, in this order, before falling back to
# the existing disease_matcher-driven yes/no symptom questions. Not backed
# by any DB scoring — the schema has no field for "duration" or "severity"
# to feed into rank_diseases()'s math (see disease_matcher.py), so these
# exist purely to make the conversation feel like real history-taking and
# to ground Gemini's phrasing — they never change which disease is ranked
# highest.
HISTORY_SLOTS = ("duration", "severity", "onset")

_DEFAULT_STATE = {
    "chief_complaint": None,
    "duration": None,
    "onset": None,
    "severity": None,
    "progression": None,
    "location": None,
    "character": None,
    "age": None,
    "age_group": None,
    "sex": None,
    "relevant_history": None,
    # Free-text mentions the user volunteered, not a structured medication/
    # allergy/condition database (Healora's schema has none) — see
    # profile_extraction.py. Never used to generate dosage or treatment
    # advice, only surfaced back to the user/summary as "you mentioned...".
    "medications": [],
    "allergies": [],
    "existing_conditions": [],
    "risk_factors": None,
    "current_possible_conditions": [],
    "current_primary_condition": None,
    "conversation_stage": "GREETING",
    "pending_history_slot": None,
    "pending_symptom_question": None,
    "history_slots_asked": [],
    # Question text already asked this conversation (history-taking +
    # symptom-clarification), so the question-selection layer never repeats
    # itself and so a summary/test can inspect what was asked.
    "questions_asked": [],
    "emergency_status": False,
    "last_user_message": None,
    "conversation_summary": None,
}

_LIST_FIELDS = (
    "history_slots_asked",
    "current_possible_conditions",
    "medications",
    "allergies",
    "existing_conditions",
    "questions_asked",
)


def new_state():
    return dict(_DEFAULT_STATE)


def normalize(raw_state):
    """Merge a client-supplied state dict onto the default shape so a
    missing/malformed/partial `state` from an older client (or none at all)
    never crashes the request — every key always exists with a safe type."""
    state = new_state()
    if isinstance(raw_state, dict):
        for key in _DEFAULT_STATE:
            if key in raw_state and raw_state[key] is not None:
                state[key] = raw_state[key]
    if state.get("conversation_stage") not in STAGES:
        state["conversation_stage"] = "GREETING"
    for key in _LIST_FIELDS:
        if not isinstance(state.get(key), list):
            state[key] = []
    if not isinstance(state.get("emergency_status"), bool):
        state["emergency_status"] = False
    return state


def mark_emergency(state):
    state["conversation_stage"] = "EMERGENCY"
    state["emergency_status"] = True
    return state


def symptoms_present(answers):
    return [a[0] for a in answers if a[1]]


def symptoms_denied(answers):
    return [a[0] for a in answers if not a[1]]


def next_history_slot(state):
    """The next history-taking slot to ask about, or None if all have been
    asked (or skipped) for the current chief complaint."""
    asked = set(state.get("history_slots_asked") or [])
    for slot in HISTORY_SLOTS:
        if slot not in asked:
            return slot
    return None


def start_new_complaint(state, chief_complaint):
    """Reset the history-taking/result context for a genuinely new
    complaint, while leaving unrelated fields (age_group, allergies, etc.)
    untouched — those don't reset just because the presenting symptom
    changed mid-conversation."""
    state["chief_complaint"] = chief_complaint
    state["duration"] = None
    state["onset"] = None
    state["severity"] = None
    state["progression"] = None
    state["pending_history_slot"] = None
    state["history_slots_asked"] = []
    state["current_possible_conditions"] = []
    state["current_primary_condition"] = None
    state["conversation_stage"] = "HISTORY_TAKING"
    return state
