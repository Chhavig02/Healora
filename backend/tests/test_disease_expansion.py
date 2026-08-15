"""Tests for scripts/import_disease_expansion.py.

Runs against a completely separate, isolated SQLite database from the rest
of the suite (via its own `create_app()` call after pointing DATABASE_URL
elsewhere) — not the shared session database the other test modules use.
This matters because those other modules assert *exact* legacy-only totals
(e.g. "41 diseases"), and this module's fixture adds 147 more; sharing a
database would make those assertions order-dependent and flaky. Isolating
here means every other test file is completely unaffected by this one,
regardless of collection order.
"""

import os
import tempfile
import uuid

import pytest

_DB_PATH = os.path.join(tempfile.gettempdir(), f"healora_expansion_test_{uuid.uuid4().hex}.db")


@pytest.fixture(scope="module")
def expansion_app():
    original = {k: os.environ.get(k) for k in ("DATABASE_URL", "JWT_SECRET", "GEMINI_API_KEY")}

    os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
    os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-000000"
    os.environ["GEMINI_API_KEY"] = ""

    from app import create_app

    flask_app = create_app()
    yield flask_app

    for key, value in original.items():
        if value is not None:
            os.environ[key] = value


@pytest.fixture(scope="module")
def expanded(expansion_app):
    with expansion_app.app_context():
        from scripts.import_disease_expansion import run as run_expansion

        report = run_expansion(verbose=False)
    return report


@pytest.fixture()
def expansion_ctx(expansion_app, expanded):
    with expansion_app.app_context():
        yield expansion_app


def test_report_matches_expected_totals(expanded):
    # Hand-verified against the actual source files: 150 new diseases minus
    # 3 human-reviewed merges (Hepatitis A, Common cold, Osteoarthritis) =
    # 147 genuinely new; 360 new symptoms minus 34 exact + 6 merged = 320.
    assert expanded["existing_diseases"] == 41
    assert expanded["new_diseases"] == 147
    assert expanded["total_diseases"] == 188
    assert expanded["existing_symptoms"] == 131
    assert expanded["new_symptoms"] == 320
    assert expanded["total_symptoms"] == 451
    assert expanded["malformed_records"] == []
    assert expanded["unresolved_mappings"] == []


def test_idempotent_reimport_adds_nothing(expansion_ctx):
    from models import Disease, DiseaseSymptom, Symptom
    from scripts.import_disease_expansion import run as run_expansion

    before_d = Disease.query.count()
    before_s = Symptom.query.count()
    before_l = DiseaseSymptom.query.count()

    run_expansion(verbose=False)

    assert Disease.query.count() == before_d
    assert Symptom.query.count() == before_s
    assert DiseaseSymptom.query.count() == before_l


def test_case_variant_diseases_not_duplicated(expansion_ctx):
    from models import Disease

    assert Disease.query.filter(Disease.name.ilike("hepatitis a")).count() == 1
    assert Disease.query.filter(Disease.name.ilike("common cold")).count() == 1


def test_existing_description_not_overwritten_with_blank(expansion_ctx):
    from models import Disease

    # The expansion file's description for every disease is blank — merging
    # "Hepatitis A" into the existing "hepatitis A" must not wipe out its
    # real, original description.
    d = Disease.query.filter(Disease.name.ilike("hepatitis a")).first()
    assert d.description
    assert "liver" in d.description.lower()


def test_dataset_typo_merged_not_duplicated(expansion_ctx):
    from models import Disease

    assert Disease.query.filter_by(name="Osteoarthritis").first() is None
    existing = Disease.query.filter_by(name="Osteoarthristis").first()
    assert existing is not None
    assert "Osteoarthritis" in [a.alias for a in existing.aliases]


def test_symptom_synonyms_merged_as_aliases_not_duplicate_rows(expansion_ctx):
    from models import Symptom

    for new_name in [
        "blisters",
        "blood_in_stool",
        "burning_urination",
        "diarrhea",
        "pain_behind_eyes",
        "swollen_lymph_nodes",
    ]:
        assert Symptom.query.filter_by(name=new_name).first() is None, (
            f"{new_name!r} should have merged into an existing symptom, not been created"
        )


def test_medically_distinct_lookalikes_kept_separate(expansion_ctx):
    from models import Symptom

    # These resemble existing symptoms as strings but are not the same
    # thing — must exist as their own distinct rows.
    for name in [
        "eye_pain",
        "intense_itching",
        "lower_abdominal_pain",
        "upper_abdominal_pain",
        "painful_swallowing",
        "fever",
    ]:
        assert Symptom.query.filter_by(name=name).first() is not None, f"{name!r} should exist"
    assert Symptom.query.filter_by(name="knee_pain").first() is not None
    assert Symptom.query.filter_by(name="eye_pain").first().id != Symptom.query.filter_by(
        name="knee_pain"
    ).first().id


def test_importance_preserved_verbatim_not_reinterpreted_as_probability(expansion_ctx):
    from models import Disease, DiseaseSymptom

    stroke = Disease.query.filter_by(name="Stroke").first()
    links = DiseaseSymptom.query.filter_by(disease_id=stroke.id).order_by(DiseaseSymptom.rank).all()
    assert [l.importance_label for l in links] == ["high", "high", "medium", "medium", "supporting"]
    assert [l.rank for l in links] == [1, 2, 3, 4, 5]
    # weight/is_common are Healora's own derived heuristic, distinct from
    # the raw label above — not a claim that "high" means a specific %.
    assert links[0].weight == 3.0 and links[0].is_common is True
    assert links[-1].weight == 1.0 and links[-1].is_common is False


def test_new_diseases_carry_verification_status_not_marked_validated(expansion_ctx):
    from models import Disease

    stroke = Disease.query.filter_by(name="Stroke").first()
    assert stroke.verification_status
    assert "needs" in stroke.verification_status.lower() or "review" in stroke.verification_status.lower()
    assert stroke.reference


def test_disease_matcher_ranks_five_existing_diseases(expansion_ctx):
    import disease_matcher

    cases = {
        "Dengue": ["high_fever", "headache", "joint_pain", "pain_behind_the_eyes"],
        "GERD": ["stomach_pain", "acidity", "ulcers_on_tongue", "vomiting"],
        "Malaria": ["chills", "vomiting", "high_fever", "sweating"],
        "Psoriasis": ["skin_rash", "joint_pain", "skin_peeling", "silver_like_dusting"],
        "Typhoid": ["chills", "vomiting", "high_fever", "abdominal_pain"],
    }
    for expected, symptoms in cases.items():
        ranked = disease_matcher.rank_diseases(symptoms, [])
        assert expected in [r["name"] for r in ranked[:3]]


def test_disease_matcher_ranks_five_newly_imported_diseases(expansion_ctx):
    import disease_matcher
    from models import Disease, DiseaseSymptom

    for name in ["Stroke", "Acute bronchitis", "Acute sinusitis", "Strep throat", "Stomach cancer"]:
        disease = Disease.query.filter_by(name=name).first()
        links = DiseaseSymptom.query.filter_by(disease_id=disease.id).all()
        symptoms = [l.symptom.name for l in links]
        ranked = disease_matcher.rank_diseases(symptoms, [])
        assert name in [r["name"] for r in ranked[:3]]


def test_shared_symptom_returns_multiple_candidates_not_one_forced(expansion_ctx):
    import disease_matcher

    ranked = disease_matcher.rank_diseases(["fever"], [])
    assert len(ranked) > 1


def test_unknown_symptom_creates_no_database_record(expansion_ctx):
    import disease_matcher
    from models import Symptom

    before = Symptom.query.count()
    result = disease_matcher.rank_diseases(["definitely_not_a_real_symptom_xyz"], [])
    after = Symptom.query.count()
    assert before == after
    assert result == []


def test_gemini_output_cannot_change_the_ranking_decision(expansion_ctx):
    import chat as chat_module
    from models import Disease, Symptom

    client = expansion_ctx.test_client()
    answers = [
        ["sudden_weakness", True],
        ["facial_drooping", True],
        ["slurred_speech", True],
        ["vision_problems", True],
    ]

    baseline = client.post("/api/chat", json={"message": "", "answers": answers}).get_json()
    baseline_disease = baseline["next_step"]["disease"]

    before_d, before_s = Disease.query.count(), Symptom.query.count()

    original = chat_module._gemini_extract_structured
    chat_module._gemini_extract_structured = lambda user_input, vocab_names: [
        ("not_a_real_symptom", True),
        ("attempted_injection", True),
    ]
    try:
        poisoned = client.post(
            "/api/chat", json={"message": "test", "answers": answers}
        ).get_json()
    finally:
        chat_module._gemini_extract_structured = original

    assert poisoned["next_step"]["disease"] == baseline_disease
    assert Disease.query.count() == before_d
    assert Symptom.query.count() == before_s
