"""Clause-level negation detection for symptom statements.

The existing keyword extractor (symptom_engine.extract_symptoms_keyword)
has no notion of negation at all — it just finds which canonical symptoms
are *mentioned*. That's not good enough for a real conversation: "I have
fever and cough" and "I have fever but no cough" mention exactly the same
two symptoms, but assert opposite things about the second one.

The approach here is deliberately simple and explainable, the same spirit
as the rest of this codebase's keyword-driven matching (see
symptom_engine.py's own docstring): split the message into clauses on the
punctuation/conjunctions that typically separate one assertion from
another, decide per clause whether it reads as a denial (an English
lead-in like "no"/"don't have", or the Hinglish postpositive particle
"nahi"/"nahin" — as in "khansi nahi hai", "cough not present"), and run
the existing extractor on each clause independently. A symptom is only
ever "negative" if it was found inside a negated clause; the same symptom
mentioned in a different, non-negated clause is treated as present (a
plain assertion elsewhere in the message outweighs a possibly-misparsed
negation).

This is not full sentence-level negation parsing (no dependency parsing,
no scope resolution) — it covers the phrasing patterns this app's own
tests and target users actually use. Gemini's structured extraction (see
chat.py's `_gemini_extract_structured`) is asked to also flag
present/absent directly; this module is what keeps that behavior correct
even with no GEMINI_API_KEY configured, which is the always-available
floor the app has to guarantee.
"""

import re

import symptom_engine

_CLAUSE_SPLIT_RE = re.compile(r"\b(?:but|however|although|though)\b|[,;]", re.I)

# Checked anywhere within a clause, not just at the start — Hinglish
# negation ("khansi nahi hai") puts the negation particle after the
# symptom, not before it, so a lead-in-only check would miss it.
_NEGATION_RE = re.compile(
    r"\b(?:no|not|nope|nah|never|without)\b"
    r"|\bdon'?t have\b|\bdo not have\b|\bdoesn'?t have\b|\bdoes not have\b"
    r"|\bdidn'?t have\b|\bdid not have\b"
    r"|\bhaven'?t (?:got|had)\b|\bhasn'?t (?:got|had)\b"
    r"|\bnahi\b|\bnahin\b|\bnai\b",
    re.I,
)


def _clause_is_negated(clause):
    return bool(_NEGATION_RE.search(clause))


def split_negated_symptoms(text):
    """Returns (positive_symptoms, negative_symptoms) — sorted lists of
    canonical symptom names found in `text`, split by whether the clause
    they appeared in reads as a denial. A symptom appearing in both a
    positive and a negated clause is treated as positive."""
    if not text or not text.strip():
        return [], []

    clauses = [c for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip()]
    if not clauses:
        clauses = [text]

    positive = set()
    negative = set()
    for clause in clauses:
        found = symptom_engine.extract_symptoms_keyword(clause)
        if not found:
            continue
        if _clause_is_negated(clause):
            negative.update(found)
        else:
            positive.update(found)

    # A plain, unambiguous assertion elsewhere in the message wins over a
    # negation found in some other clause (e.g. imperfectly split text).
    negative -= positive
    return sorted(positive), sorted(negative)
