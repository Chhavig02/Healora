"""Thin wrapper around the Gemini free-tier API (google-genai SDK).

## The Gemini boundary — read before adding a new call site

Gemini is the language layer only. It is never Healora's source of medical
truth. Concretely, that means:

- Gemini never creates, updates, or deletes a Disease or Symptom row. Only
  scripts/seed_diseases.py writes to those tables, from CSV/JSON data.
- Any symptom name Gemini extracts is meaningless until checked against the
  canonical Symptom table (see chat.py's `_gemini_extract_symptoms`, which
  filters against `symptom_engine.get_all_symptom_names()`). Anything
  outside that vocabulary is discarded, never inserted.
- Disease ranking, scoring, and the "which disease is this" decision always
  come from disease_matcher.py, which only reads the database. Gemini's
  explanation text is generated *after* that decision is made, grounded in
  the specific Disease row's fields — it doesn't get a vote on which
  disease is presented.
- Emergency detection (emergency.py) runs before any Gemini call and is
  final; nothing here can see or override it.
- Every function below degrades gracefully to `fallback` (None by default)
  if no GEMINI_API_KEY is configured, the SDK isn't installed, or the call
  fails for any reason (rate limit, network error, bad JSON, validation
  failure) — callers must always be written to work with fallback=None.
"""

import logging
import os

logger = logging.getLogger(__name__)

_configured = False
_client = None

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# Applied to every call by default.
HEALORA_SYSTEM_INSTRUCTION = (
    "You are the language layer for Healora, an educational symptom-support "
    "assistant. You are NOT a doctor and this is NOT a diagnostic tool. "
    "Hard rules, no exceptions:\n"
    "1. Never state or imply a definitive diagnosis. Use language like "
    "'possible conditions to discuss with a doctor', never 'you have X'.\n"
    "2. Never invent a disease, symptom, treatment, or medication dosage "
    "that wasn't given to you in the prompt's data. If you weren't given "
    "structured facts about something, say you don't have verified "
    "information rather than filling the gap. Never mention a condition "
    "name that wasn't explicitly provided to you in the prompt.\n"
    "3. Never override or soften an emergency warning — if the app already "
    "flagged something as an emergency, that decision is final and not "
    "yours to reassess.\n"
    "4. Always keep or reinforce the message that this is educational "
    "guidance and a licensed healthcare professional should be consulted, "
    "especially for anything severe, persistent, or worsening.\n"
    "5. Be warm and clear, but concise — this is a chat widget, not an "
    "article."
)


def _ensure_client():
    global _configured, _client
    if _configured:
        return _client is not None

    _configured = True
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.info("GEMINI_API_KEY not set — Gemini features disabled, using local fallbacks.")
        return False

    try:
        from google import genai
        from google.genai import types

        # The SDK's defaults (5 attempts, up to 60s backoff) mean a single
        # slow/overloaded call can block the request for over a minute —
        # and since the dev server and a naive single-worker deployment are
        # single-threaded, that stalls every other request too. One quick
        # attempt with a hard timeout keeps latency bounded; our own
        # fallback path is a perfectly good substitute for the SDK retrying
        # on our behalf. 10000ms is the server-enforced minimum deadline —
        # a shorter value is rejected outright with a 400, not just slower.
        _client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=10000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        return True
    except Exception:
        logger.exception("Failed to initialize Gemini SDK")
        _client = None
        return False


def is_available():
    return _ensure_client()


def generate_text(prompt, fallback=None, temperature=0.6, system_instruction=HEALORA_SYSTEM_INSTRUCTION):
    if not _ensure_client():
        return fallback
    try:
        from google.genai import types

        response = _client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_instruction,
            ),
        )
        text = (response.text or "").strip()
        return text or fallback
    except Exception:
        logger.exception("Gemini text generation failed")
        return fallback


def generate_json(
    prompt,
    fallback=None,
    temperature=0.2,
    system_instruction=HEALORA_SYSTEM_INSTRUCTION,
    validator=None,
):
    """`validator`, if given, is called with the parsed JSON and must return
    True/False (or raise). A failing/raising validator is treated exactly
    like an API failure — `fallback` is returned and nothing else changes.

    This only checks *shape* (right keys, right types) — it does not know
    what a valid symptom or disease name is. Callers still need their own
    domain check against the actual database (see chat.py), because the
    valid vocabulary can change between requests as the dataset grows.
    """
    if not _ensure_client():
        return fallback
    try:
        import json

        from google.genai import types

        response = _client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                system_instruction=system_instruction,
            ),
        )
        data = json.loads(response.text)
    except Exception:
        logger.exception("Gemini JSON generation failed")
        return fallback

    if validator is not None:
        try:
            if not validator(data):
                logger.warning("Gemini JSON response failed shape validation: %r", data)
                return fallback
        except Exception:
            logger.exception("Gemini JSON validator raised")
            return fallback

    return data
