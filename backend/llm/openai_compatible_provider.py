"""Generic OpenAI-compatible chat-completions provider — the configurable
fallback slot. Works with any provider that speaks the OpenAI Chat
Completions API shape (Groq, OpenAI itself, Together AI, OpenRouter,
Fireworks, a local Ollama/vLLM instance in OpenAI-compat mode, ...) —
Healora isn't hard-coded to one fallback vendor; which one is active is
entirely env-var driven (see FALLBACK_LLM_PROVIDER below). Uses the
standard library's urllib rather than adding a new HTTP client dependency,
since this is a single simple POST per call.
"""

import json
import logging
import os
import urllib.error
import urllib.request

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

NAME = "fallback"

# FALLBACK_LLM_PROVIDER selects one of these by name and its base URL is
# filled in automatically; FALLBACK_BASE_URL always overrides if set, so
# any other OpenAI-compatible endpoint (self-hosted, or a provider not
# listed here) works too without a code change.
_KNOWN_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "together": "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
}
# Only used when FALLBACK_MODEL isn't set — a reasonable small/fast/cheap
# default per known provider, not a recommendation that it's the best
# available model there.
_KNOWN_DEFAULT_MODELS = {
    "groq": "llama-3.1-8b-instant",
    "openai": "gpt-4o-mini",
    "together": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "openrouter": "meta-llama/llama-3.1-8b-instruct",
    "fireworks": "accounts/fireworks/models/llama-v3p1-8b-instruct",
}

_TIMEOUT_SECONDS = 10


def _provider_name():
    return (os.environ.get("FALLBACK_LLM_PROVIDER") or "").strip().lower()


def _api_key():
    return os.environ.get("FALLBACK_API_KEY")


def _base_url():
    explicit = os.environ.get("FALLBACK_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    return _KNOWN_BASE_URLS.get(_provider_name())


def _model():
    return os.environ.get("FALLBACK_MODEL") or _KNOWN_DEFAULT_MODELS.get(_provider_name())


def is_configured():
    return bool(_provider_name() and _api_key() and _base_url() and _model())


def _classify_http_error(status_code, detail):
    lowered = (detail or "").lower()
    if status_code == 429:
        return REASON_QUOTA if "quota" in lowered else REASON_RATE_LIMIT
    if status_code in (401, 403):
        # Bad/missing credentials — a configuration problem, not a
        # transient failure, but still just "this provider didn't work"
        # from the gateway's point of view, not an unhandled exception.
        return REASON_UNAVAILABLE
    if status_code >= 500:
        return REASON_API_ERROR
    return REASON_API_ERROR


def _post(payload):
    url = f"{_base_url()}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        reason = _classify_http_error(exc.code, detail)
        logger.warning("Fallback provider HTTP error (%s)", reason)
        raise ProviderError(reason, f"HTTP {exc.code}") from None
    except TimeoutError:
        logger.warning("Fallback provider request timed out")
        raise ProviderError(REASON_TIMEOUT, "request timed out") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            logger.warning("Fallback provider request timed out")
            raise ProviderError(REASON_TIMEOUT, str(exc.reason)) from None
        # DNS failure, connection refused, etc. — the endpoint itself is
        # unreachable, not something worth retrying against.
        logger.warning("Fallback provider unreachable")
        raise ProviderError(REASON_API_ERROR, str(exc.reason)) from None


def generate_text(prompt, system_instruction=HEALORA_SYSTEM_INSTRUCTION, temperature=0.6):
    if not is_configured():
        raise ProviderError(REASON_UNAVAILABLE, "fallback provider not configured")
    payload = {
        "model": _model(),
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ],
    }
    data = _post(payload)
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(REASON_INVALID_RESPONSE, str(exc)) from None
    if not text:
        raise ProviderError(REASON_INVALID_RESPONSE, "empty response")
    return text


def generate_json(prompt, system_instruction=HEALORA_SYSTEM_INSTRUCTION, temperature=0.2):
    if not is_configured():
        raise ProviderError(REASON_UNAVAILABLE, "fallback provider not configured")
    payload = {
        "model": _model(),
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ],
    }
    data = _post(payload)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(REASON_INVALID_RESPONSE, str(exc)) from None
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ProviderError(REASON_INVALID_RESPONSE, str(exc)) from None
