import json
import logging
import random
import re

from flask import Blueprint, jsonify, request

import disease_matcher
import symptom_engine
from auth import optional_token
from emergency import EMERGENCY_MESSAGE, detect_emergency
from extensions import db
from gemini_client import generate_json, generate_text, is_available
from health_tips import get_daily_tip
from models import ChatMessage

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
    "I couldn't confidently match that to anything in Healora's symptom database yet. "
    "Could you describe what you're feeling in a bit more detail (e.g. where it hurts, "
    "how long it's lasted, anything that makes it better or worse)?"
)


def _is_greeting(text):
    return bool(_GREETING_PATTERN.search(text))


def _is_symptom_extraction_shape(data):
    return (
        isinstance(data, dict)
        and isinstance(data.get("symptoms"), list)
        and all(isinstance(s, str) for s in data["symptoms"])
    )


def _gemini_extract_symptoms(user_input, vocab_names):
    """Ask Gemini which known symptoms a free-text message implies. Gemini's
    output is advisory only: anything it returns that isn't a real
    Symptom.name is discarded here, never trusted or written to the
    database — see the "Gemini boundary" note in gemini_client.py.
    """
    vocab_str = ", ".join(vocab_names)
    prompt = (
        "You are a symptom-extraction component inside a medical symptom-checker app.\n"
        "Known symptom vocabulary (respond using ONLY these exact strings, "
        f"underscored form): {vocab_str}\n\n"
        f'User message: "{user_input}"\n\n'
        'Return strict JSON of the shape {"symptoms": ["<vocab_item>", ...]} containing '
        "only vocabulary items clearly implied by the message. If none apply, return "
        '{"symptoms": []}. Do not invent items outside the vocabulary.'
    )
    data = generate_json(prompt, fallback=None, validator=_is_symptom_extraction_shape)
    if not isinstance(data, dict):
        return []
    symptoms = data.get("symptoms") or []

    valid = set(vocab_names)
    accepted = [s for s in symptoms if s in valid]
    unresolved = [s for s in symptoms if s not in valid]
    if unresolved:
        # Gemini named something outside the canonical Symptom vocabulary —
        # discarded, not inserted anywhere. Logged so an unusually common
        # unresolved phrase can inform a future alias/data addition.
        logger.info("Discarded unresolved symptom candidates from Gemini: %r", unresolved)

    return accepted


def _phrase_question(raw_symptom, confirmed_symptoms, fallback_text):
    readable = raw_symptom.replace("_", " ")
    confirmed = ", ".join(s.replace("_", " ") for s in confirmed_symptoms) or "none yet"
    prompt = (
        "You are conducting a symptom check for the user. They have already confirmed "
        f"having: {confirmed}. Ask them, in one short natural sentence ending in \"?\", "
        f'whether they also have this symptom: "{readable}". Output only the question, '
        "nothing else."
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


def _phrase_result(disease_row, match_strength, symptoms_present, possible_conditions, history_snippet):
    confirmed = ", ".join(symptoms_present) or "the symptoms you described"
    facts = disease_row.to_dict(include_enrichment=True)

    fact_lines = [
        f"- Name: {facts['name']}",
        f"- Standard description: {facts['description'] or 'not available'}",
    ]
    for key, label in _ENRICHMENT_LABELS:
        if facts.get(key):
            fact_lines.append(f"- {label}: {facts[key]}")
    facts_block = "\n".join(fact_lines)

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

    allowed_names = ", ".join([facts["name"]] + other_names)
    prompt = (
        "A separate deterministic symptom-matching system (not you) queried Healora's "
        "database and determined these structured facts about the top candidate "
        f"condition:\n{facts_block}\n"
        f"Match strength: {match_strength} (qualitative — never restate this as a "
        f"percentage or probability).\n"
        f"Confirmed symptoms: {confirmed}{other_line}{history_line}\n\n"
        "Using ONLY the facts above — do not add any medical claim, cause, treatment, "
        "or condition that isn't in them — write a short (3-5 sentence), empathetic "
        "explanation of this result for the user, in natural prose. The ONLY condition "
        f"names you may mention anywhere in your reply are: {allowed_names}. Do not "
        "name any other disease or condition, even a common or seemingly obvious one. "
        "If other possibilities were listed, briefly note they're also worth discussing "
        "with a doctor. End by reinforcing this is educational guidance, not a "
        "diagnosis."
    )
    fallback = facts["description"] or "Please consult a medical professional for more details."
    return generate_text(prompt, fallback=fallback)


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


@chat_bp.route("/chat", methods=["POST"])
@optional_token
def chat():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    answers = data.get("answers", [])
    user = request.current_user

    # Emergency detection runs first, before any DB lookup or model call,
    # and its result is final — nothing downstream (including Gemini) can
    # override it.
    if detect_emergency(user_input):
        return jsonify(
            {
                "message": EMERGENCY_MESSAGE,
                "next_step": {"type": "emergency"},
                "answers": answers,
                "emergency": True,
            }
        )

    lower_input = user_input.lower()

    if "bye" in lower_input or "exit" in lower_input:
        return jsonify({"message": "Bye! Take care.", "next_step": {"type": "reset"}})

    if not answers and _is_greeting(lower_input):
        response = random.choice(GREETING_RESPONSES)
        return jsonify(
            {
                "message": response + ". Please describe your symptoms or just say 'start' to begin a check.",
                "next_step": {"type": "waiting"},
            }
        )

    vocab_names = symptom_engine.get_all_symptom_names()
    local_symptoms = symptom_engine.extract_symptoms_keyword(lower_input)
    gemini_symptoms = _gemini_extract_symptoms(user_input, vocab_names) if user_input else []
    new_symptoms = list(set(local_symptoms) | set(gemini_symptoms))

    for s in new_symptoms:
        if not any(a[0] == s for a in answers):
            answers.append([s, True])

    _log_message(user, "user", user_input or "(symptom check continued)", new_symptoms)

    next_step = disease_matcher.get_next_step(answers)

    message = None
    if new_symptoms:
        message = f"I've noted that you have: {', '.join(s.replace('_', ' ') for s in new_symptoms)}."

    if next_step is None:
        # No disease in the database shares any confirmed symptom yet —
        # common right after a greeting-only turn, or genuinely unrecognized
        # phrasing. Ask for more detail instead of returning an empty result.
        return jsonify(
            {
                "message": message or NO_MATCH_MESSAGE,
                "next_step": {"type": "waiting"},
                "answers": answers,
                "emergency": False,
            }
        )

    if next_step["type"] == "question" and is_available():
        confirmed = [a[0] for a in answers if a[1]]
        next_step["symptom"] = _phrase_question(
            next_step["raw_symptom"], confirmed, next_step["symptom"]
        )
    elif next_step["type"] == "result":
        disease_row = disease_matcher.get_disease_by_name(next_step["disease"])
        history_snippet = _recent_history_snippet(user)
        if disease_row is not None and is_available():
            next_step["description"] = _phrase_result(
                disease_row,
                next_step["match_strength"],
                next_step["symptoms_present"],
                next_step["possible_conditions"],
                history_snippet,
            )
        _log_message(user, "assistant", next_step["description"])

    return jsonify(
        {
            "message": message,
            "next_step": next_step,
            "answers": answers,
            "emergency": False,
        }
    )


@chat_bp.route("/symptoms", methods=["GET"])
def get_all_symptoms():
    return jsonify({"symptoms": symptom_engine.list_symptoms_display()})


@chat_bp.route("/tips", methods=["GET"])
def tips():
    return jsonify({"tip": get_daily_tip()})
