"""Hardcoded, keyword-based emergency detection.

Deliberately NOT delegated to the LLM: a model call can fail, time out, be
rate-limited, or simply misjudge a borderline phrase. A fixed keyword list
checked before anything else touches the network is the one safety net that
always fires the same way.
"""

import re

_EMERGENCY_PHRASES = [
    "chest pain",
    "crushing pain",
    "can't breathe",
    "cant breathe",
    "cannot breathe",
    "not breathing",
    "difficulty breathing",
    "severe bleeding",
    "heavy bleeding",
    "won't stop bleeding",
    "unconscious",
    "unresponsive",
    "passed out",
    "seizure",
    "convulsion",
    "stroke",
    "face drooping",
    "slurred speech",
    "suicidal",
    "want to die",
    "kill myself",
    "end my life",
    "self harm",
    "overdose",
    "anaphylaxis",
    "severe allergic reaction",
    "throat closing",
    "choking",
    "blue lips",
    "turning blue",
    "severe burn",
    "head injury",
    "coughing up blood",
    "vomiting blood",
]

_PATTERN = re.compile(
    r"(" + "|".join(re.escape(p) for p in _EMERGENCY_PHRASES) + r")",
    re.IGNORECASE,
)

EMERGENCY_MESSAGE = (
    "⚠️ This may be a medical emergency. Please call your local emergency number "
    "(e.g. 911, 112, or 999) or go to the nearest emergency room immediately. "
    "Healora is an informational tool only and cannot provide emergency care."
)


def detect_emergency(text):
    if not text:
        return False
    return bool(_PATTERN.search(text))
