from flask import Blueprint, jsonify, request

from auth import token_required
from extensions import db
from models import Reminder

reminders_bp = Blueprint("reminders", __name__, url_prefix="/api/reminders")

VALID_FREQUENCIES = {"daily", "twice_daily", "weekly", "as_needed"}


@reminders_bp.route("", methods=["GET"])
@token_required
def list_reminders():
    reminders = (
        Reminder.query.filter_by(user_id=request.current_user.id)
        .order_by(Reminder.time_of_day.asc())
        .all()
    )
    return jsonify({"reminders": [r.to_dict() for r in reminders]})


@reminders_bp.route("", methods=["POST"])
@token_required
def create_reminder():
    data = request.get_json(silent=True) or {}
    name = (data.get("medication_name") or "").strip()
    if not name:
        return jsonify({"error": "medication_name is required"}), 400

    frequency = data.get("frequency", "daily")
    if frequency not in VALID_FREQUENCIES:
        frequency = "daily"

    reminder = Reminder(
        user_id=request.current_user.id,
        medication_name=name,
        dosage=(data.get("dosage") or "").strip() or None,
        time_of_day=(data.get("time_of_day") or "").strip() or None,
        frequency=frequency,
        notes=(data.get("notes") or "").strip() or None,
    )
    db.session.add(reminder)
    db.session.commit()
    return jsonify(reminder.to_dict()), 201


@reminders_bp.route("/<int:reminder_id>", methods=["PUT"])
@token_required
def update_reminder(reminder_id):
    reminder = Reminder.query.filter_by(
        id=reminder_id, user_id=request.current_user.id
    ).first()
    if not reminder:
        return jsonify({"error": "Reminder not found"}), 404

    data = request.get_json(silent=True) or {}
    if "medication_name" in data:
        name = (data["medication_name"] or "").strip()
        if not name:
            return jsonify({"error": "medication_name cannot be empty"}), 400
        reminder.medication_name = name
    if "dosage" in data:
        reminder.dosage = (data["dosage"] or "").strip() or None
    if "time_of_day" in data:
        reminder.time_of_day = (data["time_of_day"] or "").strip() or None
    if "frequency" in data and data["frequency"] in VALID_FREQUENCIES:
        reminder.frequency = data["frequency"]
    if "notes" in data:
        reminder.notes = (data["notes"] or "").strip() or None
    if "active" in data:
        reminder.active = bool(data["active"])

    db.session.commit()
    return jsonify(reminder.to_dict())


@reminders_bp.route("/<int:reminder_id>", methods=["DELETE"])
@token_required
def delete_reminder(reminder_id):
    reminder = Reminder.query.filter_by(
        id=reminder_id, user_id=request.current_user.id
    ).first()
    if not reminder:
        return jsonify({"error": "Reminder not found"}), 404

    db.session.delete(reminder)
    db.session.commit()
    return "", 204
