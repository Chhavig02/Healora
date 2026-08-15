"""Idempotent importer for Healora's disease knowledge base.

Two data sources, both safe to re-run any number of times:

1. The project's original dataset (Training.csv + doc_consult.csv + the
   curated descriptions in data/legacy_disease_info.py) — the primary
   migration path, preserving every disease/symptom the app already had.
2. An optional JSON file of additional diseases, for growing past the
   original 41 without touching application code. See `DISEASE_JSON_SCHEMA`
   below for the expected shape.

Usage (from the backend/ directory):

    python scripts/seed_diseases.py                # migrate the bundled CSVs
    python scripts/seed_diseases.py --json more.json  # also import extra diseases
    python scripts/seed_diseases.py --json more.json --skip-csv  # JSON only

Idempotency: diseases/symptoms are matched by unique name, disease-symptom
links by a (disease_id, symptom_id) unique constraint. Re-running updates
existing rows in place rather than duplicating them.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import create_app  # noqa: E402
from data.legacy_disease_info import DISEASE_INFO  # noqa: E402
from data.symptom_aliases_seed import SYMPTOM_ALIASES_SEED  # noqa: E402
from extensions import db  # noqa: E402
from models import Disease, DiseaseAlias, DiseaseSymptom, Symptom, SymptomAlias  # noqa: E402

# The bundled dataset has inconsistent whitespace: the raw CSV itself has
# "Hypertension " (trailing space) as a prognosis value, and DISEASE_INFO
# separately has "Diabetes " (trailing space) as a dict key that doesn't
# match the CSV's clean "Diabetes" at all. Both are stripped before lookup
# so descriptions aren't silently dropped for either disease.
_DISEASE_INFO_BY_STRIPPED_NAME = {k.strip(): v for k, v in DISEASE_INFO.items()}

TRAINING_CSV = os.path.join(_BACKEND_DIR, "Training.csv")
DOC_CONSULT_CSV = os.path.join(_BACKEND_DIR, "doc_consult.csv")

LEGACY_SOURCE = (
    "Migrated from Healora's original bundled dataset "
    "(Training.csv / doc_consult.csv) and its curated disease descriptions."
)

# A symptom counted as "common" for a disease if it appears in at least this
# fraction of that disease's training rows; otherwise it's "less common".
# Both are kept (not dropped) so the matcher can still use rarer symptoms as
# distinguishing follow-up questions.
COMMON_THRESHOLD = 0.5

DISEASE_JSON_SCHEMA = """
[
  {
    "name": "Dengue",
    "description": "A mosquito-borne viral disease...",
    "category": "Infectious disease",
    "risk_score": 65,
    "source": "https://www.who.int/news-room/fact-sheets/detail/dengue-and-severe-dengue",
    "causes": "...",                  # optional
    "risk_factors": "...",            # optional
    "prevention": "...",              # optional
    "when_to_see_doctor": "...",      # optional
    "emergency_warning_signs": "...", # optional
    "management": "...",              # optional
    "age_sex_notes": "...",           # optional
    "aliases": ["breakbone fever"],   # optional
    "symptoms": [
      {"name": "high_fever", "is_common": true, "weight": 2.5},
      {"name": "headache", "is_common": true, "weight": 2.0},
      {"name": "rash", "is_common": false, "weight": 1.0}
    ]
  }
]
"""


def _norm_symptom_name(raw):
    return raw.strip().lower().replace(" ", "_")


def _display_name(canonical):
    return canonical.replace("_", " ").strip().capitalize()


def _read_training(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        symptom_cols = [h.strip() for h in header[:-1]]
        rows_by_disease = defaultdict(list)
        for row in reader:
            if not row or len(row) < len(header):
                continue
            disease = row[-1].strip()
            try:
                values = [int(v) for v in row[:-1]]
            except ValueError:
                continue
            rows_by_disease[disease].append(values)
    return symptom_cols, rows_by_disease


def _read_risk_scores(path):
    risk = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            try:
                risk[row[0].strip()] = int(row[1])
            except ValueError:
                continue
    return risk


def _get_or_create_symptom(cache, canonical_name):
    canonical_name = _norm_symptom_name(canonical_name)
    if canonical_name in cache:
        return cache[canonical_name]
    symptom = Symptom.query.filter_by(name=canonical_name).first()
    if not symptom:
        symptom = Symptom(name=canonical_name, display_name=_display_name(canonical_name))
        db.session.add(symptom)
        db.session.flush()
    cache[canonical_name] = symptom
    return symptom


def _get_or_create_disease(name, description, risk_score, source, category=None):
    disease = Disease.query.filter_by(name=name).first()
    created = False
    if not disease:
        disease = Disease(
            name=name,
            description=description or None,
            risk_score=risk_score or 0,
            source=source,
            category=category,
        )
        db.session.add(disease)
        db.session.flush()
        created = True
    else:
        if not disease.description and description:
            disease.description = description
        if not disease.risk_score and risk_score:
            disease.risk_score = risk_score
        if not disease.source and source:
            disease.source = source
        if not disease.category and category:
            disease.category = category
    return disease, created


def _link_disease_symptom(disease, symptom, is_common, weight):
    existing = DiseaseSymptom.query.filter_by(
        disease_id=disease.id, symptom_id=symptom.id
    ).first()
    if existing:
        existing.is_common = is_common
        existing.weight = weight
        return existing, False
    link = DiseaseSymptom(
        disease_id=disease.id, symptom_id=symptom.id, is_common=is_common, weight=weight
    )
    db.session.add(link)
    return link, True


def migrate_legacy_csv(verbose=True):
    symptom_cols, rows_by_disease = _read_training(TRAINING_CSV)
    risk_scores = _read_risk_scores(DOC_CONSULT_CSV)

    symptom_cache = {}
    stats = {"diseases_created": 0, "diseases_updated": 0, "links_processed": 0}
    missing_descriptions = []

    for disease_name, rows in rows_by_disease.items():
        n = len(rows)
        # Frequency (not the old code's lossy `.max()` OR-collapse) so we can
        # tell a defining symptom from an occasional one.
        freq = [sum(r[i] for r in rows) / n for i in range(len(symptom_cols))]

        description = (_DISEASE_INFO_BY_STRIPPED_NAME.get(disease_name) or "").strip() or None
        if not description:
            missing_descriptions.append(disease_name)
        risk = risk_scores.get(disease_name, 0)
        disease, created = _get_or_create_disease(
            disease_name, description, risk, source=LEGACY_SOURCE
        )
        stats["diseases_created" if created else "diseases_updated"] += 1

        for col, f in zip(symptom_cols, freq):
            if f <= 0:
                continue
            symptom = _get_or_create_symptom(symptom_cache, col)
            is_common = f >= COMMON_THRESHOLD
            weight = round(0.5 + f * 2.5, 2)  # maps 0..1 frequency to 0.5..3.0 weight
            _link_disease_symptom(disease, symptom, is_common, weight)
            stats["links_processed"] += 1

    alias_count = 0
    for canonical, aliases in SYMPTOM_ALIASES_SEED.items():
        symptom = symptom_cache.get(_norm_symptom_name(canonical)) or Symptom.query.filter_by(
            name=_norm_symptom_name(canonical)
        ).first()
        if not symptom:
            continue
        for alias_text in aliases:
            alias_text = alias_text.strip().lower()
            exists = SymptomAlias.query.filter_by(symptom_id=symptom.id, alias=alias_text).first()
            if exists:
                continue
            db.session.add(SymptomAlias(symptom_id=symptom.id, alias=alias_text))
            alias_count += 1
    stats["aliases_added"] = alias_count

    db.session.commit()

    if verbose:
        print(f"[seed] legacy CSV migration: {stats}")
        if missing_descriptions:
            print(f"[seed] WARNING: no description found for: {missing_descriptions}")
        print(f"[seed] total diseases in DB: {Disease.query.count()}")
        print(f"[seed] total symptoms in DB: {Symptom.query.count()}")

    return stats


def import_diseases_from_json(path, verbose=True):
    """Add (or update) diseases from a structured JSON file — the intended
    path for growing past the original dataset without code changes. See
    DISEASE_JSON_SCHEMA at the top of this module for the expected shape.
    """
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise ValueError("Disease JSON file must contain a top-level array")

    symptom_cache = {}
    stats = {"diseases_created": 0, "diseases_updated": 0, "links_processed": 0, "skipped": 0}

    for i, record in enumerate(records):
        name = (record.get("name") or "").strip()
        if not name:
            print(f"[seed] skipping record {i}: missing 'name'")
            stats["skipped"] += 1
            continue
        symptoms = record.get("symptoms") or []
        if not symptoms:
            print(f"[seed] skipping '{name}': no symptoms listed")
            stats["skipped"] += 1
            continue

        enrichment = {
            k: record.get(k)
            for k in (
                "causes",
                "risk_factors",
                "prevention",
                "when_to_see_doctor",
                "emergency_warning_signs",
                "management",
                "age_sex_notes",
            )
        }

        disease, created = _get_or_create_disease(
            name,
            record.get("description"),
            record.get("risk_score", 0),
            source=record.get("source") or "Imported via seed_diseases.py --json (unattributed)",
            category=record.get("category"),
        )
        for field, value in enrichment.items():
            if value and not getattr(disease, field):
                setattr(disease, field, value)
        stats["diseases_created" if created else "diseases_updated"] += 1

        for alias_text in record.get("aliases", []):
            alias_text = alias_text.strip()
            if not alias_text:
                continue
            if not DiseaseAlias.query.filter_by(disease_id=disease.id, alias=alias_text).first():
                db.session.add(DiseaseAlias(disease_id=disease.id, alias=alias_text))

        for s in symptoms:
            symptom_name = s.get("name") if isinstance(s, dict) else s
            if not symptom_name:
                continue
            symptom = _get_or_create_symptom(symptom_cache, symptom_name)
            is_common = bool(s.get("is_common", True)) if isinstance(s, dict) else True
            weight = float(s.get("weight", 1.0)) if isinstance(s, dict) else 1.0
            _link_disease_symptom(disease, symptom, is_common, weight)
            stats["links_processed"] += 1

    db.session.commit()

    if verbose:
        print(f"[seed] JSON import from {path}: {stats}")

    return stats


def run(json_path=None, skip_csv=False, verbose=True):
    app = create_app()
    with app.app_context():
        if not skip_csv:
            migrate_legacy_csv(verbose=verbose)
        if json_path:
            import_diseases_from_json(json_path, verbose=verbose)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", help="Path to a JSON file of additional diseases to import")
    parser.add_argument("--skip-csv", action="store_true", help="Skip the legacy CSV migration (JSON only)")
    args = parser.parse_args()
    run(json_path=args.json_path, skip_csv=args.skip_csv)
