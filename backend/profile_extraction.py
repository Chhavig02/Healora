"""Deterministic extraction of profile context the user volunteers: age,
sex, medications, allergies, and existing (chronic) conditions.

Curated and conservative, the same spirit as ambiguous_terms.py and
symptom_aliases_seed.py — this recognizes clearly-stated patterns
("I'm 34", "I'm allergic to penicillin", "I have asthma") rather than
attempting open-ended medical NLP, and it never guesses. Nothing here is
written to a database — same as the rest of conversation state, it only
round-trips through the client each turn (see conversation_state.py). It
exists purely so the conversation can remember what the user already told
it and reflect it back in the summary — never to compute a dosage,
diagnosis, or risk score from it.
"""

import re

_AGE_RE = re.compile(r"\b(\d{1,3})\s*(?:years?[\s-]?old|yrs?[\s-]?old|y/?o)\b", re.I)

_SEX_RE = re.compile(r"\b(?:i'?m|i am|as a)\s+(?:a\s+)?(male|female|man|woman)\b", re.I)
_SEX_MAP = {"male": "male", "man": "male", "female": "female", "woman": "female"}

_MEDICATION_CUE_RE = re.compile(
    r"\b(?:i'?m taking|i am taking|i take|currently on|on medication[s]?[:,]?\s*|taking)\s+"
    r"([a-z][a-z0-9 ,.\-]{1,60}?)(?:[.!?]|$)",
    re.I,
)
_ALLERGY_CUE_RE = re.compile(
    r"\ballerg(?:y|ic)\s+to\s+([a-z][a-z0-9 ,.\-]{1,60}?)(?:[.!?]|$)", re.I
)

_KNOWN_CONDITIONS = (
    "diabetes",
    "asthma",
    "hypertension",
    "high blood pressure",
    "thyroid disorder",
    "thyroid",
    "heart disease",
    "kidney disease",
    "epilepsy",
    "copd",
    "arthritis",
    "anemia",
    "pregnant",
    "pregnancy",
)
_CONDITION_CUE_RE = re.compile(
    r"\b(?:i have|history of|diagnosed with|i'?m|suffering from)\s+(?:a\s+)?(?:history of\s+)?"
    r"(" + "|".join(re.escape(c) for c in _KNOWN_CONDITIONS) + r")\b",
    re.I,
)


def extract_age(text):
    match = _AGE_RE.search(text)
    return match.group(1) if match else None


def extract_sex(text):
    match = _SEX_RE.search(text)
    if not match:
        return None
    return _SEX_MAP.get(match.group(1).lower())


def extract_medication_mention(text):
    match = _MEDICATION_CUE_RE.search(text)
    if not match:
        return None
    value = match.group(1).strip(" .,")
    return value or None


def extract_allergy_mention(text):
    match = _ALLERGY_CUE_RE.search(text)
    if not match:
        return None
    value = match.group(1).strip(" .,")
    return value or None


def extract_existing_condition(text):
    match = _CONDITION_CUE_RE.search(text)
    if not match:
        return None
    return match.group(1).lower()


def apply_to_state(state, text):
    """Mutates `state` in place with anything new this message volunteers.
    Safe to call on every turn — only ever adds, never overwrites a value
    the user already gave, and silently no-ops when nothing matches."""
    if not text:
        return state

    if not state.get("age"):
        age = extract_age(text)
        if age:
            state["age"] = age

    if not state.get("sex"):
        sex = extract_sex(text)
        if sex:
            state["sex"] = sex

    medication = extract_medication_mention(text)
    if medication and medication not in (state.get("medications") or []):
        state.setdefault("medications", []).append(medication)

    allergy = extract_allergy_mention(text)
    if allergy and allergy not in (state.get("allergies") or []):
        state.setdefault("allergies", []).append(allergy)

    condition = extract_existing_condition(text)
    if condition and condition not in (state.get("existing_conditions") or []):
        state.setdefault("existing_conditions", []).append(condition)

    return state
