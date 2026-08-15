"""Free, self-hosted, deterministic symptom-name matching.

Resolves free text to canonical symptom names (the same underscored strings
used throughout the `answers` API contract) using the Symptom/SymptomAlias
tables — no hardcoded vocabulary, no external API call, so it's always
available even with no Gemini key and zero rate-limit risk. This is the
fallback layer chat.py falls back to when Gemini is unavailable or fails,
and the fast first pass tried before ever calling Gemini.

Matching, in order:
1. Exact phrase match — canonical name, display name, or an alias appears
   verbatim (word-bounded) in the message.
2. All-significant-words match — every word (len > 2) of a multi-word
   symptom/alias appears somewhere in the message, in any order. Guards
   against matching on a single shared generic word (e.g. "skin").
3. Fuzzy single-token match (difflib) — catches typos like "haedache" —
   only attempted if nothing matched yet, to keep false positives down.
"""

import difflib
import re

from models import Symptom

_WORD_RE = re.compile(r"[a-z0-9]+")

# Excluded from the "all significant words present" check below — requiring
# a stopword like "the" to literally appear breaks otherwise-clear matches
# (e.g. "pain behind eyes" vs. canonical "pain behind the eyes").
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "to", "is", "and", "my", "with"}

_vocab_cache = None


def _normalize(text):
    return " ".join(_WORD_RE.findall((text or "").lower()))


def _load_vocab():
    global _vocab_cache
    if _vocab_cache is not None:
        return _vocab_cache

    symptoms = Symptom.query.all()
    phrase_to_canonical = {}
    canonical_names = []
    single_word_vocab = {}  # normalized single word -> canonical name

    for s in symptoms:
        canonical_names.append(s.name)
        phrases = {_normalize(s.name.replace("_", " ")), _normalize(s.display_name)}
        for alias in s.aliases:
            phrases.add(_normalize(alias.alias))
        phrases.discard("")
        for p in phrases:
            phrase_to_canonical[p] = s.name
            if " " not in p and len(p) > 2:
                single_word_vocab[p] = s.name

    _vocab_cache = {
        "phrase_to_canonical": phrase_to_canonical,
        "phrases_by_length_desc": sorted(phrase_to_canonical, key=len, reverse=True),
        "canonical_names": sorted(set(canonical_names)),
        "single_word_vocab": single_word_vocab,
    }
    return _vocab_cache


def invalidate_vocab_cache():
    """Call after re-seeding the database in the same process (tests do
    this). In production, a fresh deploy/restart naturally picks up new
    vocabulary, so this isn't wired into any request path."""
    global _vocab_cache
    _vocab_cache = None


def get_all_symptom_names():
    return list(_load_vocab()["canonical_names"])


def list_symptoms_display():
    """For the /api/symptoms enumeration endpoint — human-readable names,
    not the matching vocabulary internals."""
    return [s.display_name for s in Symptom.query.order_by(Symptom.display_name.asc()).all()]


def extract_symptoms_keyword(text):
    vocab = _load_vocab()
    normalized = _normalize(text)
    if not normalized:
        return []

    padded = f" {normalized} "
    found = set()

    # 1. exact phrase match, longest first so multi-word aliases win over
    # a shorter phrase that happens to be a substring of them
    for phrase in vocab["phrases_by_length_desc"]:
        if f" {phrase} " in padded:
            found.add(vocab["phrase_to_canonical"][phrase])

    # 2. all-significant-words-present match, for phrasing that doesn't
    # keep the words adjacent/ordered
    if True:
        tokens = set(normalized.split(" "))
        for phrase, canonical in vocab["phrase_to_canonical"].items():
            if canonical in found:
                continue
            words = [w for w in phrase.split(" ") if len(w) > 2 and w not in _STOPWORDS]
            if len(words) >= 2 and all(w in tokens for w in words):
                found.add(canonical)

    # 3. fuzzy single-token fallback — only if nothing matched, to avoid
    # compounding false positives on top of real matches
    if not found:
        vocab_words = list(vocab["single_word_vocab"].keys())
        for token in normalized.split(" "):
            if len(token) < 4:
                continue
            close = difflib.get_close_matches(token, vocab_words, n=1, cutoff=0.84)
            if close:
                found.add(vocab["single_word_vocab"][close[0]])

    return sorted(found)
