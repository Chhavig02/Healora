"""Intent classification for the conversational chat flow.

Emergency detection is deliberately NOT one of the intents handled here —
`emergency.py` runs before this module is ever reached and its decision is
final (see chat.py). This module only distinguishes the *non-emergency*
conversational intents.

Like the rest of Healora's Gemini integration, classification is
Gemini-assisted but never Gemini-dependent: `classify` always falls back to
a deterministic, keyword-based classifier if Gemini is unavailable, fails,
or returns something outside the known intent set. The fallback is what
every test in this codebase exercises by default (no GEMINI_API_KEY in the
test environment), so it has to be genuinely serviceable on its own, not a
token stub.
"""

import re

from gemini_client import generate_json, is_available

INTENTS = (
    "GREETING",
    "NEW_SYMPTOM",
    "SYMPTOM_ANSWER",
    "HISTORY_ANSWER",
    "FOLLOW_UP_RESULT",
    "QUESTION_ABOUT_CONDITION",
    "MEDICATION_QUESTION",
    "PRECAUTION_QUESTION",
    "DIET_QUESTION",
    "HOME_CARE_QUESTION",
    "RECOVERY_QUESTION",
    "SEVERITY_QUESTION",
    "CAUSE_QUESTION",
    "DURATION_QUESTION",
    "PREGNANCY",
    "CASUAL",
    "RESTART",
    "UNCLEAR",
)

# Every regex below is checked with re.search against the raw (lowercased
# by re.I) message — deliberately using `\w*` suffixes on the key stems
# (medicine, precaution, ...) rather than a bare `\bmedicine\b` word match:
# `\b` is a transition between a word and non-word character, so a plain
# `\bmedicine\b` does NOT match inside "medicines" (there's no boundary
# between the "e" and the "s", both word characters) — a real bug that
# made "medicines?" fall through to UNCLEAR. Same issue applied to
# "precautions". The `\w*` suffix fixes the whole family of plural/
# inflected forms at once instead of enumerating each one.
_GREETING_RE = re.compile(r"\b(hello|hi|hey|greetings|sup|what's up|start|checkup)\b", re.I)
_RESTART_RE = re.compile(
    r"^\s*(restart|start over|start again|reset|begin again|new (check|conversation|chat))\b", re.I
)
CASUAL_RE = re.compile(
    r"^\s*(thanks|thank you|thankyou|ok|okay|k|great|cool|good|nice|got it|alright|sure)\s*[!.]*\s*$",
    re.I,
)
# Affectionate/relationship small talk — phrased as full sentences, so it
# needs its own (non-anchored) pattern rather than extending CASUAL_RE's
# whole-message match. Routed to the same CASUAL handling: a warm,
# non-medical reply that doesn't claim to be a real person or a romantic
# partner — never symptom clarification.
_AFFECTION_RE = re.compile(
    r"\b(i love you|love you|i like you|i want to marry you|will you marry me|"
    r"marry me|you'?re (the best|amazing|awesome|so sweet|so kind)|i miss you)\b",
    re.I,
)
# A simple prefix is enough to tolerate the common misspelling "pregnent"
# (and "pregnancy"/"preggo"/etc.) without needing fuzzy edit-distance
# matching — "preg" is specific enough in English that this doesn't risk
# false positives the way a broader fuzzy match would.
_PREGNANCY_RE = re.compile(
    r"\bpreg\w*\b|\bexpecting\b|\bmissed (my )?period\b|\bmaternity\b", re.I
)
_YES_RE = re.compile(r"^\s*(yes|yeah|yep|yup|correct|right)\b", re.I)
_NO_RE = re.compile(r"^\s*(no|nope|nah|not really|not at all)\b", re.I)
_MEDICATION_RE = re.compile(
    r"\b(medicine\w*|medication\w*|drug\w*|doses?|dosage\w*|pill\w*|tablet\w*|"
    r"prescri\w*|antibiotic\w*|painkiller\w*)\b",
    re.I,
)
_SEVERITY_RE = re.compile(
    r"\b(serious\w*|severe\w*|dangerous|worr\w*|concerning|bad sign)\b|\bshould i worry\b", re.I
)
_CAUSE_RE = re.compile(r"\b(why|cause\w*|reason\w*|caused by)\b", re.I)
# Deliberately requires the fuller phrase, not a bare "last" or "go away" —
# those words show up too easily in an ordinary history-taking answer
# ("since last week", "it hasn't gone away") and would otherwise get
# misread as the user asking a new question instead of answering the one
# they were just asked.
_DURATION_RE = re.compile(
    r"\bhow long\b|\bwhen will\b|\bhow many days\b|\bgo away\b|\bwill (?:it |this )?last\b", re.I
)
_PRECAUTION_RE = re.compile(
    r"\b(precaution\w*|avoid\w*|prevent\w*|self.?care|home remedy\w*)\b|"
    r"\bwhat should i (do|avoid)\b|\btake care\b",
    re.I,
)
# Food/diet is a genuinely separate concern from precautions/prevention —
# Healora has no dietary-data field on Disease, so this always answers from
# general, non-condition-specific guidance (see orchestrator.py).
_DIET_RE = re.compile(r"\b(eat\w*|diet\w*|food\w*|drink\w*|nutrition\w*)\b", re.I)
# "What can I do at home" / "how do I manage this myself" — distinct from
# PRECAUTION_QUESTION (which is about avoiding/preventing complications);
# this is about self-management day to day.
_HOME_CARE_RE = re.compile(
    r"\bat home\b|\bhome care\b|\bmanage (?:this |it )?(?:myself|at home)\b|\bself.manage\w*\b", re.I
)
# "Can I go to work/school", "when can I go back to normal activity" — a
# return-to-normal-life question, not a medical-fact question.
_RECOVERY_RE = re.compile(
    r"\bgo(?:ing)? to work\b|\bgo back to\b|\breturn to work\b|\bresume\w*\b|"
    r"\bwhen can i\b|\bhow soon\b|\bback to normal\b|\bgo to school\b", re.I
)
_CONDITION_QUESTION_RE = re.compile(
    r"\b(what is|what's|tell me about|explain\w*|more about|what does\b.*\bmean)\b", re.I
)
_DOCTOR_RE = re.compile(r"\b(see a doctor|should i see|need a doctor|go to (the )?(er|hospital))\b", re.I)

# Used only to decide whether a message sent while a history-taking slot is
# pending should be read as an interruption rather than the answer to that
# slot — an ordinary answer ("since yesterday", "it's pretty severe") is
# rarely phrased as a question, so gating on this keeps a severity answer
# that happens to contain the word "severe" from being misread as a new
# SEVERITY_QUESTION.
_QUESTION_LEAD_RE = re.compile(r"^\s*(what|why|how|can|could|should|is|does|do|will)\b|\?", re.I)


def _yes_no(text):
    if _YES_RE.match(text):
        return True
    if _NO_RE.match(text):
        return False
    return None


def _classify_interruption(stripped):
    """Recognizes a message as one of the "informational question" intents
    — MEDICATION_QUESTION, PRECAUTION_QUESTION, DIET_QUESTION,
    HOME_CARE_QUESTION, RECOVERY_QUESTION, SEVERITY_QUESTION,
    CAUSE_QUESTION, DURATION_QUESTION, QUESTION_ABOUT_CONDITION — independent
    of whatever else is going on in the conversation (a pending question, an
    established condition, or neither). Returns None if it doesn't match
    any of them. All of these route through the same contextual-answer
    capability in orchestrator.py; they're kept as separate intents only so
    the right deterministic fallback and framing is picked when Gemini is
    unavailable, not because each needs its own handling logic."""
    if _MEDICATION_RE.search(stripped):
        return "MEDICATION_QUESTION"
    if _SEVERITY_RE.search(stripped) or _DOCTOR_RE.search(stripped):
        return "SEVERITY_QUESTION"
    if _PRECAUTION_RE.search(stripped):
        return "PRECAUTION_QUESTION"
    if _DIET_RE.search(stripped):
        return "DIET_QUESTION"
    if _HOME_CARE_RE.search(stripped):
        return "HOME_CARE_QUESTION"
    if _RECOVERY_RE.search(stripped):
        return "RECOVERY_QUESTION"
    if _CAUSE_RE.search(stripped):
        return "CAUSE_QUESTION"
    if _DURATION_RE.search(stripped):
        return "DURATION_QUESTION"
    if _CONDITION_QUESTION_RE.search(stripped):
        return "QUESTION_ABOUT_CONDITION"
    return None


def _fallback_classify(text, state, vocab_names, local_symptoms):
    stripped = text.strip()
    pending_symptom = state.get("pending_symptom_question")
    pending_history = state.get("pending_history_slot")

    # An explicit restart always wins, even mid-question — the user is
    # allowed to abandon whatever was pending.
    if _RESTART_RE.search(stripped):
        return "RESTART"

    if pending_symptom:
        # A *different*, explicitly named symptom takes priority over
        # reading this as a plain yes/no reply to the one pending question
        # — otherwise "I also have a fever" (while "breathlessness?" is
        # pending) gets misread as answering the breathlessness question
        # instead of volunteering a new one.
        other_symptoms_named = [s for s in local_symptoms if s != pending_symptom]
        if other_symptoms_named:
            return "NEW_SYMPTOM"
        if _yes_no(stripped) is not None:
            return "SYMPTOM_ANSWER"

    # A pending open history question (duration/severity/onset) usually
    # just gets answered directly — but the user can also interrupt it
    # with an unrelated question ("Does the pain get worse after eating?"
    # / "What medicine should I take?") and that has to be recognized as
    # such rather than force-fit as the history answer. Gated on the text
    # actually looking like a question (or unambiguously being about
    # medication) so an ordinary answer like "it's pretty severe" doesn't
    # get misread as a new SEVERITY_QUESTION just because it contains the
    # word "severe". A genuinely new symptom mentioned here ("also I have
    # vomiting") still needs to fall through to NEW_SYMPTOM below rather
    # than being swallowed as the history answer.
    if pending_history and not local_symptoms:
        if _MEDICATION_RE.search(stripped):
            return "MEDICATION_QUESTION"
        if _QUESTION_LEAD_RE.search(stripped):
            interrupting = _classify_interruption(stripped)
            if interrupting:
                return interrupting
        return "HISTORY_ANSWER"

    if _GREETING_RE.search(stripped):
        return "GREETING"

    if CASUAL_RE.match(stripped) or _AFFECTION_RE.search(stripped):
        return "CASUAL"

    if local_symptoms:
        # A message that both names a symptom and is clearly phrased as a
        # question ("Why does fever happen?") is read as the question, not
        # a fresh symptom report — an ordinary assertion ("I have fever")
        # isn't question-shaped and falls through to NEW_SYMPTOM as usual.
        # A real symptom always wins over a pregnancy mention in the same
        # message ("I'm pregnant and have severe abdominal pain" still
        # reports abdominal_pain) — PREGNANCY is only reached below when
        # no actual symptom was recognized.
        if _QUESTION_LEAD_RE.search(stripped):
            interrupting = _classify_interruption(stripped)
            if interrupting:
                return interrupting
        # Only the pending symptom itself was named (e.g. restating "yes,
        # breathlessness") — the pending_symptom branch above would have
        # caught anything genuinely new.
        return "SYMPTOM_ANSWER" if pending_symptom else "NEW_SYMPTOM"

    # Pregnancy is its own conversational domain, not a symptom or a
    # disease to match against — checked before the generic interruption
    # patterns so "what is pregnancy?" / "pregnant symptoms" are read as
    # PREGNANCY rather than a generic QUESTION_ABOUT_CONDITION with no
    # resolvable disease.
    if _PREGNANCY_RE.search(stripped):
        return "PREGNANCY"

    interrupting = _classify_interruption(stripped)
    if interrupting:
        return interrupting

    if state.get("current_primary_condition") and "?" in stripped:
        return "FOLLOW_UP_RESULT"

    return "UNCLEAR"


def _is_intent_shape(data):
    return isinstance(data, dict) and isinstance(data.get("intent"), str)


def classify(text, state, vocab_names, local_symptoms):
    """Returns one of INTENTS. `local_symptoms` is the already-computed
    local keyword-match result for `text` (chat.py runs this regardless, so
    it's passed in rather than recomputed here)."""
    fallback = _fallback_classify(text, state, vocab_names, local_symptoms)

    if not is_available():
        return fallback

    context = (
        f"Conversation stage: {state.get('conversation_stage')}. "
        f"Currently discussing (primary possible condition, if any): "
        f"{state.get('current_primary_condition') or 'none yet'}. "
        f"Other possible conditions mentioned: "
        f"{', '.join(state.get('current_possible_conditions') or []) or 'none'}. "
        f"Chief complaint so far: {state.get('chief_complaint') or 'none yet'}. "
        f"Currently waiting on an answer about: "
        f"{state.get('pending_symptom_question') or state.get('pending_history_slot') or 'nothing specific'}."
    )
    prompt = (
        "Classify the user's message in a medical symptom-checker chat into exactly one "
        f"of these intents: {', '.join(INTENTS)}.\n\n"
        f"{context}\n\n"
        f'User message: "{text}"\n\n'
        'Return strict JSON of the shape {"intent": "<ONE_OF_THE_INTENTS>"}. '
        "If the user is answering a yes/no question that was just asked, use SYMPTOM_ANSWER "
        "(for a symptom) or HISTORY_ANSWER (for duration/severity/onset). If they're describing "
        "a new symptom, use NEW_SYMPTOM. Casual, affectionate, or relationship-toned messages "
        "('I love you', 'baby', small talk) that don't describe a symptom are CASUAL, never a "
        "symptom — do not guess a symptom out of them. Messages about pregnancy (including "
        "misspellings like 'pregnent') that don't also report an actual symptom are PREGNANCY. "
        "Only use NEW_SYMPTOM when the message actually names or describes a bodily symptom. "
        "If genuinely unsure what the user means and it isn't clearly one of the above, use "
        "UNCLEAR — never guess NEW_SYMPTOM just because nothing else fits."
    )
    data = generate_json(prompt, fallback=None, validator=_is_intent_shape)
    if isinstance(data, dict):
        intent = data.get("intent")
        if intent in INTENTS:
            return intent
    return fallback
