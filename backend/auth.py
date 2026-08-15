import datetime
import re
from functools import wraps

import jwt
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def generate_token(user):
    payload = {
        "user_id": user.id,
        "exp": datetime.datetime.utcnow()
        + datetime.timedelta(hours=current_app.config["JWT_EXPIRY_HOURS"]),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _extract_token():
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return None


def _resolve_user_from_token(token):
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        return None
    return db.session.get(User, payload.get("user_id"))


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _resolve_user_from_token(_extract_token())
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def optional_token(f):
    """Resolves request.current_user if a valid token is present, else None.
    Does not reject the request either way — used by endpoints that behave
    the same for guests but personalize when logged in."""

    @wraps(f)
    def decorated(*args, **kwargs):
        request.current_user = _resolve_user_from_token(_extract_token())
        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "name, email and password are required"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Please provide a valid email address"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists"}), 409

    user = User(name=name, email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()

    token = generate_token(user)
    return jsonify({"token": token, "user": user.to_public_dict()}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = generate_token(user)
    return jsonify({"token": token, "user": user.to_public_dict()})


@auth_bp.route("/me", methods=["GET"])
@token_required
def me():
    return jsonify(request.current_user.to_public_dict())
