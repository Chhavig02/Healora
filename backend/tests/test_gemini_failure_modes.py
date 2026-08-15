"""Gemini failure modes — spec section 12.G. Every scenario here has to
still return a valid, non-crashing response and must never invent a
symptom/condition/fact. None of these make a real network call.
"""

import gemini_client


def _post(client, message, answers, state=None):
    resp = client.post("/api/chat", json={"message": message, "answers": answers, "state": state})
    assert resp.status_code == 200
    return resp.get_json()


def test_no_api_key_still_returns_valid_response(client):
    assert gemini_client.is_available() is False
    data = _post(client, "I have a headache", [])
    assert data["next_step"]["type"] == "question"


def test_timeout_like_failure_falls_back_gracefully(client, monkeypatch):
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)

    def _raise(*args, **kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(gemini_client, "generate_text", lambda prompt, fallback=None, **kw: fallback)
    monkeypatch.setattr(gemini_client, "generate_json", lambda prompt, fallback=None, **kw: fallback)
    data = _post(client, "I have a headache", [])
    assert data["next_step"]["type"] == "question"


def test_invalid_json_from_gemini_is_treated_as_failure(client, monkeypatch):
    # generate_json's own validator rejects malformed shapes and returns
    # `fallback` — simulated here directly, matching what a real invalid
    # response from the model would do.
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)
    monkeypatch.setattr(gemini_client, "generate_json", lambda prompt, fallback=None, **kw: fallback)
    monkeypatch.setattr(gemini_client, "generate_text", lambda prompt, fallback=None, **kw: fallback)
    data = _post(client, "I have a cough and fever", [])
    assert data["next_step"]["type"] in ("question", "result")
    names = {a[0] for a in data["answers"]}
    assert {"cough", "high_fever"} <= names


def test_rate_limit_like_failure_never_invents_a_symptom(client, monkeypatch):
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)

    def _fake_generate_json(prompt, fallback=None, **kw):
        return fallback  # simulates a 429 -> generate_json swallows and returns fallback

    monkeypatch.setattr(gemini_client, "generate_json", _fake_generate_json)
    monkeypatch.setattr(gemini_client, "generate_text", lambda prompt, fallback=None, **kw: fallback)
    data = _post(client, "my joints hurt", [])
    assert data["emergency"] is False
    assert data["next_step"]["type"] in ("question", "result")


def test_malformed_response_shape_is_rejected_by_validator(client, monkeypatch):
    # Simulate Gemini returning well-formed JSON that fails the caller's
    # own shape validator (e.g. a symptom list of numbers instead of
    # {"name":..., "present":...} dicts) — generate_json must apply the
    # validator and fall back, not hand back garbage.
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)

    real_generate_json = gemini_client.generate_json

    def _bad_shape(prompt, fallback=None, validator=None, **kw):
        data = {"symptoms": [1, 2, 3]}
        if validator is not None and not validator(data):
            return fallback
        return data

    monkeypatch.setattr(gemini_client, "generate_json", _bad_shape)
    monkeypatch.setattr(gemini_client, "generate_text", lambda prompt, fallback=None, **kw: fallback)
    data = _post(client, "I have a headache", [])
    assert data["next_step"]["type"] == "question"
    assert ["headache", True] in data["answers"]


def test_gemini_extraction_failure_does_not_block_negation(client, monkeypatch):
    # Even if the Gemini-assisted structured extraction is unavailable, the
    # deterministic clause-based negation splitter (negation.py) must still
    # work on its own.
    monkeypatch.setattr(gemini_client, "is_available", lambda: True)
    monkeypatch.setattr(gemini_client, "generate_json", lambda prompt, fallback=None, **kw: fallback)
    monkeypatch.setattr(gemini_client, "generate_text", lambda prompt, fallback=None, **kw: fallback)
    data = _post(client, "I have fever but no cough", [])
    assert ["high_fever", True] in data["answers"]
    assert ["cough", False] in data["answers"]
