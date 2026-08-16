"""Real /api/chat integration tests for the LLM gateway — disease
matching, emergency detection, and conversation flows must keep working
regardless of which LLM provider (if any) is actually answering, and no
provider failure detail should ever reach the user.
"""

import llm.gemini_provider as gemini_provider
import llm.openai_compatible_provider as fallback_provider
from llm.base import ProviderError


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def _fail_both_providers(monkeypatch):
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        gemini_provider, "generate_text", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota"))
    )
    monkeypatch.setattr(
        gemini_provider, "generate_json", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota"))
    )
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: False)


def _route_through_fallback(monkeypatch, text_reply=None, json_reply=None):
    # _provider_chain() only includes the fallback module at all when
    # FALLBACK_LLM_PROVIDER names it — mocking is_configured() alone isn't
    # enough if that env var isn't set.
    monkeypatch.setenv("FALLBACK_LLM_PROVIDER", "groq")
    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        gemini_provider, "generate_text", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota"))
    )
    monkeypatch.setattr(
        gemini_provider, "generate_json", lambda *a, **kw: (_ for _ in ()).throw(ProviderError("quota"))
    )
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: True)
    if text_reply is not None:
        monkeypatch.setattr(fallback_provider, "generate_text", lambda *a, **kw: text_reply)
    if json_reply is not None:
        monkeypatch.setattr(fallback_provider, "generate_json", lambda *a, **kw: json_reply)


# 7. Disease engine still works independently --------------------------------


def test_disease_engine_unaffected_by_provider_failures(client, monkeypatch):
    _fail_both_providers(monkeypatch)
    data = _post(client, "I have fever and headache", [])
    names = {a[0] for a in data["answers"] if a[1]}
    assert {"high_fever", "headache"} <= names
    assert data["next_step"]["type"] == "question"


def test_disease_engine_reaches_a_result_with_providers_down(client, monkeypatch):
    _fail_both_providers(monkeypatch)
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["chills", True],
        ["joint_pain", True],
    ]
    state = {"chief_complaint": "high_fever", "history_slots_asked": ["duration", "severity", "onset"]}
    data = _post(client, "", answers, state)
    assert data["next_step"]["type"] == "result"
    assert data["next_step"]["disease"]


# 8. Emergency handling still overrides everything ---------------------------


def test_emergency_overrides_even_when_both_providers_are_down(client, monkeypatch):
    _fail_both_providers(monkeypatch)
    data = _post(client, "severe chest pain and difficulty breathing", [])
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


def test_emergency_overrides_when_fallback_is_the_active_provider(client, monkeypatch):
    _route_through_fallback(monkeypatch, text_reply="this is fine, no emergency", json_reply={"intent": "CASUAL"})
    data = _post(client, "I suddenly have severe chest pain and can't breathe", [])
    assert data["emergency"] is True
    assert data["next_step"]["type"] == "emergency"


# 9. Open conversation works through fallback --------------------------------


def test_open_conversation_routes_through_fallback_provider(client, monkeypatch):
    _route_through_fallback(
        monkeypatch,
        text_reply="Fatigue can have many causes — tell me more about what you're noticing.",
    )
    data = _post(client, "I'm tired all the time.", [])
    assert data["message"] == "Fatigue can have many causes — tell me more about what you're noticing."
    assert data["state"]["chief_complaint"] is None


# 10. Post-assessment contextual question works through fallback ------------


def test_post_assessment_question_routes_through_fallback_provider(client, monkeypatch):
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["chills", True],
        ["joint_pain", True],
    ]
    state = {"chief_complaint": "high_fever", "history_slots_asked": ["duration", "severity", "onset"]}
    data = _post(client, "", answers, state)
    assert data["next_step"]["type"] == "result"
    answers, state = data["answers"], data["state"]

    _route_through_fallback(monkeypatch, text_reply="Here's a fallback-provider explanation of your result.")
    data = _post(client, "What does that result mean?", answers, state)
    assert data["message"] == "Here's a fallback-provider explanation of your result."
    assert data["next_step"]["type"] == "waiting"


# 12. No provider failure ever leaks to the user -----------------------------


def test_provider_failure_details_never_reach_the_user(client, monkeypatch):
    _fail_both_providers(monkeypatch)
    forbidden = ("quota", "rate limit", "api error", "traceback", "exception", "gemini failed", "provider failed")
    for message in ["I'm tired all the time.", "What is dehydration?", "I have a headache"]:
        data = _post(client, message, [])
        lowered = (data.get("message") or "").lower()
        for word in forbidden:
            assert word not in lowered, f"leaked '{word}' in response to {message!r}: {data['message']!r}"


def test_trivial_casual_messages_never_call_the_llm(client, monkeypatch):
    # "thanks"/"okay" should be answered deterministically — verify no
    # provider function is even invoked.
    calls = {"n": 0}

    def _count_and_fail(*a, **kw):
        calls["n"] += 1
        raise ProviderError("api_error")

    monkeypatch.setattr(gemini_provider, "is_configured", lambda: True)
    monkeypatch.setattr(gemini_provider, "generate_text", _count_and_fail)
    monkeypatch.setattr(fallback_provider, "is_configured", lambda: False)

    for message in ["thanks", "thank you", "okay"]:
        data = _post(client, message, [])
        assert data["message"]
    assert calls["n"] == 0
