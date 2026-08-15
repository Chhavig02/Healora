"""Generic (symptom-agnostic) history-taking: duration, severity, onset.

These three slots are asked once per new chief complaint, before falling
back to disease_matcher's existing data-driven yes/no symptom questions.
They are NOT wired into disease ranking — the DiseaseSymptom schema has no
field for "how long" or "how severe", so inventing a scoring adjustment for
them would be exactly the kind of fabricated clinical algorithm this
project avoids. They exist to make the conversation feel like real
history-taking and to give Gemini's phrasing real context to work with.

Parsing is best-effort: if a user's free-text answer doesn't cleanly parse,
the raw text is still stored (better than discarding it) and the
conversation moves on to the next slot rather than getting stuck re-asking.
"""

import re

_SEVERITY_NUM_RE = re.compile(r"\b(10|[0-9])\s*(?:/\s*10)?\b")
_SUDDEN_RE = re.compile(r"\b(sudden(ly)?|all at once|out of nowhere|abrupt(ly)?)\b", re.I)
_GRADUAL_RE = re.compile(r"\b(gradual(ly)?|slowly|over time|built up|building up)\b", re.I)

_SLOT_QUESTIONS = {
    "duration": "How long have you had this?",
    "severity": "On a scale from 1 to 10, how severe would you say it is?",
    "onset": "Did it start suddenly, or did it build up gradually?",
}


def question_for_slot(slot):
    return _SLOT_QUESTIONS.get(slot, "Can you tell me a bit more about that?")


def parse_slot_answer(slot, text):
    """Returns the value to store for this slot. Falls back to the raw
    trimmed text when nothing more specific can be parsed out."""
    stripped = text.strip()
    if not stripped:
        return None

    if slot == "severity":
        match = _SEVERITY_NUM_RE.search(stripped)
        if match:
            return match.group(1)
        return stripped

    if slot == "onset":
        if _SUDDEN_RE.search(stripped):
            return "sudden"
        if _GRADUAL_RE.search(stripped):
            return "gradual"
        return stripped

    # duration and anything else: no cleaner structured form to reduce it
    # to, keep the user's own phrasing verbatim ("since yesterday", "3
    # days", "a couple of hours").
    return stripped
