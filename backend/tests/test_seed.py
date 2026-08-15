"""Covers Phase 14 items #1 (existing diseases still work) and #2/#3
(disease import works, duplicate imports don't duplicate)."""

from models import Disease, DiseaseSymptom, Symptom
from scripts.seed_diseases import migrate_legacy_csv


def test_migration_imports_all_41_legacy_diseases(app_ctx, seeded):
    assert Disease.query.count() == 41


def test_migration_imports_131_unique_symptoms(app_ctx, seeded):
    # Training.csv has 132 header columns but "fluid_overload" is listed
    # twice — see seed_diseases docstring / README for the finding.
    assert Symptom.query.count() == 131


def test_known_disease_has_expected_fields(app_ctx, seeded):
    dengue = Disease.query.filter_by(name="Dengue").first()
    assert dengue is not None
    assert dengue.description
    assert dengue.risk_score > 0
    assert dengue.source
    symptom_names = {link.symptom.name for link in dengue.symptom_links}
    assert "high_fever" in symptom_names
    assert "headache" in symptom_names


def test_whitespace_dirty_diseases_still_got_descriptions(app_ctx, seeded):
    # Regression test for the Diabetes/Hypertension trailing-space bug found
    # and fixed during migration — both must have a real description, not
    # a silently-dropped None.
    diabetes = Disease.query.filter_by(name="Diabetes").first()
    hypertension = Disease.query.filter_by(name="Hypertension").first()
    assert diabetes is not None and diabetes.description
    assert hypertension is not None and hypertension.description


def test_reseeding_is_idempotent(app_ctx, seeded):
    diseases_before = Disease.query.count()
    symptoms_before = Symptom.query.count()
    links_before = DiseaseSymptom.query.count()

    migrate_legacy_csv(verbose=False)

    assert Disease.query.count() == diseases_before
    assert Symptom.query.count() == symptoms_before
    assert DiseaseSymptom.query.count() == links_before
