"""Conversation orchestrator — the single place that decides what
Healora's response to a message should be.

    USER MESSAGE
         |
         v
    handle_message()
         |
         +--> Emergency check (final, first, cannot be overridden by
         |    anything below — see emergency.py)
         +--> Volunteered profile context capture (age/sex/medications/
         |    allergies/existing conditions — see profile_extraction.py)
         +--> Semantic interpretation (semantic_interpreter.py) — Gemini-
         |    assisted, always backed by a deterministic fallback. Produces
         |    a structured interpretation (a `meaning` bucket plus
         |    context-aware signals like "does this actually answer the
         |    pending question", improvement/worsening), not just a flat
         |    intent string — see that module's own docstring for why.
         +--> Route to the capability that interp["meaning"] actually needs:
                - GREETING / RESTART / CASUAL -> light response, no engine
                - HISTORY_ANSWER / SYMPTOM_ANSWER -> apply the answer to the
                  existing assessment (plus any new symptom content in the
                  same message — never mutually exclusive with answering
                  the pending question), then continue it
                - MEDICATION / PRECAUTION / DIET / HOME_CARE / RECOVERY /
                  SEVERITY / CAUSE / DURATION / QUESTION_ABOUT_CONDITION
                  question -> one shared contextual-answer capability,
                  grounded in conversation state + (if resolved) a specific
                  Disease row's own facts. Never touches the disease engine.
                - SYMPTOMS_WORSENING / FEELING_BETTER -> an update about how
                  things are trending, not a question — grounded in the
                  active condition's facts when one exists, never a fresh
                  disease-engine run.
                - EMOTIONAL_CONCERN -> warm, contextual support via the
                  open-conversation capability, no medical content invented.
                - NEW_SYMPTOM -> extract symptoms (negation-aware), merge
                  into `answers`, continue the assessment. This — plus the
                  SYMPTOM_ANSWER/HISTORY_ANSWER paths above — are the ONLY
                  places disease_matcher.get_next_step is ever called.
                - Nothing else matched (UNCLEAR) and no new symptoms found:
                  a curated ambiguous-term clarification if one applies,
                  otherwise a context-aware conversational reply if an
                  assessment is already in progress, otherwise the plain
                  "help me understand" floor for a genuinely fresh,
                  unrecognized message.
         |
         v
    response dict (message, next_step, answers, state, emergency)

Root problem this module (plus semantic_interpreter.py) fixes: previously,
any message that didn't match one of a handful of narrow intents (missing
"medicines?" due to a plural-matching regex bug, missing "what should I
eat?" entirely, etc.) fell through to re-invoking the disease engine on
unchanged `answers` — which regenerates the same question or re-shows the
same result card, reads as "the bot forgot what we were talking about".
That specific bug is fixed, but the underlying pattern kept recurring: a
new phrasing shows up ("tierd", "now I am fine"), and the fix was one more
regex or branch bolted onto this file. semantic_interpreter.py exists so a
new phrasing generalizes from what it means in context instead of needing
its own patch — this file still owns every actual decision about what to
do with that meaning, and the disease engine itself (disease_matcher.py)
is untouched either way.
"""

import json
import logging
import random
import re

import conversation_state as cs
import disease_matcher
import history_taking
import negation
import profile_extraction
import semantic_interpreter
import symptom_engine
from data.ambiguous_terms import find_clarification
from emergency import EMERGENCY_MESSAGE, detect_emergency
from extensions import db
from gemini_client import generate_json, generate_text, is_available
from intent_classifier import CASUAL_RE
from models import ChatMessage, Disease

logger = logging.getLogger(__name__)

GREETING_INPUTS = ("hello", "hi", "greetings", "sup", "what's up", "hey", "start", "checkup")
GREETING_RESPONSES = [
    "Hello! I'm here to help you understand your symptoms. How are you feeling today?",
    "Hi there! I'm your Healora AI assistant. Please tell me what's bothering you.",
    "Greetings! Let's perform a quick health assessment. What symptoms are you experiencing?",
    "Hello! I'm ready to help. Feel free to describe your symptoms in your own words.",
]
# A light acknowledgment for a greeting that arrives with other content
# attached ("hi baby", a greeting mid-conversation) — no "let's start a
# health assessment" framing, since that presumes intent the message
# hasn't actually established yet.
LIGHT_GREETING_RESPONSES = [
    "Hi! How can I help?",
    "Hello! What can I do for you?",
    "Hey there — what's on your mind?",
]

# Anchored — the message has to be *just* a greeting (plus trivial filler
# like "there" or punctuation) to earn the full onboarding nudge below.
# "hi baby" contains a greeting word but is not *just* a greeting, so it
# falls through to the general GREETING handling further down instead —
# otherwise the loose, substring version of this check swallowed any
# message that merely contained a greeting word anywhere, regardless of
# what else was in it.
_PURE_GREETING_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(w) for w in GREETING_INPUTS) + r")"
    r"\s*(there|healora)?\s*[!.,]*\s*$",
    re.I,
)

NO_MATCH_MESSAGE = (
    "I want to understand that a little better. Could you describe what you're "
    "feeling — where it is, how it started, or what it feels like?"
)

# The genuinely neutral "I don't understand" floor — used only when a
# message isn't casual, pregnancy-related, a recognized follow-up
# question, or symptom-shaped, AND there's no assessment context to fall
# back on. Deliberately NOT phrased around "describe what you're feeling":
# that framing is only appropriate once something has already indicated a
# health concern (see NO_MATCH_MESSAGE, which stays reserved for the
# disease engine genuinely finding nothing for symptoms someone did
# report). Using the symptom-framed message here was the root cause of
# ordinary conversation ("baby", "I want to marry you") reading as if it
# had been misheard as a symptom.
UNKNOWN_FALLBACK_MESSAGE = (
    "I'm not quite sure what you mean — could you tell me a bit more? If there's a "
    "symptom or health question on your mind, feel free to describe it; otherwise, "
    "just let me know what you'd like to talk about."
)

PREGNANCY_FALLBACK = (
    "Are you asking about pregnancy in general, or is there something specific "
    "you're experiencing that you'd like help with? I can share general educational "
    "information about pregnancy, but for anything specific to your situation, an "
    "OB-GYN or doctor is the best source."
)

PREGNANCY_SYSTEM_INSTRUCTION = (
    "You are the language layer for Healora, an educational health-support "
    "assistant. The user has said something related to pregnancy. You are NOT a "
    "doctor and this is NOT a diagnostic tool. Hard rules:\n"
    "1. Never diagnose a pregnancy or a pregnancy complication — you have no way "
    "to confirm one.\n"
    "2. You may share well-established general pregnancy education (common early "
    "signs, general next steps like taking a home test or seeing a doctor) — never "
    "invent a specific statistic, timeline, or medical fact.\n"
    "3. Never recommend or name a specific medication.\n"
    "4. If the message is vague ('pregnent' with nothing else), ask a warm, brief "
    "clarifying question rather than assuming what they want to know.\n"
    "5. If the message also describes something that sounds like it could be a "
    "medical emergency (e.g. heavy bleeding, severe pain), remind them to seek care "
    "promptly — Healora's separate emergency system already handles clear "
    "emergencies, so don't try to diagnose one yourself here.\n"
    "6. Answer in 2-4 warm, concise sentences, and end by noting a doctor or "
    "OB-GYN can give guidance specific to their situation."
)

MEDICATION_GUARDRAIL_MESSAGE = (
    "I can share general educational information, but I don't have verified "
    "medication or dosage information for your situation — Healora's database "
    "doesn't include treatment data, so I won't guess. A doctor or pharmacist "
    "can recommend the right treatment based on your symptoms and history."
)

DIET_FALLBACK = (
    "Healora doesn't have verified dietary guidance tied to a specific condition, "
    "but in general, light, easily digestible food and staying well-hydrated are "
    "reasonable while you're feeling unwell. For guidance specific to what you're "
    "experiencing, a doctor or dietitian would be the best source."
)

HOME_CARE_FALLBACK = (
    "General supportive care — resting, staying hydrated, and keeping an eye on "
    "your symptoms — is reasonable at home. If things are severe, persistent, or "
    "getting worse, it's best to check in with a healthcare professional."
)

RECOVERY_FALLBACK = (
    "Healora doesn't have verified data on typical recovery timelines — it varies "
    "a lot by person and by what's actually going on. A doctor can give you a "
    "better estimate; as a general rule of thumb, it's worth easing back into "
    "normal activity once your symptoms are clearly improving rather than pushing "
    "through them."
)

GENERAL_HEALTH_FALLBACK = (
    "I don't have verified information on that specific question yet — a "
    "doctor or pharmacist would be able to give you accurate guidance. "
    "Would you like to tell me about any symptoms you're experiencing instead?"
)

# A handful of symptom names that are genuinely non-specific — "I'm tired"
# or "I feel off" could mean dozens of different things, unlike a concrete,
# localized symptom ("headache", "cough", "chest pain"). Mentioning one of
# these *alone* isn't treated as enough to launch straight into structured
# history-taking (see the "open conversation before assessment" comment in
# handle_message) — deliberately small and curated, the same spirit as
# ambiguous_terms.py, not an attempt to classify every symptom this way.
VAGUE_SOLO_SYMPTOMS = frozenset({"fatigue", "malaise", "lethargy"})

# An explicit ask to be assessed — this always counts as "enough
# information" to (re)enter structured mode, even off the back of only a
# vague symptom or no new symptom in the same message.
_ASSESSMENT_REQUEST_RE = re.compile(
    r"\b(check my symptoms|assess me|do an assessment|go through (some|a few) questions|"
    r"start (the |an )?assessment|check what'?s wrong|narrow (this|it) down)\b",
    re.I,
)

OPEN_CONVERSATION_SYSTEM_INSTRUCTION = (
    "You are Healora, a warm, conversational AI health assistant — not a bounded "
    "disease-lookup tool that can only discuss the diseases in its own database. You "
    "are NOT a doctor and this is NOT a diagnostic tool. The user has said something "
    "health-related, vague, or emotional that doesn't yet call for (or isn't) a "
    "structured symptom assessment. Hard rules, no exceptions:\n"
    "1. Never state or imply a diagnosis. If they've described something vague, "
    "acknowledge it warmly and you may mention a few broad, well-known possible "
    "categories of cause (e.g. sleep, stress, nutrition, infection) without naming a "
    "specific disease.\n"
    "2. You may use well-established general medical knowledge to answer a genuine "
    "health question (why fevers happen, what dehydration feels like, pregnancy, "
    "nutrition, recovery, etc.) — never invent a specific fact, statistic, "
    "medication, or dosage.\n"
    "3. If it's useful, invite more detail with ONE natural, open question (what "
    "else they've noticed, how long, etc.) — don't interrogate, and don't ask "
    "something already answered in the context below.\n"
    "4. If the message is emotional or off-topic (scared, worried, bored, "
    "affectionate, small talk), respond warmly and appropriately — you're not a "
    "licensed doctor, a real person, or a romantic partner, but you can still be "
    "kind and present.\n"
    "5. If the conversation has already given enough concrete detail that a "
    "structured symptom check would genuinely help, you may gently offer it — but "
    "never force it or imply one is already underway if it isn't.\n"
    "6. If something you're told sounds like it could be a medical emergency, "
    "remind them to seek care promptly — Healora's separate emergency system "
    "already handles clear emergencies, so don't try to diagnose one yourself here.\n"
    "7. Keep it to 2-4 warm, natural sentences — this is a chat, not an article."
)

RESTART_MESSAGE = "Sure — let's start fresh. What's bothering you today?"

_CASUAL_RESPONSES = [
    "You're welcome — I'm here if anything else comes up.",
    "Glad I could help. Let me know if anything changes or you think of something else.",
    "Anytime. Take care of yourself, and reach out if you need anything else.",
    "That's kind of you to say — I'm glad I can be here to help. Let me know what's on your mind.",
]

# Every intent that asks a question ABOUT the situation rather than
# reporting a symptom — all answered by the single contextual-answer
# capability below (_answer_contextual), never by the disease engine.
_CONTEXTUAL_INTENTS = (
    "MEDICATION_QUESTION",
    "PRECAUTION_QUESTION",
    "DIET_QUESTION",
    "HOME_CARE_QUESTION",
    "RECOVERY_QUESTION",
    "SEVERITY_QUESTION",
    "CAUSE_QUESTION",
    "DURATION_QUESTION",
    "QUESTION_ABOUT_CONDITION",
    "FOLLOW_UP_RESULT",
)


def _is_pure_greeting(text):
    return bool(_PURE_GREETING_RE.match(text))


# ---------------------------------------------------------------------------
# Symptom extraction (local, negation-aware + Gemini structured, merged)
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
    whether each is present or explicitly denied. Gemini's output is
    advisory only: anything it returns that isn't a real Symptom.name is
    discarded here, never trusted or written to the database — see the
    "Gemini boundary" note in gemini_client.py. It's also never the final
    word on negation for a symptom the deterministic clause-based extractor
    (negation.py) already found — see the merge in _extract_symptoms_with_negation.
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
        logger.info("Discarded unresolved symptom candidates from Gemini: %r", unresolved)

    return result


def _extract_symptoms_with_negation(user_input, vocab_names):
    """Merges the deterministic, clause-based negation splitter with
    Gemini's structured (advisory) extraction. The local extractor is
    authoritative for any symptom it found at all — Gemini only fills in
    symptoms local extraction missed entirely — so behavior never regresses
    when GEMINI_API_KEY is unset.

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
# Gemini-phrased assessment text (symptom questions, history questions,
# results, summaries) — grounded in the deterministic engine's own output.
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


# ---------------------------------------------------------------------------
# Contextual conversational answers — the response layer for every
# "question about the situation" intent (medication, precaution, diet, home
# care, recovery, severity, cause, duration, condition explanation, or a
# genuinely unclassified follow-up while an assessment is in progress).
# Grounded in the full conversation state, plus a specific Disease row's
# facts when one is resolved — NEVER in a fresh disease-matcher run. This
# is what a "medicines?" or "what should I eat?" after an assessment
# actually calls, instead of the engine that produced the assessment.
# ---------------------------------------------------------------------------


CONTEXTUAL_FOLLOWUP_SYSTEM_INSTRUCTION = (
    "You are the language layer for Healora, an educational health-support "
    "assistant continuing an ongoing conversation with a user about their "
    "symptoms. You are NOT a doctor and this is NOT a diagnostic tool. Hard "
    "rules, no exceptions:\n"
    "1. Never state a confirmed diagnosis. Any condition name given to you "
    "below is only a possibility flagged by a separate deterministic "
    "symptom-matching system, not a confirmed diagnosis — always frame it "
    "that way (e.g. '<condition> is one possibility based on what you've "
    "described so far').\n"
    "2. Never name, recommend, or dose a specific medication, including "
    "antibiotics or over-the-counter drugs — direct the user to a doctor "
    "or pharmacist for that. You may describe general supportive-care "
    "concepts (rest, hydration) only in general terms, never as a "
    "prescription.\n"
    "3. You may use well-established, textbook-level general medical "
    "knowledge to answer the question, but never invent a specific fact "
    "(a statistic, a food restriction, a recovery timeline, a cause) that "
    "isn't reasonable general knowledge or given to you in the context "
    "below.\n"
    "4. Only mention condition names that appear in the context below — "
    "never introduce a new one.\n"
    "5. Answer the user's specific question directly and warmly, in 2-4 "
    "sentences. If conversation context is given, use it to make the "
    "answer feel connected to what they've already told you rather than "
    "generic — but if there's little or no context, it's fine to answer "
    "as a standalone general-education question.\n"
    "6. If what the user describes sounds like it could be a medical "
    "emergency, remind them to seek care promptly — but Healora's separate "
    "emergency system already handles clear emergencies, so don't try to "
    "diagnose one yourself here.\n"
    "7. End by noting a doctor or pharmacist can give guidance specific to "
    "their situation, unless you've just done so."
)


def _conversation_context_block(state, answers):
    lines = []
    present = cs.symptoms_present(answers)
    denied = cs.symptoms_denied(answers)
    if state.get("chief_complaint"):
        lines.append(f"- Chief complaint: {state['chief_complaint'].replace('_', ' ')}")
    if present:
        lines.append(f"- Symptoms present: {', '.join(s.replace('_', ' ') for s in present)}")
    if denied:
        lines.append(f"- Symptoms explicitly denied: {', '.join(s.replace('_', ' ') for s in denied)}")
    if state.get("duration"):
        lines.append(f"- Duration: {state['duration']}")
    if state.get("severity"):
        lines.append(f"- Self-rated severity: {state['severity']}/10")
    if state.get("onset"):
        lines.append(f"- Onset: {state['onset']}")
    if state.get("current_primary_condition"):
        lines.append(
            f"- Top possible condition from Healora's structured matcher: {state['current_primary_condition']}"
        )
    if state.get("user_reported_worsening"):
        lines.append("- The user just indicated their symptoms are getting worse.")
    if state.get("user_reported_improvement"):
        lines.append("- The user just indicated their symptoms are improving.")
    others = [
        c for c in (state.get("current_possible_conditions") or []) if c != state.get("current_primary_condition")
    ]
    if others:
        lines.append(f"- Other possible conditions also flagged (lower match): {', '.join(others[:4])}")
    return "\n".join(lines) or "- No symptom details captured yet in this conversation."


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
    # FOLLOW_UP_RESULT / UNCLEAR-with-context / general "what should I do"
    return facts.get("when_to_see_doctor") or (
        "It's a good idea to discuss these symptoms with a healthcare professional, "
        "especially if they're severe, persistent, or getting worse."
    )


def _contextual_fallback(intent, state, disease_row):
    """Deterministic, still context-aware fallback used when Gemini is
    unavailable or fails — every one of these is honest about not having
    verified data rather than inventing anything, and the medication one in
    particular names the possible condition (without claiming it as a
    diagnosis) instead of a flat generic string, matching the same shape
    Gemini is asked to produce."""
    if intent == "MEDICATION_QUESTION":
        condition = state.get("current_primary_condition")
        if condition:
            return (
                f"Because {condition} is only a possible condition based on your symptoms — not a "
                "confirmed diagnosis — I don't have verified medication or dosage information for "
                "your situation. A doctor or pharmacist can recommend the right treatment once "
                "things are properly evaluated."
            )
        return MEDICATION_GUARDRAIL_MESSAGE
    if intent == "DIET_QUESTION":
        return DIET_FALLBACK
    if intent == "HOME_CARE_QUESTION":
        return HOME_CARE_FALLBACK
    if intent == "RECOVERY_QUESTION":
        return RECOVERY_FALLBACK
    if disease_row is not None:
        return _followup_fallback(intent, disease_row)
    return GENERAL_HEALTH_FALLBACK


def _answer_contextual(intent, message, state, answers, disease_row):
    context_block = _conversation_context_block(state, answers)
    fallback = _contextual_fallback(intent, state, disease_row)

    disease_facts_line = ""
    if disease_row is not None:
        _facts, facts_block = _facts_block(disease_row)
        disease_facts_line = (
            f"\nVerified structured facts about {disease_row.name} — the only facts you may use "
            f"about this specific condition, never invent more:\n{facts_block}\n"
        )

    prompt = (
        f"Conversation context so far:\n{context_block}\n{disease_facts_line}\n"
        f'The user just asked: "{message}"\n\n'
        f"Their question category: {intent}.\n"
        "Respond following the system rules exactly."
    )
    return generate_text(prompt, fallback=fallback, system_instruction=CONTEXTUAL_FOLLOWUP_SYSTEM_INSTRUCTION)


def _answer_pregnancy(message, state, answers):
    """Pregnancy is its own conversational domain — never routed through
    the disease engine (see intent_classifier.PREGNANCY_RE and its comment:
    a real symptom in the same message still wins and reaches the normal
    assessment path; this only fires when nothing symptom-shaped was
    found)."""
    context_block = _conversation_context_block(state, answers)
    prompt = (
        f"Conversation context so far:\n{context_block}\n\n"
        f'The user just said: "{message}"\n\n'
        "Respond following the system rules exactly."
    )
    return generate_text(prompt, fallback=PREGNANCY_FALLBACK, system_instruction=PREGNANCY_SYSTEM_INSTRUCTION)


_VAGUE_SYMPTOM_FALLBACK = (
    "I'm sorry you've been feeling that way. That can have a number of possible "
    "causes — things like sleep, stress, nutrition, or an underlying illness can "
    "all play a role. Can you tell me a bit more about what you're noticing, and "
    "how long this has been going on?"
)


def _answer_open_conversation(message, state, answers, mode="general"):
    """The open, non-bounded health-conversation capability — Gemini as the
    conversational brain, never the disease engine. Used for vague/
    emotional statements, general "why/what" health questions with nothing
    to ground them in a specific Disease row, and anything else that isn't
    casual, pregnancy-related, a recognized follow-up question, or a
    concrete symptom report. `mode` only selects which deterministic
    fallback to use when Gemini is unavailable — the system instruction is
    shared, since the underlying capability is the same either way."""
    context_block = _conversation_context_block(state, answers)
    fallback = _VAGUE_SYMPTOM_FALLBACK if mode == "vague_symptom" else UNKNOWN_FALLBACK_MESSAGE
    prompt = (
        f"Conversation context so far:\n{context_block}\n\n"
        f'The user just said: "{message}"\n\n'
        "Respond following the system rules exactly."
    )
    return generate_text(prompt, fallback=fallback, system_instruction=OPEN_CONVERSATION_SYSTEM_INSTRUCTION)


# ---------------------------------------------------------------------------
# Follow-up target resolution — does the message name a known disease, or
# is there an active assessment to fall back on?
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


# ---------------------------------------------------------------------------
# History taking (duration / severity / onset) + pending-question reminders
# ---------------------------------------------------------------------------

# The "does this message actually look like an answer to the pending
# duration/severity/onset question" cue-word check now lives in
# semantic_interpreter.py (interp["answers_pending_question"]) — moved, not
# duplicated, since it's squarely a semantic-interpretation question, and
# the orchestrator's HISTORY_ANSWER branch below needs it alongside (not
# instead of) an unconditional check for new symptom content.


def _ask_history_question(state):
    slot = cs.next_history_slot(state)
    state["pending_history_slot"] = slot
    state["pending_symptom_question"] = None
    state["pending_question_type"] = slot
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
    silently drop the conversation's thread."""
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


# ---------------------------------------------------------------------------
# The disease engine entry point — the ONLY function in this module that
# calls disease_matcher.get_next_step. Everything else either avoids the
# engine entirely (contextual answers) or lands here because a genuine
# symptom-assessment step is actually needed.
# ---------------------------------------------------------------------------


def _continue_matching(answers, state, user):
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
        state["pending_question_type"] = "symptom"
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
        state["pending_question_type"] = None
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


def _has_active_context(state, answers):
    return bool(state.get("chief_complaint") or state.get("current_primary_condition") or answers)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def handle_message(user_input, answers, state, user):
    """Decides what Healora's response to one message should be, and
    returns the same response dict shape the /api/chat route has always
    returned (message, next_step, answers, state, emergency) — this is the
    only thing chat.py's route needs to call."""
    if user_input:
        state["last_user_message"] = user_input

    # Emergency detection runs first, before any DB lookup, conversation
    # state, or model call, and its result is final — nothing downstream
    # (including intent classification or Gemini) can override it.
    if detect_emergency(user_input):
        return {
            "message": EMERGENCY_MESSAGE,
            "next_step": {"type": "emergency"},
            "answers": answers,
            "state": cs.mark_emergency(state),
            "emergency": True,
        }

    lower_input = user_input.lower()

    # Volunteered profile context (age, sex, medications, allergies,
    # existing conditions) can show up in any message — captured here, once,
    # regardless of which branch below ends up handling the message.
    if user_input:
        profile_extraction.apply_to_state(state, user_input)

    if "bye" in lower_input or "exit" in lower_input:
        return {"message": "Bye! Take care.", "next_step": {"type": "reset"}, "state": cs.new_state(), "emergency": False}

    if not answers and not state.get("chief_complaint") and _is_pure_greeting(lower_input):
        response = random.choice(GREETING_RESPONSES)
        state["conversation_stage"] = "CHIEF_COMPLAINT"
        return {
            "message": response + ". Please describe your symptoms or just say 'start' to begin a check.",
            "next_step": {"type": "waiting"},
            "state": state,
            "emergency": False,
        }

    # No new text — a yes/no button click, which already carried its answer
    # in `answers` before this request was sent. Go straight to
    # re-evaluating the assessment; nothing to classify.
    if not user_input:
        return _continue_matching(answers, state, user)

    had_prior_answers = bool(answers)

    vocab_names = symptom_engine.get_all_symptom_names()
    local_symptoms = symptom_engine.extract_symptoms_keyword(lower_input)
    interp = semantic_interpreter.interpret(user_input, state, vocab_names, local_symptoms)
    intent = interp["meaning"]
    # Applied uniformly, regardless of which branch below ends up handling
    # the rest of the message — a worsening/improvement statement is a
    # real signal even in a message whose main content is a new symptom
    # report or a contextual question (see semantic_interpreter.py's
    # module docstring on why these are independent flags, not restricted
    # to one meaning value each).
    state["user_reported_improvement"] = bool(interp["user_reported_improvement"])
    state["user_reported_worsening"] = bool(interp["user_reported_worsening"])
    if interp.get("topic"):
        state["current_topic"] = interp["topic"]

    _log_message(user, "user", user_input, local_symptoms)

    # --- Answering a pending open history question (duration/severity/onset)
    if intent == "HISTORY_ANSWER" and state.get("pending_history_slot"):
        slot = state["pending_history_slot"]
        # Symptom content is checked unconditionally now, not only when the
        # message "doesn't look like" an answer — a message can do both at
        # once ("about three days, and I also feel dizzy" both answers the
        # duration question AND reports a new symptom; the old
        # either/or gate silently dropped whichever one it didn't pick).
        new_positive, new_negative = _extract_symptoms_with_negation(user_input, vocab_names)
        new_positive = [s for s in new_positive if not any(a[0] == s for a in answers)]
        new_negative = [s for s in new_negative if not any(a[0] == s for a in answers)]
        for s in new_positive:
            answers.append([s, True])
        for s in new_negative:
            answers.append([s, False])

        symptom_note = None
        if new_positive or new_negative:
            parts = []
            if new_positive:
                parts.append("you have: " + ", ".join(s.replace("_", " ") for s in new_positive))
            if new_negative:
                parts.append("you don't have: " + ", ".join(s.replace("_", " ") for s in new_negative))
            symptom_note = "I've also noted that " + "; and ".join(parts) + "."

        answers_slot = interp["answers_pending_question"]
        # Neither a recognizable answer nor a new symptom — the original
        # "store it anyway" floor: a genuinely odd-but-real free-text
        # answer still has to go somewhere rather than getting the
        # conversation stuck re-asking.
        if not answers_slot and not symptom_note:
            answers_slot = True

        if not answers_slot:
            return {
                "message": _with_pending_reminder(symptom_note, state),
                "next_step": {"type": "waiting"},
                "answers": answers,
                "state": state,
                "emergency": False,
            }

        value = history_taking.parse_slot_answer(slot, user_input)
        state[slot] = value
        state["history_slots_asked"] = list(set((state.get("history_slots_asked") or []) + [slot]))
        state["pending_history_slot"] = None
        state["pending_question_type"] = None
        result = _continue_matching(answers, state, user)
        base_message = f"Got it — noting {slot}: {value}." if value else None
        if symptom_note:
            result["message"] = f"{base_message} {symptom_note}" if base_message else symptom_note
        else:
            result["message"] = base_message
        return result

    # --- Free-text yes/no answer to a pending symptom question
    if intent == "SYMPTOM_ANSWER" and state.get("pending_symptom_question"):
        raw_symptom = state["pending_symptom_question"]
        answered_yes = bool(re.match(r"^\s*(yes|yeah|yep|yup)\b", user_input, re.I))
        if not any(a[0] == raw_symptom for a in answers):
            answers.append([raw_symptom, answered_yes])
        return _continue_matching(answers, state, user)

    # --- A greeting that arrived with other content attached ("hi baby"),
    # or mid-conversation ("hi" after answers already exist) — the fresh-
    # conversation onboarding shortcut above only fires for a message that
    # is *just* a greeting, so anything else greeting-shaped lands here
    # instead. A light acknowledgment, not the "let's start a health
    # assessment" framing, since nothing has actually indicated that yet.
    if intent == "GREETING":
        text = generate_text(
            f'The user said: "{user_input}" — a greeting, possibly with other casual content. '
            "Reply warmly and briefly in one short sentence, no medical content, without assuming "
            "they want to start a symptom check.",
            fallback=random.choice(LIGHT_GREETING_RESPONSES),
        )
        return {"message": text, "next_step": {"type": "waiting"}, "answers": answers, "state": state, "emergency": False}

    # --- Explicit restart ("start over", "restart") — same reset as "bye"
    # but framed as continuing the conversation, not ending it.
    if intent == "RESTART":
        return {"message": RESTART_MESSAGE, "next_step": {"type": "reset"}, "state": cs.new_state(), "emergency": False}

    # --- Casual / thanks
    if intent == "CASUAL":
        if CASUAL_RE.match(user_input.strip()):
            # A closed-set trivial acknowledgment ("thanks", "okay",
            # "great", "sure", ...) — a good natural reply already exists
            # for these, so this skips the LLM gateway entirely rather
            # than spending a call (and its quota) on something this
            # simple. Anything else CASUAL — affectionate messages, small
            # talk that doesn't match this exact pattern — still gets a
            # real, tailored reply below; this is quota optimization, not
            # a replacement for the conversational brain.
            text = random.choice(_CASUAL_RESPONSES)
        else:
            text = generate_text(
                f'The user said: "{user_input}" in a medical chat, after receiving guidance. '
                "Reply warmly in one short sentence, no medical content.",
                fallback=random.choice(_CASUAL_RESPONSES),
            )
        return {"message": text, "next_step": {"type": "waiting"}, "answers": answers, "state": state, "emergency": False}

    # --- "I'm fine now" / "I feel better" — an update, not a question.
    # Previously fell through to the generic post-result catch-all and got
    # a flat "go see a doctor" reply that ignored what was actually said.
    if intent == "FEELING_BETTER":
        text = generate_text(
            f'The user just said: "{user_input}" — they\'re saying their symptoms have eased or '
            "resolved, in an ongoing health conversation. Reply warmly and briefly (1-2 sentences) — "
            "glad to hear it, and mention they're welcome to come back if anything changes or returns. "
            "No generic medical advice.",
            fallback="That's great to hear! Let me know if anything changes or comes back.",
        )
        return {"message": text, "next_step": {"type": "waiting"}, "answers": answers, "state": state, "emergency": False}

    # --- "It's getting worse" / "the fever came back" — an update that
    # things are deteriorating, not resolved and not a new question. Only
    # reached when no actual new symptom was named (NEW_SYMPTOM always
    # wins over this — see semantic_interpreter.py); user_reported_worsening
    # is still set above regardless of which branch handles the message.
    # Grounded in the active condition's own facts (when one exists) so
    # "escalate when appropriate" means pointing at real data, never a
    # fabricated re-diagnosis — the disease engine itself is never
    # re-invoked here, same principle as the contextual-answer capability
    # below.
    if intent == "SYMPTOMS_WORSENING":
        disease_row = None
        if state.get("current_primary_condition"):
            disease_row = disease_matcher.get_disease_by_name(state["current_primary_condition"])
        if disease_row is not None:
            _facts, facts_block = _facts_block(disease_row)
            prompt = (
                f'The user said: "{user_input}" — their symptoms seem to be getting worse '
                "or returning, in an ongoing health conversation. Verified facts about the "
                f"possible condition being discussed:\n{facts_block}\n"
                "Reply warmly in 2-3 sentences: acknowledge this, and gently encourage "
                "seeing a healthcare professional sooner given the worsening trend. Do not "
                "name any other condition, and do not claim a diagnosis."
            )
            fallback = (
                "I'm sorry to hear that. Since things seem to be getting worse, it's a "
                "good idea to check in with a healthcare professional sooner rather than later."
            )
        else:
            prompt = (
                f'The user just said: "{user_input}" — their symptoms seem to be getting '
                "worse or returning, in an ongoing health conversation. Reply warmly and "
                "briefly (1-2 sentences), and gently encourage seeing a healthcare "
                "professional if things continue to worsen. No generic medical advice "
                "beyond that."
            )
            fallback = (
                "I'm sorry to hear that — if things keep getting worse, it's a good idea "
                "to check in with a healthcare professional."
            )
        text = generate_text(prompt, fallback=fallback)
        return {
            "message": _with_pending_reminder(text, state),
            "next_step": {"type": "waiting"},
            "answers": answers,
            "state": state,
            "emergency": False,
        }

    # --- Fear/worry/anxiety about the situation, with no new medical
    # content — warm, contextual support via the same open-conversation
    # capability UNCLEAR-with-no-active-context uses below, not the more
    # clinical, fact-bound contextual-answer capability (see
    # OPEN_CONVERSATION_SYSTEM_INSTRUCTION rule 4). Only reachable via the
    # LLM path today — the deterministic fallback never emits this meaning
    # on its own (see semantic_interpreter._fallback_interpret), since
    # "I'm scared" already resolves correctly through the existing UNCLEAR
    # floor with no dedicated regex needed.
    if intent == "EMOTIONAL_CONCERN":
        state["current_topic"] = interp.get("topic") or "emotional_concern"
        answer_text = _answer_open_conversation(user_input, state, answers, mode="general")
        return {
            "message": _with_pending_reminder(answer_text, state),
            "next_step": {"type": "waiting"},
            "answers": answers,
            "state": state,
            "emergency": False,
        }

    # --- Pregnancy is its own conversational domain — never forced through
    # the disease engine (see intent_classifier.PREGNANCY_RE). A message
    # that also names an actual symptom never reaches this branch at all
    # (NEW_SYMPTOM wins in that case — see intent_classifier.py).
    if intent == "PREGNANCY":
        answer_text = _answer_pregnancy(user_input, state, answers)
        return {
            "message": _with_pending_reminder(answer_text, state),
            "next_step": {"type": "waiting"},
            "answers": answers,
            "state": state,
            "emergency": False,
        }

    # --- Every "question about the situation" intent — medication,
    # precaution, diet, home care, recovery, severity, cause, duration,
    # condition explanation, or the generic "?" follow-up catch-all.
    # Answered by the contextual-answer capability, grounded in
    # conversation state + a resolved Disease row's facts when there is
    # one. Never invokes the disease engine.
    if intent in _CONTEXTUAL_INTENTS:
        target = _resolve_followup_target(user_input, state)
        if target is not None or intent != "FOLLOW_UP_RESULT":
            answer_text = _answer_contextual(intent, user_input, state, answers, target)
            if target is None:
                state["conversation_stage"] = "GENERAL_QUESTION"
            return {
                "message": _with_pending_reminder(answer_text, state),
                "next_step": {"type": "waiting"},
                "answers": answers,
                "state": state,
                "emergency": False,
            }
        # FOLLOW_UP_RESULT with nothing in context to answer about — fall
        # through to normal symptom handling below instead of dead-ending.

    # --- New symptom / open health conversation. Clause-aware extraction,
    # so "I have fever but no cough" records fever=True, cough=False
    # instead of negating (or asserting) the whole message at once — see
    # negation.py. This is also the point where the conversation either
    # stays open (Gemini, no engine call) or formally enters structured
    # assessment (the disease engine) — see the "not enough yet" branch
    # below. The disease engine is invoked from exactly two places in this
    # whole module: here, and inside _continue_matching's own recursive
    # calls from the SYMPTOM_ANSWER/HISTORY_ANSWER branches above.
    had_active_assessment = bool(state.get("current_primary_condition"))
    already_started = bool(state.get("chief_complaint")) or had_active_assessment
    explicit_assessment_request = bool(_ASSESSMENT_REQUEST_RE.search(lower_input))
    positive_symptoms, negative_symptoms = _extract_symptoms_with_negation(user_input, vocab_names)

    for s in positive_symptoms:
        if not any(a[0] == s for a in answers):
            answers.append([s, True])
    for s in negative_symptoms:
        if not any(a[0] == s for a in answers):
            answers.append([s, False])

    if positive_symptoms or negative_symptoms:
        known_positive = set(cs.symptoms_present(answers))
        # Only defer when this is a genuinely fresh complaint, everything
        # known so far is a single vague/non-specific symptom (see
        # VAGUE_SOLO_SYMPTOMS), and the user hasn't explicitly asked to be
        # assessed — "I have a headache" or "fever and headache" still go
        # straight into structured assessment, unchanged; "I'm tired all
        # the time" on its own doesn't.
        still_too_vague = (
            not already_started
            and known_positive
            and known_positive <= VAGUE_SOLO_SYMPTOMS
            and not explicit_assessment_request
        )
        if still_too_vague:
            state["awaiting_more_detail"] = True
            answer_text = _answer_open_conversation(user_input, state, answers, mode="vague_symptom")
            return {
                "message": answer_text,
                "next_step": {"type": "waiting"},
                "answers": answers,
                "state": state,
                "emergency": False,
            }

        # A plain keyword match on a real symptom (e.g. "dizzy") always
        # routes a message to NEW_SYMPTOM before it ever reaches the
        # HISTORY_ANSWER branch above (see semantic_interpreter.py's
        # _fallback_interpret, which — same as intent_classifier's
        # existing behavior — only treats a pending history slot as
        # possibly the whole story when no symptom keyword was found at
        # all). Without this, "about three days, and I also feel dizzy"
        # would record the dizziness but silently drop the duration answer
        # and re-ask the same question — not a data-loss bug, but exactly
        # the "doesn't feel like it remembers what I just said" friction
        # this module exists to avoid. So: if a history slot is genuinely
        # pending and this message also reads as answering it
        # (interp["answers_pending_question"]), capture that too before
        # falling through to _continue_matching, which would otherwise
        # re-ask it.
        history_note = None
        pending_slot = state.get("pending_history_slot")
        if pending_slot and interp["answers_pending_question"]:
            slot_value = history_taking.parse_slot_answer(pending_slot, user_input)
            state[pending_slot] = slot_value
            state["history_slots_asked"] = list(set((state.get("history_slots_asked") or []) + [pending_slot]))
            state["pending_history_slot"] = None
            state["pending_question_type"] = None
            if slot_value:
                history_note = f"Got it — noting {pending_slot}: {slot_value}."

        parts = []
        if positive_symptoms:
            parts.append("you have: " + ", ".join(s.replace("_", " ") for s in positive_symptoms))
        if negative_symptoms:
            parts.append("you don't have: " + ", ".join(s.replace("_", " ") for s in negative_symptoms))
        note = "I've noted that " + "; and ".join(parts) + "."
        # A genuinely new symptom volunteered after an assessment already
        # exists changes the picture — say so explicitly rather than
        # silently re-running the matcher, per the "new symptoms after
        # assessment" requirement.
        if had_active_assessment and positive_symptoms:
            note = "That's new information — let me reassess based on everything you've told me. " + note
        elif state.get("awaiting_more_detail") and positive_symptoms:
            note = "Thanks — let's go through this a bit more systematically. " + note
        message = f"{history_note} {note}" if history_note else note
        # Formally enters structured mode: either this is genuinely the
        # first message of the conversation (`not had_prior_answers`), or
        # it's the message that finally gave enough detail after one or
        # more open-conversation turns (`awaiting_more_detail`) — both are
        # "not already started" cases the vague-check above didn't defer.
        if not already_started and positive_symptoms and (not had_prior_answers or state.get("awaiting_more_detail")):
            cs.start_new_complaint(state, positive_symptoms[0])
        state["awaiting_more_detail"] = False

        result = _continue_matching(answers, state, user)
        result["message"] = message
        return result

    # Nothing recognized as a symptom in this message.
    if explicit_assessment_request and cs.symptoms_present(answers) and not already_started:
        # No new symptom in *this* message, but the user has explicitly
        # asked to be assessed and there's already something on record
        # (e.g. from an earlier vague-symptom turn) — go ahead and start.
        cs.start_new_complaint(state, cs.symptoms_present(answers)[0])
        state["awaiting_more_detail"] = False
        result = _continue_matching(answers, state, user)
        result["message"] = "Sure — let's go through this a bit more systematically."
        return result

    # Three floors, in order: a curated clarification for a known-
    # ambiguous term (e.g. "cold" — genuinely symptom-adjacent, unlike
    # "baby"); a context-aware conversational reply if an assessment is
    # already in progress (this is the fix for "medicines?"/"what should I
    # eat?" style follow-ups that don't match a specific intent —
    # previously this fell through to re-running the disease engine on
    # unchanged answers); otherwise the open, Gemini-driven health
    # conversation — deliberately NOT the symptom-framed NO_MATCH_MESSAGE,
    # since reaching this point means nothing symptom-shaped, casual,
    # pregnancy-related, or otherwise recognized was found at all; treating
    # every unrecognized message as a mis-described symptom, or as a dead
    # end, is the root problem this module exists to avoid.
    clarification = find_clarification(lower_input)
    if clarification:
        return {
            "message": clarification,
            "next_step": {"type": "waiting"},
            "answers": answers,
            "state": state,
            "emergency": False,
        }
    if _has_active_context(state, answers):
        target = _resolve_followup_target(user_input, state)
        answer_text = _answer_contextual("FOLLOW_UP_RESULT", user_input, state, answers, target)
        return {
            "message": _with_pending_reminder(answer_text, state),
            "next_step": {"type": "waiting"},
            "answers": answers,
            "state": state,
            "emergency": False,
        }
    state["awaiting_more_detail"] = True
    answer_text = _answer_open_conversation(user_input, state, answers, mode="general")
    return {
        "message": answer_text,
        "next_step": {"type": "waiting"},
        "answers": answers,
        "state": state,
        "emergency": False,
    }
