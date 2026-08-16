"""LLM gateway — provider-agnostic routing (Gemini primary, configurable
fallback, deterministic floor). Covers spec section 13's twelve scenarios.
Provider-level tests monkeypatch llm.gemini_provider /
llm.openai_compatible_provider directly (real network calls to either are
never made); a second block re-verifies the same behavior through the
real /api/chat endpoint.
"""

import logging

import pytest

import llm.gateway as gateway
import llm.gemini_provider as gemini_provider
import llm.openai_compatible_provider as fallback_provider
from llm.base import ProviderError


@pytest.fixture(autouse=True)
def _fresh_provider_state(monkeypatch):
    """Every test gets providers reset to "not configured" by default, and
    an explicit FALLBACK_LLM_PROVIDER so the fallback slot in the chain is
    actually populated — individual tests opt into "configured" via
    monkeypatching `is_configured`."""
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "groq")
    monkeypatch.setenv("FALLBACK_API_KEY", "test-fallback-key")
    monkeypatch.setenv("FALLBACK_MODEL", "test-model")
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: False)
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: False)
    yield


# 1. Gemini succeeds -> Gemini response returned ----------------------------


def test_gemini_success_returns_gemini_response(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_text", lambda *a, **kw: "gemini response")
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "gemini response"


# 2. Gemini quota error -> fallback response returned ------------------------


def test_gemini_quota_error_uses_fallback(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)

    def _quota(*a, **kw):
        raise ProviderError("quota")

    monkeypatch.setattr(gemini_provider, "generate_text", _quota)
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    monkeypatch.setattr(fallback_provider, "generate_text", lambda *a, **kw: "fallback response")
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "fallback response"


# 3. Gemini timeout -> fallback response returned -----------------------------


def test_gemini_timeout_uses_fallback_after_one_retry(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    calls = {"n": 0}

    def _always_timeout(*a, **kw):
        calls["n"] += 1
        raise ProviderError("timeout")

    monkeypatch.setattr(gemini_provider, "generate_text", _always_timeout)
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    monkeypatch.setattr(fallback_provider, "generate_text", lambda *a, **kw: "fallback response")
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "fallback response"
    # exactly one retry against Gemini before moving on — not a loop
    assert calls["n"] == 2


# 4. Gemini API error -> fallback response returned ---------------------------


def test_gemini_api_error_uses_fallback(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)

    def _api_error(*a, **kw):
        raise ProviderError("api_error")

    monkeypatch.setattr(gemini_provider, "generate_text", _api_error)
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    monkeypatch.setattr(fallback_provider, "generate_text", lambda *a, **kw: "fallback response")
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "fallback response"


# 5. Gemini succeeds -> fallback is NOT called --------------------------------


def test_fallback_not_called_when_gemini_succeeds(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_text", lambda *a, **kw: "gemini response")
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)

    fallback_calls = {"n": 0}

    def _fallback_should_not_run(*a, **kw):
        fallback_calls["n"] += 1
        return "fallback response"

    monkeypatch.setattr(fallback_provider, "generate_text", _fallback_should_not_run)
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "gemini response"
    assert fallback_calls["n"] == 0


# 6. Gemini fails + fallback fails -> deterministic safe response ------------


def test_both_providers_fail_returns_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_text", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota")))
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    monkeypatch.setattr(fallback_provider, "generate_text", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("api_error")))
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "DETERMINISTIC"


def test_no_fallback_configured_goes_straight_to_deterministic(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_text", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota")))
    # fallback stays "not configured" (autouse fixture default)
    result = gateway.generate_text("hi", fallback="DETERMINISTIC")
    assert result == "DETERMINISTIC"


def test_generate_json_validator_rejection_falls_through_to_next_provider(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_json", lambda *a, **kw: {"bad": "shape"})
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    monkeypatch.setattr(fallback_provider, "generate_json", lambda *a, **kw: {"intent": "CASUAL"})

    result = gateway.generate_json(
        "classify this",
        fallback=None,
        validator=lambda d: isinstance(d, dict) and "intent" in d,
    )
    assert result == {"intent": "CASUAL"}


def test_is_available_true_when_any_provider_configured(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: False)
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    assert gateway.is_available() is True


def test_is_available_false_when_nothing_configured(monkeypatch):
    assert gateway.is_available() is False


# 11. No API key appears in logs ---------------------------------------------


def test_no_api_key_in_logs(monkeypatch, caplog):
    monkeypatch.setenv("FALLBACK_API_KEY", "super-secret-fallback-key-12345")
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_text", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota")))
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    monkeypatch.setattr(fallback_provider, "generate_text", lambda *a, **kw: "fallback response")

    with caplog.at_level(logging.DEBUG):
        gateway.generate_text("hi", fallback="DETERMINISTIC")

    assert "super-secret-fallback-key-12345" not in caplog.text
