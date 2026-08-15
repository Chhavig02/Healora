import os
import warnings

from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore", category=DeprecationWarning)

from flask import Flask, jsonify
from flask_cors import CORS

from auth import auth_bp
from chat import chat_bp
from config import Config
from diseases import diseases_bp
from extensions import db
from models import Symptom
from reminders import reminders_bp
from schema_sync import sync_schema
from scripts.seed_diseases import migrate_legacy_csv


def create_app():
    flask_app = Flask(__name__)
    flask_app.config.from_object(Config())

    origins = flask_app.config["CORS_ORIGINS"]
    CORS(flask_app, origins="*" if origins == "*" else origins.split(","))

    db.init_app(flask_app)
    with flask_app.app_context():
        db.create_all()
        sync_schema(db)
        # A freshly created database (first boot against a new DATABASE_URL,
        # e.g. a new deploy) has no Disease/Symptom rows yet, and nothing
        # else runs the seed step automatically — every symptom check would
        # silently fail to match anything. migrate_legacy_csv is idempotent
        # (matches by unique name), so this is safe to check on every boot.
        if Symptom.query.count() == 0:
            flask_app.logger.info("Empty symptom table detected — running legacy CSV seed migration.")
            migrate_legacy_csv(verbose=False)

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(reminders_bp)
    flask_app.register_blueprint(chat_bp)
    flask_app.register_blueprint(diseases_bp)

    @flask_app.route("/", methods=["GET"])
    def home():
        return jsonify(
            {
                "status": "Healora Backend is running",
                "endpoints": [
                    "/api/chat",
                    "/api/symptoms",
                    "/api/tips",
                    "/api/diseases",
                    "/api/diseases/<id>",
                    "/api/auth/signup",
                    "/api/auth/login",
                    "/api/auth/me",
                    "/api/reminders",
                ],
            }
        )

    return flask_app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # threaded=True matters here: a slow/retrying Gemini call must not block
    # unrelated requests (including emergency detection) on the single dev
    # server thread. Production concurrency is controlled via the Procfile's
    # gunicorn worker/thread flags instead.
    app.run(
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
        threaded=True,
    )
