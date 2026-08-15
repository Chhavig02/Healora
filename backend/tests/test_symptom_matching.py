"""Covers Phase 14 items #4 (aliases) and #5 (multi-word symptoms), plus the
exact example phrasings from the spec."""

import symptom_engine


def test_exact_canonical_name_match(app_ctx, seeded):
    assert "headache" in symptom_engine.extract_symptoms_keyword("I have a headache")


def test_alias_joints_hurt(app_ctx, seeded):
    assert "joint_pain" in symptom_engine.extract_symptoms_keyword("my joints hurt")


def test_alias_feeling_very_hot_maps_to_high_fever(app_ctx, seeded):
    assert "high_fever" in symptom_engine.extract_symptoms_keyword("feeling very hot")


def test_alias_cant_breathe_properly_maps_to_breathlessness(app_ctx, seeded):
    found = symptom_engine.extract_symptoms_keyword("can't breathe properly")
    assert "breathlessness" in found


def test_alias_head_is_hurting_maps_to_headache(app_ctx, seeded):
    assert "headache" in symptom_engine.extract_symptoms_keyword("my head is hurting")


def test_multiword_symptom_matches_regardless_of_word_order(app_ctx, seeded):
    # "loss_of_appetite" -> phrase "loss of appetite"; input has both
    # significant words ("loss", "appetite") but not adjacent/ordered.
    found = symptom_engine.extract_symptoms_keyword("I've noticed some appetite loss today")
    assert "loss_of_appetite" in found


def test_single_shared_generic_word_does_not_cause_false_positive(app_ctx, seeded):
    # Regression test: "skin" alone must not match every skin_* symptom.
    found = symptom_engine.extract_symptoms_keyword("my skin looks fine today")
    assert "skin_peeling" not in found
    assert "yellowish_skin" not in found


def test_multiword_match_ignores_missing_stopwords(app_ctx, seeded):
    # canonical "pain_behind_the_eyes" -> "pain behind the eyes"; user
    # dropping "the" shouldn't break the match.
    found = symptom_engine.extract_symptoms_keyword("pain behind eyes")
    assert "pain_behind_the_eyes" in found


def test_unrecognized_text_returns_nothing(app_ctx, seeded):
    assert symptom_engine.extract_symptoms_keyword("qwerty zzz nothing matches") == []


def test_vocab_is_db_backed_not_hardcoded(app_ctx, seeded):
    names = symptom_engine.get_all_symptom_names()
    assert len(names) == 131
    assert "joint_pain" in names
