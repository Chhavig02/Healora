"""Covers Phase 14 item #8 — emergency detection works independently (no DB,
no Gemini, no app context needed at all)."""

from emergency import detect_emergency


def test_detects_chest_pain():
    assert detect_emergency("I have severe chest pain")


def test_detects_cant_breathe_variants():
    assert detect_emergency("I can't breathe")
    assert detect_emergency("cant breathe properly")


def test_detects_suicidal_ideation():
    assert detect_emergency("I want to kill myself")


def test_does_not_flag_ordinary_symptoms():
    assert not detect_emergency("I have a mild headache and a runny nose")


def test_empty_and_none_are_safe():
    assert not detect_emergency("")
    assert not detect_emergency(None)


def test_case_insensitive():
    assert detect_emergency("SEVERE CHEST PAIN")
