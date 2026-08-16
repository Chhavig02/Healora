"""Gemini provider — the primary LLM provider. This is the same
google-genai integration Healora has always used (10s hard timeout, a
single attempt — see the comment below on why), refactored to raise a
classified llm.base.ProviderError on failure instead of silently
returning a fallback value itself; llm/gateway.py is what decides what to
do about a failure (try the fallback provider, or give up and let the
caller's own fallback text stand), not this module.
"""

import json
import logging
import os

from llm.base import (
    HEALORA_SYSTEM_INSTRUCTION,
    REASON_API_ERROR,
    REASON_INVALID_RESPONSE,
    REASON_QUOTA,
    REASON_RATE_LIMIT,
    REASON_TIMEOUT,
    REASON_UNAVAILABLE,
    ProviderError,
)

logger = logging.getLogger(__name__)

NAME = "gemini"

_configured = False
_client = None

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")


def _ensure_client():
    global _configured, _client
    if _configured:
        return _client is not None

    _configured = True
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.info("GEMINI_API_KEY not set — Gemini provider disabled.")
        return False

    try:
        from google import genai
        from google.genai import types

        # The SDK's defaults (5 attempts, up to 60s backoff) mean a single
        # slow/overloaded call can block the request for over a minute —
        # and since the dev server and a naive single-worker deployment
        # are single-threaded, that stalls every other request too. One
        # quick attempt with a hard timeout keeps latency bounded; the
        # gateway's own fallback-provider routing is a better use of that
        # time than the SDK retrying the same provider on our behalf.
        # 10000ms is the server-enforced minimum deadline — a shorter
        # value is rejected outright with a 400, not just slower.
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


def is_configured():
    return _ensure_client()


def _classify_exception(exc):
    try:
        from google.genai import errors as genai_errors
    except Exception:
        genai_errors = None

    if genai_errors is not None and isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        status = (getattr(exc, "status", "") or "").upper()
        message = (getattr(exc, "message", None) or str(exc)).lower()
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            if "rate limit" in message or "rate_limit" in message or "per minute" in message:
                return REASON_RATE_LIMIT
            return REASON_QUOTA
        if code and code >= 500:
            return REASON_API_ERROR
        return REASON_API_ERROR

    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return REASON_TIMEOUT
    except Exception:
        pass

    if isinstance(exc, TimeoutError):
        return REASON_TIMEOUT
    if isinstance(exc, json.JSONDecodeError):
        return REASON_INVALID_RESPONSE
    return REASON_API_ERROR


def generate_text(prompt, system_instruction=HEALORA_SYSTEM_INSTRUCTION, temperature=0.6):
    if not _ensure_client():
        raise ProviderError(REASON_UNAVAILABLE, "GEMINI_API_KEY not configured")
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
        if not text:
            raise ProviderError(REASON_INVALID_RESPONSE, "empty response")
        return text
    except ProviderError:
        raise
    except Exception as exc:
        reason = _classify_exception(exc)
        logger.warning("Gemini text generation failed (%s)", reason)
        logger.debug("Gemini text generation failure detail", exc_info=True)
        raise ProviderError(reason) from None


def generate_json(prompt, system_instruction=HEALORA_SYSTEM_INSTRUCTION, temperature=0.2):
    if not _ensure_client():
        raise ProviderError(REASON_UNAVAILABLE, "GEMINI_API_KEY not configured")
    try:
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
        return json.loads(response.text)
    except ProviderError:
        raise
    except Exception as exc:
        reason = _classify_exception(exc)
        logger.warning("Gemini JSON generation failed (%s)", reason)
        logger.debug("Gemini JSON generation failure detail", exc_info=True)
        raise ProviderError(reason) from None
