"""Read-only browse API over the disease knowledge base — mainly for
transparency/QA (verifying a seed actually populated what you expect) and
for any future admin UI. Not used by the chat flow itself.
"""

from flask import Blueprint, jsonify, request

from extensions import db
from models import Disease

diseases_bp = Blueprint("diseases", __name__, url_prefix="/api/diseases")

MAX_PAGE_SIZE = 100


@diseases_bp.route("", methods=["GET"])
def list_diseases():
    search = (request.args.get("q") or "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(MAX_PAGE_SIZE, max(1, int(request.args.get("page_size", 25))))
    except ValueError:
        page_size = 25

    query = Disease.query
    if search:
        query = query.filter(Disease.name.ilike(f"%{search}%"))

    total = query.count()
    rows = (
        query.order_by(Disease.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jsonify(
        {
            "total": total,
            "page": page,
            "page_size": page_size,
            "diseases": [d.to_dict() for d in rows],
        }
    )


@diseases_bp.route("/<int:disease_id>", methods=["GET"])
def get_disease(disease_id):
    disease = db.session.get(Disease, disease_id)
    if not disease:
        return jsonify({"error": "Disease not found"}), 404

    symptoms = [
        {
            "name": link.symptom.name,
            "display_name": link.symptom.display_name,
            "is_common": link.is_common,
            "weight": link.weight,
        }
        for link in disease.symptom_links
    ]
    symptoms.sort(key=lambda s: (-s["is_common"], -s["weight"]))

    data = disease.to_dict(include_enrichment=True)
    data["symptoms"] = symptoms
    data["aliases"] = [a.alias for a in disease.aliases]
    return jsonify(data)
