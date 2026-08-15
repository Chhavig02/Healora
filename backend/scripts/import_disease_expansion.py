"""Idempotent importer for the "Healora 150-disease expansion" dataset.

Reads three Excel workbooks (see `--xlsx-dir`, defaults to
backend/data/expansion/):

- Healora_150_New_Diseases.xlsx     (sheet "Diseases")
- Healora_150_Expanded_Symptoms.xlsx (sheet "Symptoms")
- Healora_150_Disease_Symptoms.xlsx  (sheet "Disease_Symptoms")

and merges them into the existing Disease/Symptom/DiseaseSymptom tables
alongside the originally-migrated dataset.

Usage (from the backend/ directory):

    python scripts/import_disease_expansion.py
    python scripts/import_disease_expansion.py --xlsx-dir path/to/files

Requires `openpyxl` (not a runtime dependency of the app — install it or
use requirements-dev.txt when running this script).

## What this deliberately does NOT do

- It does not treat the source file's `description` column (always blank
  in this dataset) as license to fabricate one. Diseases are imported with
  no description; that's an honest gap, not a bug.
- It does not treat the `importance` column ("high"/"medium"/"supporting")
  as a clinical probability. It's mapped to Healora's own `weight`/
  `is_common` ranking heuristic (a judgment call, documented below) while
  the raw label is preserved verbatim in `importance_label` for anyone who
  wants to reinterpret it differently later.
- It does not merge diseases or symptoms just because their names look
  alike. The merge maps below are a small, hand-reviewed list of genuine
  duplicates (case variants, one dataset typo, true symptom synonyms) —
  see the comments on each map for the reasoning. Everything else that
  merely *resembles* an existing name (e.g. "Gastritis" vs "Arthritis"/
  "Gastroenteritis"; "eye_pain" vs "knee_pain") is imported as a distinct,
  new record on purpose.
"""

import argparse
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Disease, DiseaseAlias, DiseaseSymptom, Symptom, SymptomAlias  # noqa: E402
from scripts.seed_diseases import migrate_legacy_csv  # noqa: E402

DEFAULT_XLSX_DIR = os.path.join(_BACKEND_DIR, "data", "expansion")

DISEASES_FILE = "Healora_150_New_Diseases.xlsx"
SYMPTOMS_FILE = "Healora_150_Expanded_Symptoms.xlsx"
MAPPINGS_FILE = "Healora_150_Disease_Symptoms.xlsx"

# --- Hand-reviewed merge maps -----------------------------------------------
#
# Built by actually diffing this dataset's names against the existing 41
# diseases / 131 symptoms (difflib close-match scan + manual review of every
# hit) — not a blanket similarity threshold, which produced obvious false
# positives (e.g. "Gastritis" ~ "Arthritis", "eye_pain" ~ "knee_pain") that
# must NOT be merged. Only genuine duplicates are listed here.

DISEASE_MERGE_MAP = {
    # New file's exact name -> existing DB's exact name.
    "Hepatitis A": "hepatitis A",  # case variant, same disease
    "Common cold": "Common Cold",  # case variant, same disease
    # The existing DB has a typo baked in from the *original* Healora
    # dataset ("Osteoarthristis" isn't a real medical term). This is the
    # same disease, correctly spelled in the new file — merged into the
    # existing (typo'd) row rather than renaming it, to avoid touching
    # whatever else might key off that exact existing string.
    "Osteoarthritis": "Osteoarthristis",
}

SYMPTOM_MERGE_MAP = {
    # New file's canonical_name -> existing DB's canonical name. Each is a
    # true synonym/spelling variant of the exact same symptom, not just a
    # similar string:
    "blisters": "blister",  # plural/singular
    "blood_in_stool": "bloody_stool",  # phrasing variant
    "burning_urination": "burning_micturition",  # lay term vs clinical term
    "diarrhea": "diarrhoea",  # US/UK spelling
    "pain_behind_eyes": "pain_behind_the_eyes",  # missing "the"
    "swollen_lymph_nodes": "swelled_lymph_nodes",  # grammatical variant
    # Explicitly NOT merged, despite superficial string similarity —
    # medically distinct symptoms:
    #   eye_pain vs knee_pain               (different body parts)
    #   intense_itching vs internal_itching (different qualifiers)
    #   lower_/upper_abdominal_pain vs abdominal_pain (clinically
    #     meaningful localization the original dataset never captured)
    #   painful_swallowing vs painful_walking (different actions)
    # "fever" is also new and NOT a duplicate of high_fever/mild_fever —
    # the original dataset never had a generic fever symptom at all.
}

# Healora's own ranking heuristic — NOT a restatement of the source
# dataset's "importance" as a clinical probability. The raw label is kept
# verbatim in DiseaseSymptom.importance_label regardless of this mapping.
IMPORTANCE_WEIGHT = {"high": 3.0, "medium": 2.0, "supporting": 1.0}
IMPORTANCE_IS_COMMON = {"high": True, "medium": True, "supporting": False}


def _load_sheet(path, sheet_name):
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb[sheet_name].iter_rows(values_only=True))
    header, data = rows[0], rows[1:]
    return header, data


def _get_or_create_disease(display_name, description, source_type, reference, verification_status):
    target_name = DISEASE_MERGE_MAP.get(display_name, display_name)
    existing = Disease.query.filter(db.func.lower(Disease.name) == target_name.strip().lower()).first()

    if existing:
        if display_name.strip().lower() != existing.name.strip().lower():
            alias_exists = DiseaseAlias.query.filter_by(
                disease_id=existing.id, alias=display_name
            ).first()
            if not alias_exists:
                db.session.add(DiseaseAlias(disease_id=existing.id, alias=display_name))
        if not existing.description and description:
            existing.description = description
        if not existing.source_type and source_type:
            existing.source_type = source_type
        if not existing.reference and reference:
            existing.reference = reference
        if not existing.verification_status and verification_status:
            existing.verification_status = verification_status
        return existing, False

    disease = Disease(
        name=display_name,
        description=description or None,
        risk_score=0,
        source_type=source_type,
        reference=reference,
        verification_status=verification_status,
    )
    db.session.add(disease)
    db.session.flush()
    return disease, True


def _get_or_create_symptom(display_name, canonical_name, category, source_type, reference, verification_status):
    target_canonical = SYMPTOM_MERGE_MAP.get(canonical_name, canonical_name)
    existing = Symptom.query.filter_by(name=target_canonical).first()

    if existing:
        alias_text = display_name.strip().lower()
        if alias_text != existing.name and alias_text != existing.display_name.lower():
            alias_exists = SymptomAlias.query.filter_by(
                symptom_id=existing.id, alias=alias_text
            ).first()
            if not alias_exists:
                db.session.add(SymptomAlias(symptom_id=existing.id, alias=alias_text))
        if not existing.category and category:
            existing.category = category
        if not existing.source_type and source_type:
            existing.source_type = source_type
        if not existing.reference and reference:
            existing.reference = reference
        if not existing.verification_status and verification_status:
            existing.verification_status = verification_status
        return existing, False

    symptom = Symptom(
        name=target_canonical,
        display_name=display_name,
        category=category,
        source_type=source_type,
        reference=reference,
        verification_status=verification_status,
    )
    db.session.add(symptom)
    db.session.flush()
    return symptom, True


def _link_disease_symptom(disease, symptom, rank, importance, source_type, reference, verification_status):
    weight = IMPORTANCE_WEIGHT.get(importance, 1.0)
    is_common = IMPORTANCE_IS_COMMON.get(importance, False)

    link = DiseaseSymptom.query.filter_by(disease_id=disease.id, symptom_id=symptom.id).first()
    created = link is None
    if link is None:
        link = DiseaseSymptom(disease_id=disease.id, symptom_id=symptom.id)
        db.session.add(link)

    link.weight = weight
    link.is_common = is_common
    link.rank = rank
    link.importance_label = importance
    link.source_type = source_type
    link.reference = reference
    link.verification_status = verification_status
    return link, created


def run(xlsx_dir=None, verbose=True):
    xlsx_dir = xlsx_dir or DEFAULT_XLSX_DIR
    app = create_app()

    with app.app_context():
        # Guarantees the base 41-disease dataset exists first (idempotent,
        # cheap) so the merge maps above have something to resolve against
        # even if this script is run standalone against a fresh database.
        migrate_legacy_csv(verbose=False)

        diseases_before = Disease.query.count()
        symptoms_before = Symptom.query.count()

        dh, disease_rows = _load_sheet(os.path.join(xlsx_dir, DISEASES_FILE), "Diseases")
        sh, symptom_rows = _load_sheet(os.path.join(xlsx_dir, SYMPTOMS_FILE), "Symptoms")
        mh, mapping_rows = _load_sheet(os.path.join(xlsx_dir, MAPPINGS_FILE), "Disease_Symptoms")

        malformed = []

        disease_cache = {}
        for row in disease_rows:
            name, canonical, description, source_type, verification_status, reference = row
            if not name or not canonical:
                malformed.append(("disease", row))
                continue
            disease, _created = _get_or_create_disease(
                name.strip(), description, source_type, reference, verification_status
            )
            disease_cache[name] = disease

        symptom_cache = {}
        for row in symptom_rows:
            name, canonical, alias, category, source_type, verification_status, reference = row
            if not name or not canonical:
                malformed.append(("symptom", row))
                continue
            symptom, _created = _get_or_create_symptom(
                name.strip(), canonical.strip(), category, source_type, reference, verification_status
            )
            symptom_cache[name] = symptom
            if alias:
                target = SYMPTOM_MERGE_MAP.get(canonical.strip(), canonical.strip())
                alias_text = alias.strip().lower()
                if alias_text and not SymptomAlias.query.filter_by(
                    symptom_id=symptom.id, alias=alias_text
                ).first():
                    db.session.add(SymptomAlias(symptom_id=symptom.id, alias=alias_text))

        links_created = 0
        links_updated = 0
        unresolved_mappings = []
        for row in mapping_rows:
            disease_name, symptom_name, rank, importance, source_type, verification_status, reference = row
            disease = disease_cache.get(disease_name)
            symptom = symptom_cache.get(symptom_name)
            if disease is None or symptom is None:
                unresolved_mappings.append(row)
                continue
            _link, created = _link_disease_symptom(
                disease, symptom, rank, importance, source_type, reference, verification_status
            )
            if created:
                links_created += 1
            else:
                links_updated += 1

        db.session.commit()

        diseases_after = Disease.query.count()
        symptoms_after = Symptom.query.count()
        links_total = DiseaseSymptom.query.count()

        report = {
            "existing_diseases": diseases_before,
            "new_diseases": diseases_after - diseases_before,
            "total_diseases": diseases_after,
            "existing_symptoms": symptoms_before,
            "new_symptoms": symptoms_after - symptoms_before,
            "total_symptoms": symptoms_after,
            "disease_symptom_relationships": links_total,
            "links_created_this_run": links_created,
            "links_updated_this_run": links_updated,
            "malformed_records": malformed,
            "unresolved_mappings": unresolved_mappings,
        }

        if verbose:
            print()
            print("Existing diseases:")
            print(f"  {report['existing_diseases']}")
            print()
            print("New diseases successfully added:")
            print(f"  {report['new_diseases']}")
            print()
            print("Total diseases:")
            print(f"  {report['total_diseases']}")
            print()
            print("Existing symptoms:")
            print(f"  {report['existing_symptoms']}")
            print()
            print("New symptoms:")
            print(f"  {report['new_symptoms']}")
            print()
            print("Total unique symptoms:")
            print(f"  {report['total_symptoms']}")
            print()
            print("Disease-symptom relationships:")
            print(f"  {report['disease_symptom_relationships']}")
            print()
            if malformed:
                print(f"WARNING: {len(malformed)} malformed record(s) skipped: {malformed}")
            if unresolved_mappings:
                print(
                    f"WARNING: {len(unresolved_mappings)} mapping row(s) could not be "
                    f"resolved to a disease/symptom: {unresolved_mappings}"
                )

        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx-dir",
        default=None,
        help=f"Directory containing the 3 xlsx files (default: {DEFAULT_XLSX_DIR})",
    )
    args = parser.parse_args()
    run(xlsx_dir=args.xlsx_dir)
