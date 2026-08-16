"""Flask HTTP adapter for the chat API. All conversation decision-making
lives in orchestrator.py (see its module docstring for the architecture) —
this file only parses the request, calls it, and serializes the response.
"""

from flask import Blueprint, jsonify, request

import conversation_state as cs
import orchestrator
import symptom_engine
from auth import optional_token
from health_tips import get_daily_tip

chat_bp = Blueprint("chat", __name__, url_prefix="/api")


@chat_bp.route("/chat", methods=["POST"])
@optional_token
def chat():
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    answers = data.get("answers", [])
    state = cs.normalize(data.get("state"))
    user = request.current_user

    result = orchestrator.handle_message(user_input, answers, state, user)
    result.setdefault("answers", answers)
    result.setdefault("state", state)
    return jsonify(result)


@chat_bp.route("/symptoms", methods=["GET"])
def get_all_symptoms():
    return jsonify({"symptoms": symptom_engine.list_symptoms_display()})


@chat_bp.route("/tips", methods=["GET"])
def tips():
    return jsonify({"tip": get_daily_tip()})
