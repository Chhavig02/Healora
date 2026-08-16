"""Provider-agnostic LLM gateway — the only module the rest of the
backend should get LLM text/JSON generation from.

    Conversation Orchestrator
              |
          LLM Gateway   (this module)
           /        \\
       Gemini      Fallback provider
           \\        /
        text/json, or None

Tries the primary provider (Gemini, by default) first. On a retryable
failure — quota exhausted, rate limited, a timeout, a 5xx, a malformed
response — it moves to the configured fallback provider (see
FALLBACK_LLM_PROVIDER; disabled unless one is actually configured). If
nothing works, it returns None, and the caller's own `fallback=` text —
the deterministic safety net every call site in orchestrator.py already
supplies — is what the user sees. This gateway never invents that text
itself; it only decides *which* provider (if any) gets to generate a real
response.

Failure handling (see llm/base.py's REASON_* constants):
  - quota / rate_limit / api_error / invalid_response / unavailable:
    move to the next provider immediately, no retry against the same one.
  - timeout: one bounded retry against the same provider before moving on
    — never more than that, so a slow provider can't block the request
    indefinitely or loop.

This module never touches the disease engine — it has no idea what a
Disease or a Symptom is. It is purely "get me text/JSON from *a* language
model," which is exactly what gemini_client.py always was; this file (plus
llm/gemini_provider.py and llm/openai_compatible_provider.py) is that same
responsibility split across "which provider" vs "how do I talk to this
one specific provider."
"""

import logging
import os

import llm.gemini_provider as gemini_provider
import llm.openai_compatible_provider as openai_compatible_provider
from llm.base import HEALORA_SYSTEM_INSTRUCTION, REASON_INVALID_RESPONSE, ProviderError

logger = logging.getLogger(__name__)

# Every fallback-provider *name* this gateway recognizes maps to the same
# generic OpenAI-compatible implementation — see that module's own
# _KNOWN_BASE_URLS for the vendors it has a built-in base URL for.
# "openai_compatible" is the catch-all for anything else, driven entirely
# by FALLBACK_BASE_URL/FALLBACK_MODEL.
_PROVIDER_MODULES = {
    "gemini": gemini_provider,
    "groq": openai_compatible_provider,
    "openai": openai_compatible_provider,
    "together": openai_compatible_provider,
    "openrouter": openai_compatible_provider,
    "fireworks": openai_compatible_provider,
    "openai_compatible": openai_compatible_provider,
}


def _provider_chain():
    primary_name = (os.environ.get("PRIMARY_LLM_PROVIDER") or "gemini").strip().lower()
    fallback_name = (os.environ.get("FALLBACK_LLM_PROVIDER") or "").strip().lower()

    primary = _PROVIDER_MODULES.get(primary_name) or gemini_provider
    chain = [primary]

    fallback = _PROVIDER_MODULES.get(fallback_name)
    if fallback is not None and fallback is not primary:
        chain.append(fallback)

    return chain


def _log(provider_name, outcome, reason=None):
    # provider_used / failure_reason only — never the prompt, the raw
    # exception text, or anything from the environment. Stack traces (via
    # logger.exception/logger.debug) stay inside the provider modules
    # themselves, at a lower level than this summary line.
    if outcome == "success":
        logger.info("llm_gateway provider_used=%s outcome=success", provider_name)
    elif outcome == "failure":
        logger.warning("llm_gateway provider_used=%s outcome=failure failure_reason=%s", provider_name, reason)
    else:
        logger.info("llm_gateway provider_used=%s outcome=%s", provider_name, outcome)


def _call_provider(provider, method_name, prompt, system_instruction, temperature):
    """Returns (result, reason) — result is None on failure, with reason
    explaining why. Never raises: an unexpected (non-ProviderError)
    exception is caught, logged server-side, and treated as a plain
    failure of this provider so the gateway can still move on."""
    fn = getattr(provider, method_name)
    reason = None
    for attempt in range(2):
        try:
            return fn(prompt, system_instruction=system_instruction, temperature=temperature), None
        except ProviderError as exc:
            reason = exc.reason
            if reason == "timeout" and attempt == 0:
                continue  # one bounded retry against the same provider, never more
            break
        except Exception:
            logger.exception("Unexpected error calling provider %s.%s", provider.NAME, method_name)
            reason = "api_error"
            break
    return None, reason


def is_available():
    return any(provider.is_configured() for provider in _provider_chain())


def generate_text(prompt, fallback=None, temperature=0.6, system_instruction=HEALORA_SYSTEM_INSTRUCTION):
    for provider in _provider_chain():
        if not provider.is_configured():
            continue
        result, reason = _call_provider(provider, "generate_text", prompt, system_instruction, temperature)
        if result is not None:
            _log(provider.NAME, "success")
            return result
        _log(provider.NAME, "failure", reason)
    _log("deterministic", "used")
    return fallback


def generate_json(prompt, fallback=None, temperature=0.2, system_instruction=HEALORA_SYSTEM_INSTRUCTION, validator=None):
    """`validator`, if given, is called with the parsed JSON and must
    return True/False (or raise) — checked once per provider's result, so
    a response that parses as JSON but has the wrong shape is treated
    exactly like a failure of that provider, and the gateway still tries
    whatever's next in the chain rather than giving up immediately."""
    for provider in _provider_chain():
        if not provider.is_configured():
            continue
        result, reason = _call_provider(provider, "generate_json", prompt, system_instruction, temperature)
        if result is not None:
            if validator is not None:
                try:
                    if not validator(result):
                        _log(provider.NAME, "failure", REASON_INVALID_RESPONSE)
                        continue
                except Exception:
                    logger.exception("Validator raised for provider %s", provider.NAME)
                    _log(provider.NAME, "failure", REASON_INVALID_RESPONSE)
                    continue
            _log(provider.NAME, "success")
            return result
        _log(provider.NAME, "failure", reason)
    _log("deterministic", "used")
    return fallback
