import json
import logging
import random
import re

from flask import Blueprint, jsonify, request

import conversation_state as cs
import disease_matcher
import history_taking
import negation
import profile_extraction
import symptom_engine
from auth import optional_token
from data.ambiguous_terms import find_clarification
from emergency import EMERGENCY_MESSAGE, detect_emergency
from extensions import db
from gemini_client import generate_json, generate_text, is_available
from health_tips import get_daily_tip
from intent_classifier import classify as classify_intent
from models import ChatMessage, Disease

chat_bp = Blueprint("chat", __name__, url_prefix="/api")

logger = logging.getLogger(__name__)

GREETING_INPUTS = ("hello", "hi", "greetings", "sup", "what's up", "hey", "start", "checkup")
GREETING_RESPONSES = [
    "Hello! I'm here to help you understand your symptoms. How are you feeling today?",
    "Hi there! I'm your Healora AI assistant. Please tell me what's bothering you.",
    "Greetings! Let's perform a quick health assessment. What symptoms are you experiencing?",
    "Hello! I'm ready to help. Feel free to describe your symptoms in your own words.",
]

_GREETING_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in GREETING_INPUTS) + r")\b"
)

NO_MATCH_MESSAGE = (
    "I want to understand that a little better. Could you describe what you're "
    "feeling — where it is, how it started, or what it feels like?"
)

MEDICATION_GUARDRAIL_MESSAGE = (
    "I can share general educational information, but I don't have verified "
    "medication or dosage information for your situation — Healora's database "
    "doesn't include treatment data, so I won't guess. A doctor or pharmacist "
    "can recommend the right treatment based on your symptoms and history."
)

RESTART_MESSAGE = "Sure — let's start fresh. What's bothering you today?"

# A distinct, narrower system instruction from HEALORA_SYSTEM_INSTRUCTION:
# general health-education questions ("Why does fever happen?", "What
# should I do for dehydration?") aren't about a specific Disease/Symptom
# row Healora has facts for, so the usual "never state anything not given
# to you in the prompt's data" rule would make Gemini refuse to answer at
# all. This scopes it down instead: well-established, textbook-level
# health education only, never a diagnosis, medication name, or dosage.
GENERAL_HEALTH_SYSTEM_INSTRUCTION = (
    "You are the language layer for Healora, an educational health-support "
    "assistant. You are NOT a doctor and this is NOT a diagnostic tool. The "
    "user has asked a general health-education question that is not about "
    "their own specific symptoms. Hard rules, no exceptions:\n"
    "1. Only state well-established, textbook-level general medical/health "
    "education facts (e.g. why fevers occur, what dehydration is, general "
    "prevention advice). Do not state anything uncertain or controversial.\n"
    "2. Never recommend, name, or dose a specific medication.\n"
    "3. Never diagnose the user or suggest what condition they personally "
    "have — you were not given any information about their symptoms here.\n"
    "4. Keep it concise (2-4 sentences) and end by noting a doctor or "
    "pharmacist can give guidance specific to their situation.\n"
    "5. If the question isn't something you can answer with well-established "
    "general knowledge, say plainly that you don't have verified "
    "information on that rather than guessing."
)

GENERAL_HEALTH_FALLBACK = (
    "I don't have verified information on that specific question yet — a "
    "doctor or pharmacist would be able to give you accurate guidance. "
    "Would you like to tell me about any symptoms you're experiencing instead?"
)

_CASUAL_RESPONSES = [
    "You're welcome — I'm here if anything else comes up.",
    "Glad I could help. Let me know if anything changes or you think of something else.",
    "Anytime. Take care of yourself, and reach out if you need anything else.",
]


# ---------------------------------------------------------------------------
# Greeting / small talk
# ---------------------------------------------------------------------------


def _is_greeting(text):
    return bool(_GREETING_PATTERN.search(text))


# ---------------------------------------------------------------------------
# Symptom extraction (local + Gemini, merged) — unchanged from the original
# single-turn pipeline, just factored out.
# ---------------------------------------------------------------------------


def _is_structured_symptom_shape(data):
    if not isinstance(data, dict):
        return False
    items = data.get("symptoms")
    if not isinstance(items, list):
        return False
    return all(
        isinstance(it, dict) and isinstance(it.get("name"), str) and isinstance(it.get("present"), bool)
        for it in items
    )


def _gemini_extract_structured(user_input, vocab_names):
    """Ask Gemini which known symptoms a free-text message asserts, and
    whether each is present or explicitly denied — the structured shape
    lets Gemini contribute to negation handling instead of only ever
    reporting "mentioned". Gemini's output is advisory only: anything it
    returns that isn't a real Symptom.name is discarded here, never
    trusted or written to the database — see the "Gemini boundary" note in
    gemini_client.py. It's also never the final word on negation for a
    symptom the deterministic clause-based extractor (negation.py) already
    found — see the merge in the main route.
    """
    vocab_str = ", ".join(vocab_names)
    prompt = (
        "You are a symptom-extraction component inside a medical symptom-checker app.\n"
        "Known symptom vocabulary (respond using ONLY these exact strings, "
        f"underscored form): {vocab_str}\n\n"
        f'User message: "{user_input}"\n\n'
        'Return strict JSON of the shape {"symptoms": [{"name": "<vocab_item>", '
        '"present": true|false}, ...]}. Include an item for every vocabulary symptom '
        'the message clearly asserts as present OR explicitly denies (e.g. "no cough" '
        '-> {"name": "cough", "present": false}). Do not include a symptom the message '
        "doesn't mention at all, and do not invent items outside the vocabulary."
    )
    data = generate_json(prompt, fallback=None, validator=_is_structured_symptom_shape)
    if not isinstance(data, dict):
        return []
    items = data.get("symptoms") or []

    valid = set(vocab_names)
    result = []
    unresolved = []
    for item in items:
        name = item.get("name")
        if name in valid:
            result.append((name, bool(item.get("present"))))
        else:
            unresolved.append(name)
    if unresolved:
        # Gemini named something outside the canonical Symptom vocabulary —
        # discarded, not inserted anywhere. Logged so an unusually common
        # unresolved phrase can inform a future alias/data addition.
        logger.info("Discarded unresolved symptom candidates from Gemini: %r", unresolved)

    return result


def _extract_symptoms_with_negation(user_input, vocab_names):
    """Merges the deterministic, clause-based negation splitter with
    Gemini's structured (advisory) extraction. The local extractor is
    authoritative for any symptom it found at all — Gemini only fills in
    symptoms local extraction missed entirely — so behavior never regresses
    when GEMINI_API_KEY is unset, which every test in this codebase (and
    plenty of real deployments) runs with.

    Returns (positive_symptoms, negative_symptoms), both sorted lists of
    canonical symptom names.
    """
    local_positive, local_negative = negation.split_negated_symptoms(user_input)
    local_found = set(local_positive) | set(local_negative)

    gemini_pairs = _gemini_extract_structured(user_input, vocab_names) if user_input else []
    gemini_positive = {name for name, present in gemini_pairs if present} - local_found
    gemini_negative = {name for name, present in gemini_pairs if not present} - local_found - gemini_positive

    return (
        sorted(set(local_positive) | gemini_positive),
        sorted(set(local_negative) | gemini_negative),
    )


# ---------------------------------------------------------------------------
# Gemini-phrased question / result text (unchanged behavior for symptom
# yes/no questions and results — only factored to also serve history
# questions).
# ---------------------------------------------------------------------------


def _phrase_symptom_question(raw_symptom, confirmed_symptoms, fallback_text):
    readable = raw_symptom.replace("_", " ")
    confirmed = ", ".join(s.replace("_", " ") for s in confirmed_symptoms) or "none yet"
    prompt = (
        "You are conducting a symptom check for the user. They have already confirmed "
        f"having: {confirmed}. Ask them, in one short natural sentence ending in \"?\", "
        f'whether they also have this symptom: "{readable}". Output only the question, '
        "nothing else."
    )
    return generate_text(prompt, fallback=fallback_text)


def _phrase_history_question(slot, state, fallback_text):
    complaint = (state.get("chief_complaint") or "").replace("_", " ")
    prompt = (
        "You are taking a brief medical history from a user in a symptom-checker chat. "
        f"Their main complaint is: {complaint or 'not yet specified'}. "
        f'Ask them, in one short empathetic sentence ending in "?", about the {slot} of '
        "this complaint. Output only the question, nothing else."
    )
    return generate_text(prompt, fallback=fallback_text)


_ENRICHMENT_LABELS = [
    ("causes", "Causes"),
    ("risk_factors", "Risk factors"),
    ("prevention", "Prevention"),
    ("when_to_see_doctor", "When to see a doctor"),
    ("emergency_warning_signs", "Emergency warning signs"),
    ("management", "General management"),
    ("age_sex_notes", "Age/sex notes"),
]


def _facts_block(disease_row):
    facts = disease_row.to_dict(include_enrichment=True)
    lines = [
        f"- Name: {facts['name']}",
        f"- Standard description: {facts['description'] or 'not available'}",
        f"- Severity category: {facts['severity']}",
    ]
    for key, label in _ENRICHMENT_LABELS:
        if facts.get(key):
            lines.append(f"- {label}: {facts[key]}")
    return facts, "\n".join(lines)


def _phrase_result(disease_row, match_strength, symptoms_present_list, possible_conditions, history_snippet, state):
    confirmed = ", ".join(symptoms_present_list) or "the symptoms you described"
    facts, facts_block = _facts_block(disease_row)

    other_names = [c["name"] for c in possible_conditions if c["name"] != disease_row.name][:4]
    other_line = (
        f"\nOther possibilities the system also flagged (lower match): {', '.join(other_names)}"
        if other_names
        else ""
    )
    history_line = (
        f"\nThis user's recent chat history (context, may be empty): {history_snippet}"
        if history_snippet
        else ""
    )
    hx_bits = []
    if state.get("duration"):
        hx_bits.append(f"duration: {state['duration']}")
    if state.get("severity"):
        hx_bits.append(f"self-rated severity: {state['severity']}/10")
    if state.get("onset"):
        hx_bits.append(f"onset: {state['onset']}")
    hx_line = f"\nHistory the user gave: {'; '.join(hx_bits)}" if hx_bits else ""

    allowed_names = ", ".join([facts["name"]] + other_names)
    prompt = (
        "A separate deterministic symptom-matching system (not you) queried Healora's "
        "database and determined these structured facts about the top candidate "
        f"condition:\n{facts_block}\n"
        f"Match strength: {match_strength} (qualitative — never restate this as a "
        f"percentage or probability).\n"
        f"Confirmed symptoms: {confirmed}{hx_line}{other_line}{history_line}\n\n"
        "Using ONLY the facts above — do not add any medical claim, cause, treatment, "
        "or condition that isn't in them — write a short (3-5 sentence), empathetic "
        "explanation of this result for the user, in natural prose. Refer to it as a "
        "possible condition to discuss with a doctor, never a confirmed diagnosis. The "
        f"ONLY condition names you may mention anywhere in your reply are: {allowed_names}. "
        "Do not name any other disease or condition, even a common or seemingly obvious "
        "one. If other possibilities were listed, briefly note they're also worth "
        "discussing with a doctor. End by reinforcing this is educational guidance, not "
        "a diagnosis."
    )
    fallback = facts["description"] or "Please consult a medical professional for more details."
    return generate_text(prompt, fallback=fallback)


# ---------------------------------------------------------------------------
# Follow-up question answering (after a result has been shown) — grounded
# only in the specific Disease row's own stored fields. Gemini phrases the
# answer; it never supplies the facts. See "The Gemini boundary" in
# README.md.
# ---------------------------------------------------------------------------


def _find_named_condition(message):
    """Best-effort: does the message explicitly name a disease in our
    database? Longest names checked first so e.g. "common cold" wins over
    a shorter, coincidentally-matching substring."""
    lower = message.lower()
    names = [d.name for d in Disease.query.with_entities(Disease.name).all()]
    for name in sorted(names, key=len, reverse=True):
        if len(name) > 3 and name.lower() in lower:
            return disease_matcher.get_disease_by_name(name)
    return None


def _resolve_followup_target(message, state):
    named = _find_named_condition(message)
    if named is not None:
        return named
    primary = state.get("current_primary_condition")
    if primary:
        return disease_matcher.get_disease_by_name(primary)
    return None


def _followup_fallback(intent, disease_row):
    facts = disease_row.to_dict(include_enrichment=True)
    if intent == "CAUSE_QUESTION":
        return facts.get("causes") or (
            f"Healora doesn't have verified cause information for {facts['name']} yet — "
            "that's a good question to bring to a doctor."
        )
    if intent == "PRECAUTION_QUESTION":
        return facts.get("prevention") or facts.get("management") or (
            "Healora doesn't have verified precaution guidance for this yet — a doctor "
            "or pharmacist can advise on what's safe for your situation."
        )
    if intent == "DURATION_QUESTION":
        return (
            "Healora doesn't have verified typical-duration data — this varies a lot by "
            "person, and a doctor can give you a better estimate based on your specific "
            "situation."
        )
    if intent == "SEVERITY_QUESTION":
        severity = facts["severity"]
        warning = facts.get("emergency_warning_signs")
        base = (
            f"Based on Healora's data, {facts['name']} is generally categorized as "
            f"{severity} severity."
        )
        if warning:
            base += f" Warning signs worth knowing: {warning}."
        base += " This isn't a personal risk assessment — if you're worried, please contact a healthcare professional."
        return base
    if intent == "QUESTION_ABOUT_CONDITION":
        return facts["description"] or "Healora doesn't have a verified description for this yet."
    # FOLLOW_UP_RESULT / general "what should I do" / "should I see a doctor"
    return facts.get("when_to_see_doctor") or (
        "It's a good idea to discuss these symptoms with a healthcare professional, "
        "especially if they're severe, persistent, or getting worse."
    )


def _answer_followup(intent, message, disease_row, state):
    fallback = _followup_fallback(intent, disease_row)
    _facts, facts_block = _facts_block(disease_row)
    prompt = (
        "A user in a medical symptom-checker chat is asking a follow-up question about a "
        "possible condition that a separate deterministic system already identified. Here "
        f"are the ONLY verified facts you may use:\n{facts_block}\n\n"
        f'Their question: "{message}"\n\n'
        "Using ONLY the facts above — never invent a cause, medication, dosage, treatment, "
        "statistic, or fact that isn't listed — answer in 2-4 warm, concise sentences. If "
        "the facts don't cover what they're asking, say plainly that Healora doesn't have "
        "verified information on that specific point rather than guessing, and suggest a "
        "doctor or pharmacist. Never state this as a confirmed diagnosis. Never name any "
        f"condition other than {disease_row.name}."
    )
    return generate_text(prompt, fallback=fallback)


# ---------------------------------------------------------------------------
# History taking (duration / severity / onset)
# ---------------------------------------------------------------------------


def _ask_history_question(state):
    slot = cs.next_history_slot(state)
    state["pending_history_slot"] = slot
    state["pending_symptom_question"] = None
    state["conversation_stage"] = "HISTORY_TAKING"
    fallback_text = history_taking.question_for_slot(slot)
    question_text = _phrase_history_question(slot, state, fallback_text) if is_available() else fallback_text
    state.setdefault("questions_asked", []).append(question_text)
    return {
        "type": "question",
        "symptom": question_text,
        "raw_symptom": None,
        "answer_mode": "open",
    }


def _pending_question_reminder(state):
    """Plain-text reminder of whatever question was pending before the user
    interrupted with something else (a medication question, an unrelated
    "what is X" question, ...) — so answering the interruption doesn't
    silently drop the conversation's thread. See the "Bot: does the pain
    get worse after eating? / User: what medicine should I take?" example
    this is built for."""
    if state.get("pending_history_slot"):
        return history_taking.question_for_slot(state["pending_history_slot"])
    if state.get("pending_symptom_question"):
        return state["pending_symptom_question"].replace("_", " ") + "?"
    return None


def _with_pending_reminder(message, state):
    reminder = _pending_question_reminder(state)
    if not reminder:
        return message
    return f"{message}\n\nGoing back to what I asked — {reminder}"


def _build_summary_fallback(state, symptoms_present_list, symptoms_denied_list):
    bits = []
    if state.get("chief_complaint"):
        bits.append(f"chief complaint: {state['chief_complaint'].replace('_', ' ')}")
    if state.get("duration"):
        bits.append(f"duration: {state['duration']}")
    if state.get("severity"):
        bits.append(f"severity: {state['severity']}")
    if state.get("onset"):
        bits.append(f"onset: {state['onset']}")
    if symptoms_present_list:
        bits.append(f"reported: {', '.join(symptoms_present_list)}")
    if symptoms_denied_list:
        bits.append(f"denied: {', '.join(symptoms_denied_list)}")
    return ("Summary — " + "; ".join(bits) + ".") if bits else "No details captured yet."


def _phrase_summary(state, symptoms_present_list, symptoms_denied_list, fallback_text):
    prompt = (
        "Summarize this user's reported medical history in 1-2 short, warm "
        "sentences, using ONLY the facts below — do not add anything not listed "
        "here, and do not name any condition:\n"
        f"- Chief complaint: {state.get('chief_complaint') or 'not specified'}\n"
        f"- Duration: {state.get('duration') or 'not specified'}\n"
        f"- Severity: {state.get('severity') or 'not specified'}\n"
        f"- Onset: {state.get('onset') or 'not specified'}\n"
        f"- Symptoms present: {', '.join(symptoms_present_list) or 'none'}\n"
        f"- Symptoms explicitly denied: {', '.join(symptoms_denied_list) or 'none'}\n"
        "Output only the summary sentence(s), nothing else."
    )
    return generate_text(prompt, fallback=fallback_text)


def _answer_general_health_question(user_input):
    prompt = (
        "Answer this general health-education question in plain, warm "
        f'language: "{user_input}"'
    )
    return generate_text(
        prompt,
        fallback=GENERAL_HEALTH_FALLBACK,
        system_instruction=GENERAL_HEALTH_SYSTEM_INSTRUCTION,
    )


# ---------------------------------------------------------------------------
# Continuing the deterministic symptom-matching flow (disease_matcher) —
# this is the same engine as before, just now also updating conversation
# state and choosing between a history question, a symptom question, or a
# result.
# ---------------------------------------------------------------------------


def _continue_matching(answers, state, user):
    # Fresh chief complaint: take a brief history before falling through to
    # disease_matcher's yes/no symptom questions, so the conversation
    # doesn't jump straight to a result card off one message. Subsequent
    # complaints raised later in the same conversation skip straight to the
    # matcher (see conversation_state.start_new_complaint / its call site).
    if state.get("chief_complaint") and cs.next_history_slot(state) is not None:
        return {
            "message": None,
            "next_step": _ask_history_question(state),
            "answers": answers,
            "state": state,
            "emergency": False,
        }

    next_step = disease_matcher.get_next_step(answers)

    if next_step is None:
        return {
            "message": NO_MATCH_MESSAGE,
            "next_step": {"type": "waiting"},
            "answers": answers,
            "state": state,
            "emergency": False,
        }

    if next_step["type"] == "question":
        next_step["answer_mode"] = "yes_no"
        state["pending_symptom_question"] = next_step["raw_symptom"]
        state["pending_history_slot"] = None
        state["conversation_stage"] = "SYMPTOM_CLARIFICATION"
        if is_available():
            confirmed = [a[0] for a in answers if a[1]]
            next_step["symptom"] = _phrase_symptom_question(
                next_step["raw_symptom"], confirmed, next_step["symptom"]
            )
        state.setdefault("questions_asked", []).append(next_step["symptom"])
    elif next_step["type"] == "result":
        state["pending_symptom_question"] = None
        state["pending_history_slot"] = None
        state["conversation_stage"] = "FOLLOW_UP"
        state["current_primary_condition"] = next_step["disease"]
        state["current_possible_conditions"] = [c["name"] for c in next_step["possible_conditions"]]
        disease_row = disease_matcher.get_disease_by_name(next_step["disease"])
        history_snippet = _recent_history_snippet(user)
        if disease_row is not None and is_available():
            next_step["description"] = _phrase_result(
                disease_row,
                next_step["match_strength"],
                next_step["symptoms_present"],
                next_step["possible_conditions"],
                history_snippet,
                state,
            )
        fallback_summary = _build_summary_fallback(
            state, next_step["symptoms_present"], next_step["symptoms_denied"]
        )
        summary = (
            _phrase_summary(state, next_step["symptoms_present"], next_step["symptoms_denied"], fallback_summary)
            if is_available()
            else fallback_summary
        )
        next_step["symptom_summary"] = summary
        state["conversation_summary"] = summary
        _log_message(user, "assistant", next_step["description"])

    return {
        "message": None,
        "next_step": next_step,
        "answers": answers,
        "state": state,
        "emergency": False,
    }


def _recent_history_snippet(user):
    if not user:
        return ""
    recent = (
        ChatMessage.query.filter_by(user_id=user.id, role="assistant")
        .order_by(ChatMessage.created_at.desc())
        .limit(3)
        .all()
    )
    if not recent:
        return ""
    return " | ".join(m.content[:200] for m in reversed(recent))


def _log_message(user, role, content, symptoms=None):
    if not user:
        return
    db.session.add(
        ChatMessage(
            user_id=user.id,
            role=role,
            content=content[:4000],
            symptoms=json.dumps(symptoms) if symptoms else None,
        )
    )
    db.session.commit()


# ---------------------------------------------------------------------------
# Main route
# ---------------------------------------------------------------------------


@chat_bp.route("/chat", methods=["POST"])
@optional_token
def chat():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    answers = data.get("answers", [])
    state = cs.normalize(data.get("state"))
    user = request.current_user

    if user_input:
        state["last_user_message"] = user_input

    # Emergency detection runs first, before any DB lookup, conversation
    # state, or model call, and its result is final — nothing downstream
    # (including intent classification or Gemini) can override it.
    if detect_emergency(user_input):
        return jsonify(
            {
                "message": EMERGENCY_MESSAGE,
                "next_step": {"type": "emergency"},
                "answers": answers,
                "state": cs.mark_emergency(state),
                "emergency": True,
            }
        )

    lower_input = user_input.lower()

    # Volunteered profile context (age, sex, medications, allergies,
    # existing conditions) can show up in any message — captured here, once,
    # regardless of which branch below ends up handling the message. Purely
    # additive and never overwrites something already given (see
    # profile_extraction.apply_to_state).
    if user_input:
        profile_extraction.apply_to_state(state, user_input)

    if "bye" in lower_input or "exit" in lower_input:
        return jsonify({"message": "Bye! Take care.", "next_step": {"type": "reset"}, "state": cs.new_state()})

    if not answers and not state.get("chief_complaint") and _is_greeting(lower_input):
        response = random.choice(GREETING_RESPONSES)
        state["conversation_stage"] = "CHIEF_COMPLAINT"
        return jsonify(
            {
                "message": response + ". Please describe your symptoms or just say 'start' to begin a check.",
                "next_step": {"type": "waiting"},
                "state": state,
            }
        )

    # No new text — a yes/no button click, which already carried its answer
    # in `answers` before this request was sent (see ChatWidget.jsx). Go
    # straight to re-evaluating the matcher; nothing to classify.
    if not user_input:
        result = _continue_matching(answers, state, user)
        return jsonify({**result, "emergency": False})

    had_prior_answers = bool(answers)

    vocab_names = symptom_engine.get_all_symptom_names()
    local_symptoms = symptom_engine.extract_symptoms_keyword(lower_input)
    intent = classify_intent(user_input, state, vocab_names, local_symptoms)

    _log_message(user, "user", user_input, local_symptoms)

    # --- Answering a pending open history question (duration/severity/onset)
    if intent == "HISTORY_ANSWER" and state.get("pending_history_slot"):
        slot = state["pending_history_slot"]
        value = history_taking.parse_slot_answer(slot, user_input)
        state[slot] = value
        state["history_slots_asked"] = list(set((state.get("history_slots_asked") or []) + [slot]))
        state["pending_history_slot"] = None
        result = _continue_matching(answers, state, user)
        ack = f"Got it — noting {slot}: {value}." if value else None
        return jsonify({**result, "message": ack, "emergency": False})

    # --- Free-text yes/no answer to a pending symptom question (in addition
    # to the button-click path already handled by the empty-message branch
    # above).
    if intent == "SYMPTOM_ANSWER" and state.get("pending_symptom_question"):
        raw_symptom = state["pending_symptom_question"]
        answered_yes = bool(re.match(r"^\s*(yes|yeah|yep|yup)\b", user_input, re.I))
        if not any(a[0] == raw_symptom for a in answers):
            answers.append([raw_symptom, answered_yes])
        result = _continue_matching(answers, state, user)
        return jsonify({**result, "emergency": False})

    # --- Explicit restart ("start over", "restart") — same reset as "bye"
    # but framed as continuing the conversation, not ending it.
    if intent == "RESTART":
        return jsonify(
            {"message": RESTART_MESSAGE, "next_step": {"type": "reset"}, "state": cs.new_state(), "emergency": False}
        )

    # --- Casual / thanks
    if intent == "CASUAL":
        text = generate_text(
            f'The user said: "{user_input}" in a medical chat, after receiving guidance. '
            "Reply warmly in one short sentence, no medical content.",
            fallback=random.choice(_CASUAL_RESPONSES),
        )
        return jsonify(
            {"message": text, "next_step": {"type": "waiting"}, "answers": answers, "state": state, "emergency": False}
        )

    # --- Medication questions: fixed, never Gemini-generated — Healora has
    # no medication/dosage data in its schema at all, so there is never a
    # verified answer to fall back on, and a hardcoded string can never
    # invent a drug name the way a model call always carries some residual
    # risk of doing (see "The Gemini boundary" in README.md).
    if intent == "MEDICATION_QUESTION":
        return jsonify(
            {
                "message": _with_pending_reminder(MEDICATION_GUARDRAIL_MESSAGE, state),
                "next_step": {"type": "waiting"},
                "answers": answers,
                "state": state,
                "emergency": False,
            }
        )

    # --- Follow-up questions grounded in the current (or named) condition,
    # or — if no condition is in context / named — general health education
    # (see GENERAL_HEALTH_SYSTEM_INSTRUCTION). Either way this is answered
    # here rather than falling through to symptom extraction, so a message
    # like "Why does fever happen?" doesn't get misread as a fresh fever
    # complaint just because it happens to contain the word "fever".
    if intent in (
        "FOLLOW_UP_RESULT",
        "QUESTION_ABOUT_CONDITION",
        "SEVERITY_QUESTION",
        "CAUSE_QUESTION",
        "DURATION_QUESTION",
        "PRECAUTION_QUESTION",
    ):
        target = _resolve_followup_target(user_input, state)
        if target is not None:
            answer_text = _answer_followup(intent, user_input, target, state)
            return jsonify(
                {
                    "message": _with_pending_reminder(answer_text, state),
                    "next_step": {"type": "waiting"},
                    "answers": answers,
                    "state": state,
                    "emergency": False,
                }
            )
        if intent != "FOLLOW_UP_RESULT":
            # A genuinely informational question, but not about any disease
            # Healora's database knows by name — answer as general health
            # education instead of dead-ending with NO_MATCH_MESSAGE.
            answer_text = _answer_general_health_question(user_input)
            message = _with_pending_reminder(answer_text, state)
            state["conversation_stage"] = "GENERAL_QUESTION"
            return jsonify(
                {
                    "message": message,
                    "next_step": {"type": "waiting"},
                    "answers": answers,
                    "state": state,
                    "emergency": False,
                }
            )
        # FOLLOW_UP_RESULT with nothing in context to answer about — fall
        # through to normal symptom handling below instead of dead-ending.

    # --- New symptom / establishing (or re-establishing) the chief complaint
    # Clause-aware, so "I have fever but no cough" records fever=True,
    # cough=False instead of negating (or asserting) the whole message at
    # once — see negation.py.
    positive_symptoms, negative_symptoms = _extract_symptoms_with_negation(user_input, vocab_names)

    for s in positive_symptoms:
        if not any(a[0] == s for a in answers):
            answers.append([s, True])
    for s in negative_symptoms:
        if not any(a[0] == s for a in answers):
            answers.append([s, False])

    message = None
    if positive_symptoms or negative_symptoms:
        parts = []
        if positive_symptoms:
            parts.append("you have: " + ", ".join(s.replace("_", " ") for s in positive_symptoms))
        if negative_symptoms:
            parts.append("you don't have: " + ", ".join(s.replace("_", " ") for s in negative_symptoms))
        message = "I've noted that " + "; and ".join(parts) + "."
        # Only start the history-taking sequence for a genuinely fresh
        # conversation (nothing confirmed yet before this message) — a
        # caller that seeds `answers` directly via the API (or a new
        # symptom volunteered after a result was already shown) skips
        # straight to re-running the matcher, matching how `answers` has
        # always behaved as directly API-settable state.
        if not had_prior_answers and not state.get("chief_complaint") and positive_symptoms:
            cs.start_new_complaint(state, positive_symptoms[0])
    elif not state.get("chief_complaint"):
        # Nothing recognized yet and no complaint established — try a
        # curated clarification before giving up with a generic message.
        clarification = find_clarification(lower_input)
        return jsonify(
            {
                "message": clarification or NO_MATCH_MESSAGE,
                "next_step": {"type": "waiting"},
                "answers": answers,
                "state": state,
                "emergency": False,
            }
        )

    result = _continue_matching(answers, state, user)
    if message:
        result["message"] = message
    return jsonify({**result, "emergency": False})


@chat_bp.route("/symptoms", methods=["GET"])
def get_all_symptoms():
    return jsonify({"symptoms": symptom_engine.list_symptoms_display()})


@chat_bp.route("/tips", methods=["GET"])
def tips():
    return jsonify({"tip": get_daily_tip()})
