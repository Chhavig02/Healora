"""Generic, data-driven disease ranking and adaptive follow-up questions.

No disease-specific logic lives here — everything is derived from the
Disease/Symptom/DiseaseSymptom rows in the database (see models.py), so
growing the dataset from 41 diseases to 1000+ requires zero changes to this
module — only more rows, via scripts/seed_diseases.py.

This replaces the old `sklearn.DecisionTreeClassifier` trained fresh on
every boot. Scores are a relevance signal for ranking, not a diagnostic
probability — never surface them to the user as e.g. "82% chance of X".
"""

from collections import Counter, defaultdict

from models import Disease, DiseaseSymptom, Symptom

STRONG_SCORE = 25
MODERATE_SCORE = 10
MAX_QUESTIONS = 6
MAX_CANDIDATES_FOR_QUESTIONS = 5
RESULT_LIST_SIZE = 5

# Deterministic, severity-derived next-step copy — not a fabricated
# clinical recommendation, just a plain-language nudge tied to the same
# Disease.severity_label the UI already surfaces via MatchBadge.
_NEXT_STEP_BY_SEVERITY = {
    "critical": (
        "Please seek medical care soon — these symptoms warrant prompt "
        "evaluation by a healthcare professional."
    ),
    "high": "It's a good idea to see a doctor soon to discuss these symptoms.",
    "medium": (
        "Consider checking in with a healthcare professional, especially if "
        "symptoms persist or worsen."
    ),
    "low": (
        "Monitor your symptoms and consult a healthcare professional if they "
        "persist, worsen, or you're concerned."
    ),
}


def _match_strength(score):
    if score >= STRONG_SCORE:
        return "strong"
    if score >= MODERATE_SCORE:
        return "moderate"
    return "possible"


def get_disease_by_name(name):
    return Disease.query.filter_by(name=name).first()


def _symptom_name_to_id_map(names):
    if not names:
        return {}
    rows = Symptom.query.filter(Symptom.name.in_(names)).all()
    return {r.name: r.id for r in rows}


def rank_diseases(yes_names, no_names, limit=RESULT_LIST_SIZE):
    """Rank candidate diseases by weighted symptom overlap, highest first.

    Only diseases sharing at least one confirmed ("yes") symptom are
    considered, via a targeted query — this stays efficient without loading
    the whole diseases table, regardless of how large it grows.
    """
    yes_ids = set(_symptom_name_to_id_map(yes_names).values())
    no_ids = set(_symptom_name_to_id_map(no_names).values())

    if not yes_ids:
        return []

    candidate_rows = (
        DiseaseSymptom.query.filter(DiseaseSymptom.symptom_id.in_(yes_ids))
        .with_entities(DiseaseSymptom.disease_id)
        .distinct()
        .all()
    )
    candidate_disease_ids = [r[0] for r in candidate_rows]
    if not candidate_disease_ids:
        return []

    all_links = DiseaseSymptom.query.filter(
        DiseaseSymptom.disease_id.in_(candidate_disease_ids)
    ).all()
    links_by_disease = defaultdict(list)
    for link in all_links:
        links_by_disease[link.disease_id].append(link)

    scored = []
    for disease_id, links in links_by_disease.items():
        overlap_weight = sum(l.weight for l in links if l.symptom_id in yes_ids)
        overlap_count = sum(1 for l in links if l.symptom_id in yes_ids)
        if overlap_count == 0:
            continue
        penalty_weight = sum(l.weight for l in links if l.symptom_id in no_ids)
        total_weight = sum(l.weight for l in links) or 1.0
        score = (overlap_weight * 10) - (penalty_weight * 6) - (total_weight * 0.15)
        scored.append((disease_id, score, links))

    scored.sort(key=lambda t: t[1], reverse=True)
    top = scored[:limit]
    if not top:
        return []

    diseases = {
        d.id: d for d in Disease.query.filter(Disease.id.in_([t[0] for t in top])).all()
    }

    results = []
    for disease_id, score, links in top:
        disease = diseases.get(disease_id)
        if not disease:
            continue
        matched = sorted({l.symptom.display_name for l in links if l.symptom_id in yes_ids})
        missing_common = sorted(
            {
                l.symptom.display_name
                for l in links
                if l.is_common and l.symptom_id not in yes_ids and l.symptom_id not in no_ids
            }
        )
        results.append(
            {
                "id": disease.id,
                "name": disease.name,
                "description": disease.description,
                "risk": disease.risk_score,
                "severity": disease.severity_label,
                "source": disease.source,
                "score": round(score, 2),
                "match_strength": _match_strength(score),
                "matched_symptoms": matched,
                "possible_missing_symptoms": missing_common[:5],
            }
        )
    return results


def _links_for_diseases(disease_ids):
    links = DiseaseSymptom.query.filter(DiseaseSymptom.disease_id.in_(disease_ids)).all()
    by_disease = defaultdict(list)
    for link in links:
        by_disease[link.disease_id].append(link)
    return by_disease


def pick_next_symptom(candidate_disease_ids, known_symptom_ids):
    """Pick the unanswered symptom that best splits the top candidate
    diseases — present in some but not all of them, so the answer actually
    changes the ranking. Returns a Symptom or None if nothing useful is
    left to ask (caller should present a result instead).
    """
    candidate_ids = candidate_disease_ids[:MAX_CANDIDATES_FOR_QUESTIONS]
    if len(candidate_ids) < 2:
        return None

    links_by_disease = _links_for_diseases(candidate_ids)
    n = len(candidate_ids)
    counts = Counter()
    symptom_by_id = {}

    for disease_id in candidate_ids:
        seen = set()
        for link in links_by_disease.get(disease_id, []):
            if link.symptom_id in known_symptom_ids or link.symptom_id in seen:
                continue
            seen.add(link.symptom_id)
            counts[link.symptom_id] += 1
            symptom_by_id[link.symptom_id] = link.symptom

    if not counts:
        return None

    target = n / 2
    best_id = min(counts, key=lambda sid: (abs(counts[sid] - target), -counts[sid]))
    if counts[best_id] >= n:
        # present in every top candidate — doesn't distinguish anything
        return None
    return symptom_by_id[best_id]


def get_next_step(answers):
    """answers: list of [symptom_name, bool]. Returns a dict — either a
    follow-up question or a ranked result, in the same shape the original
    decision-tree engine returned (`type`, `symptom`/`disease` etc.),
    extended with `possible_conditions` and `match_strength`.

    Returns None if no disease in the database shares any confirmed
    symptom — the caller should fall back to asking the user to describe
    things differently rather than presenting an empty result.
    """
    yes_names = [a[0] for a in answers if a[1]]
    no_names = [a[0] for a in answers if not a[1]]

    ranked = rank_diseases(yes_names, no_names, limit=RESULT_LIST_SIZE)
    if not ranked:
        return None

    top = ranked[0]
    # Weights are continuous (0.5-3.0), so a single very-common symptom can
    # clear STRONG_SCORE on its own — require at least 2 corroborating
    # symptoms from the candidate itself before treating that as settled,
    # not just one lucky high-weight match.
    strong_enough = (
        top["score"] >= STRONG_SCORE and len(top["matched_symptoms"]) >= 2
    ) or len(yes_names) >= 4
    ran_out_of_questions = len(answers) >= MAX_QUESTIONS

    if not (strong_enough or ran_out_of_questions):
        known_ids = set(_symptom_name_to_id_map(yes_names + no_names).values())
        candidate_ids = [c["id"] for c in ranked]
        next_symptom = pick_next_symptom(candidate_ids, known_ids)
        if next_symptom is not None:
            return {
                "type": "question",
                "symptom": next_symptom.display_name + "?",
                "raw_symptom": next_symptom.name,
            }

    return {
        "type": "result",
        "disease": top["name"],
        "description": top["description"]
        or "Please consult a medical professional for more details.",
        "risk": top["risk"],
        "severity": top["severity"],
        "match_strength": top["match_strength"],
        "symptoms": top["matched_symptoms"] + top["possible_missing_symptoms"],
        "symptoms_present": [n.replace("_", " ") for n in yes_names],
        "symptoms_denied": [n.replace("_", " ") for n in no_names],
        # Common symptoms of the top candidate that are neither confirmed
        # nor denied yet — i.e. what's still genuinely uncertain about this
        # assessment, not a probability estimate.
        "uncertain_symptoms": top["possible_missing_symptoms"],
        "next_step_recommendation": _NEXT_STEP_BY_SEVERITY.get(
            top["severity"], _NEXT_STEP_BY_SEVERITY["low"]
        ),
        "possible_conditions": [
            {
                "name": c["name"],
                "description": (c["description"] or "")[:220],
                "risk": c["risk"],
                "severity": c["severity"],
                "match_strength": c["match_strength"],
                # Why this candidate is being considered — the specific
                # confirmed symptoms it shares with the user, so the
                # "differential" reads as reasoned rather than asserted.
                "matched_symptoms": c["matched_symptoms"],
            }
            for c in ranked
        ],
        "disclaimer": (
            "Educational guidance based on the symptoms you described — not a medical "
            "diagnosis. Please consult a healthcare professional, especially if symptoms "
            "are severe or persist."
        ),
    }
