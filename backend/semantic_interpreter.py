"""Semantic interpretation layer — decides what a message MEANS in context,
sitting between raw text and orchestrator.py's dispatch.

    USER MESSAGE
         |
         v
    interpret()  (this module)
         |
         v
    Conversation Orchestrator (orchestrator.py) — decides what to DO about
    the meaning: which response capability to call, whether to touch the
    disease engine, etc.

Root problem this module addresses: `intent_classifier.classify` returns a
single flat bucket string. That's enough to say *what kind* of message this
is, but not *why* — e.g. it can say a message doesn't answer the pending
duration question, but has no way to also say "and it mentions a new
symptom" or "and the user says things are getting worse" at the same time.
Every time a real conversation exposed that gap, the fix so far has been
one more regex or one more special-cased branch bolted onto
orchestrator.py's handle_message() (see its own module docstring / git
history). This module doesn't replace that classifier — it wraps it and
adds the extra structured signals orchestrator.py actually needs, computed
once per turn, so a new phrasing generalizes instead of needing its own
patch.

Deliberately NOT a rewrite of intent_classifier.py: `_fallback_classify`
there is already a solid, tested, deterministic decision tree (pending-
question gating, greeting/casual/affection, feeling-better, symptom-vs-
question disambiguation, pregnancy, interruption classification) — it's
imported and reused as the backbone of this module's own no-LLM fallback,
not reimplemented. `intent_classifier.classify`/`INTENTS`/`CASUAL_RE` are
untouched and still independently used/tested elsewhere.

This module does NOT extract or validate symptom names — that stays
exactly where it already was (orchestrator.py's `_extract_symptoms_with_negation`
/ `_gemini_extract_structured`, backed by negation.py's deterministic
clause splitter, with anything outside the real Symptom vocabulary
discarded). This module only tells the orchestrator *whether* a message
should trigger that extraction (via `meaning`), which keeps the
"LLM-proposed medical facts are never trusted directly, only after
deterministic validation" boundary in exactly one place — see that
function's own docstring and the test that poisons it directly,
`test_disease_expansion.py::test_gemini_output_cannot_change_the_ranking_decision`.
"""

import re

import intent_classifier as ic
from gemini_client import generate_json, is_available

# Every value `meaning` can take: the existing flat intent vocabulary
# (still meaningful and still what most turns resolve to) plus two new
# ones this module adds because there was previously no bucket for them at
# all. Deliberately not a bigger new taxonomy — see this module's
# docstring: most of the spec's "health_question" style examples already
# resolve correctly today via the existing QUESTION_ABOUT_CONDITION/
# CAUSE_QUESTION/etc. intents (verified by tracing them), so there's
# nothing to add there.
MEANINGS = frozenset(ic.INTENTS) | {"SYMPTOMS_WORSENING", "EMOTIONAL_CONCERN"}

# Moved here from orchestrator.py (not duplicated) — these decide whether a
# message actually looks like an attempt to answer a pending duration/
# severity/onset question, as opposed to something else entirely that
# happens to arrive while one is pending. See _fallback_interpret's
# docstring for why this can no longer be the *only* thing gating whether
# new symptom content in the same message gets noticed.
_DURATION_ONSET_CUE_RE = re.compile(
    r"\d|day|week|month|year|hour|minute|since|ago|yesterday|today|"
    r"morning|evening|night|now|sudden|gradual|start|began|"
    r"few|couple|while|long time|on and off|forever", re.I
)
_SEVERITY_CUE_RE = re.compile(
    r"\d|mild|moderate|severe|worse|worst|manageable|unbearable|scale|out of", re.I
)

# A small, curated set for "getting worse" language — same spirit and same
# size class as intent_classifier._FEELING_BETTER_RE, which this mirrors.
# Independent of (and checked alongside, not instead of) whatever `meaning`
# ends up being — see _fallback_interpret: a message can both report a new
# symptom AND indicate worsening at once, and both signals are kept.
_WORSENING_RE = re.compile(
    r"\b(getting worse|got worse|worse (?:today|now|than before|than yesterday)|"
    r"worsening|much worse|(?:pain|symptoms?) (?:is|are|feels?) (?:getting |growing )?"
    r"(?:worse|stronger)|"
    r"still (?:getting )?worse|not (?:getting )?any better|worse and worse|"
    r"more severe (?:now|than before))\b"
    # "X's back"/"X is back"/"X are back" — generic enough to catch "the
    # fever's back"/"the pain is back", not just a literal "it's back".
    r"|'s back\b|\bis back\b|\bare back\b|\bcame back\b|\bcoming back\b",
    re.I,
)


def _looks_like_pending_history_answer(slot, text):
    if slot == "severity":
        return bool(_SEVERITY_CUE_RE.search(text))
    return bool(_DURATION_ONSET_CUE_RE.search(text))


def _answers_pending_deterministic(state, stripped):
    """Does this message look like an attempt to answer whatever's
    currently pending (a history slot OR a yes/no symptom question)? False
    if nothing is pending. This is advisory, not exclusive — the
    orchestrator still independently checks for new symptom content
    regardless of this value (see orchestrator.py's HISTORY_ANSWER
    branch), so a wrong guess here only affects phrasing, never loses
    information."""
    pending_history = state.get("pending_history_slot")
    if pending_history:
        return _looks_like_pending_history_answer(pending_history, stripped)
    if state.get("pending_symptom_question"):
        return ic._yes_no(stripped) is not None
    return False


def _reconcile(meaning, answers_pending, stripped):
    """A message can only genuinely be HISTORY_ANSWER/SYMPTOM_ANSWER if it
    actually reads as an attempt to answer what's pending. Both
    intent_classifier._fallback_classify and the LLM prompt use
    HISTORY_ANSWER as their own catch-all for "something's pending and
    nothing more specific matched" — which is right for a genuinely
    odd-but-real answer ("since forever", "I don't know"), but wrong for a
    message that's actually a *question* ("What should I tell my
    doctor?") that just happened to arrive while a slot was pending. Only
    a question-shaped message is downgraded here (to the safe, generic
    UNCLEAR bucket, which still preserves the pending-question reminder
    via orchestrator.py's _with_pending_reminder) — a non-question,
    non-answer message like "I'm scared." still falls through to the
    original "store it anyway" floor, matching this app's pre-existing,
    documented behavior for a genuinely ambiguous free-text answer.
    Applied uniformly to both the deterministic fallback and the LLM
    result (see interpret()), so a classification that's internally
    inconsistent — HISTORY_ANSWER, but also says this doesn't actually
    answer the pending question, and reads as a question itself — is
    never trusted from either source."""
    if meaning == "HISTORY_ANSWER" and not answers_pending and ic._QUESTION_LEAD_RE.search(stripped):
        return "UNCLEAR"
    return meaning


def _fallback_interpret(text, state, vocab_names, local_symptoms):
    """The no-LLM floor — what every existing test exercises (conftest.py
    sets GEMINI_API_KEY="" for the whole suite), so this has to be
    genuinely serviceable on its own, not a token stub. Built as a strict
    superset of intent_classifier._fallback_classify's decisions: same
    regexes, same precedence, just exposed as structured fields instead of
    a single string, plus the new worsening signal."""
    stripped = text.strip()
    meaning = ic._fallback_classify(text, state, vocab_names, local_symptoms)
    answers_pending = _answers_pending_deterministic(state, stripped)
    meaning = _reconcile(meaning, answers_pending, stripped)

    worsening = bool(_WORSENING_RE.search(stripped))
    improving = bool(ic._FEELING_BETTER_RE.search(stripped))
    # Only override when the base classifier found nothing more specific —
    # a message that's already NEW_SYMPTOM (e.g. "the fever's back and I
    # have chills") keeps that routing so the actual new symptom still
    # reaches the disease engine; worsening is still recorded as an
    # independent flag either way.
    if worsening and meaning == "UNCLEAR":
        meaning = "SYMPTOMS_WORSENING"

    topic = state.get("chief_complaint") or state.get("current_primary_condition")

    return {
        "meaning": meaning,
        "answers_pending_question": answers_pending,
        "user_reported_improvement": improving,
        "user_reported_worsening": worsening,
        "topic": topic,
        "confidence": None,
    }


def _is_interpretation_shape(data):
    if not isinstance(data, dict):
        return False
    if data.get("meaning") not in MEANINGS:
        return False
    return all(
        isinstance(data.get(key), bool)
        for key in ("answers_pending_question", "user_reported_improvement", "user_reported_worsening")
    )


def _context_block(state):
    return (
        f"Conversation stage: {state.get('conversation_stage')}. "
        f"Currently discussing (primary possible condition, if any): "
        f"{state.get('current_primary_condition') or 'none yet'}. "
        f"Other possible conditions mentioned: "
        f"{', '.join(state.get('current_possible_conditions') or []) or 'none'}. "
        f"Chief complaint so far: {state.get('chief_complaint') or 'none yet'}. "
        f"Currently waiting on an answer about: "
        f"{state.get('pending_symptom_question') or state.get('pending_history_slot') or 'nothing specific'}. "
        f"Conversation summary so far: {state.get('conversation_summary') or 'none yet'}. "
        f"Current topic: {state.get('current_topic') or 'none yet'}."
    )


def interpret(text, state, vocab_names, local_symptoms):
    """Returns a structured interpretation of `text` in context — see this
    module's docstring for the shape and rationale. Always returns a fully
    populated dict; falls back to `_fallback_interpret` whenever the LLM
    gateway is unavailable or its response fails shape validation, so the
    caller never has to special-case "no provider configured"."""
    fallback = _fallback_interpret(text, state, vocab_names, local_symptoms)

    if not is_available():
        return fallback

    prompt = (
        "You are the semantic interpretation layer for Healora, a medical symptom-checker "
        "chat. Interpret what the user's latest message MEANS, in context — never in "
        "isolation. The same words can mean different things depending on what was just "
        f"asked.\n\n{_context_block(state)}\n\n"
        f'User message: "{text}"\n\n'
        "Return strict JSON of exactly this shape: "
        '{"meaning": "<one value>", "answers_pending_question": true|false, '
        '"user_reported_improvement": true|false, "user_reported_worsening": true|false, '
        '"topic": "<short label or null>", "confidence": <number 0-1>}.\n\n'
        f"Allowed meaning values: {', '.join(sorted(MEANINGS))}.\n\n"
        "Guidance:\n"
        "- answers_pending_question is true only if this message actually attempts to "
        "answer whatever is currently pending (see context above). If the user changed "
        "the subject, reported a different symptom, or said something else entirely "
        "instead, this must be false — even if the pending question was never actually "
        "answered.\n"
        "- Use NEW_SYMPTOM whenever the message names or describes a bodily symptom, even "
        "alongside answering a pending question or reporting improvement/worsening — a "
        "symptom mention always takes priority over other meanings.\n"
        "- Use SYMPTOMS_WORSENING when the user says symptoms are getting worse, came "
        "back, or are more severe than before, and no actual new symptom is named.\n"
        "- Use FEELING_BETTER when symptoms are described as eased, resolved, or gone.\n"
        "- user_reported_improvement/user_reported_worsening are independent flags — set "
        "them whenever the message says so, regardless of what `meaning` ends up being.\n"
        "- Use EMOTIONAL_CONCERN for fear/worry/anxiety about their situation with no new "
        "medical content.\n"
        "- Casual, affectionate, or relationship-toned messages ('I love you', 'baby') "
        "that don't describe a symptom are CASUAL, never a symptom.\n"
        "- Messages about pregnancy (including misspellings like 'pregnent') that don't "
        "also report an actual symptom are PREGNANCY.\n"
        "- Do not default to HISTORY_ANSWER or SYMPTOM_ANSWER just because something is "
        "pending. A question ('What should I tell my doctor?'), a request, or an "
        "emotional statement that arrives while something is pending is NOT an answer to "
        "it, even a bad one — use whatever meaning actually fits the message (a QUESTION "
        "value, EMOTIONAL_CONCERN, CASUAL, etc.) with answers_pending_question false. "
        "Only use HISTORY_ANSWER/SYMPTOM_ANSWER when the message plausibly attempts to "
        "answer the pending question, even vaguely ('I don't know', 'on and off').\n"
        "- If genuinely unsure, use UNCLEAR — never guess NEW_SYMPTOM just because "
        "nothing else fits."
    )
    data = generate_json(prompt, fallback=None, validator=_is_interpretation_shape)
    if not isinstance(data, dict):
        return fallback

    topic = data.get("topic")
    confidence = data.get("confidence")
    answers_pending = bool(data["answers_pending_question"])
    # Same consistency check applied to the deterministic fallback (see
    # _reconcile's docstring) — the LLM is guided against this in the
    # prompt above, but its output is never trusted uncritically, same as
    # every other LLM-proposed fact in this app.
    meaning = _reconcile(data["meaning"], answers_pending, text.strip())
    return {
        "meaning": meaning,
        "answers_pending_question": answers_pending,
        "user_reported_improvement": bool(data["user_reported_improvement"]),
        "user_reported_worsening": bool(data["user_reported_worsening"]),
        "topic": topic if isinstance(topic, str) and topic.strip() else fallback["topic"],
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
    }
