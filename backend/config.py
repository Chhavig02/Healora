import os


def _normalize_db_url(url):
    # Render/Heroku hand out "postgres://" but SQLAlchemy 1.4+/psycopg2 need "postgresql://"
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    """Instantiated fresh (`Config()`) rather than passed as a bare class —
    this reads env vars at __init__ time instead of freezing them as class
    attributes at import time, so a test (or anything else calling
    create_app() more than once in-process) can point separate calls at
    separate databases by changing os.environ first.
    """

    def __init__(self):
        self.SECRET_KEY = os.environ.get("JWT_SECRET", "dev-secret-change-me")
        self.SQLALCHEMY_DATABASE_URI = _normalize_db_url(
            os.environ.get("DATABASE_URL") or "sqlite:///healora.db"
        )
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False
        self.JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "168"))
        self.GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        self.GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        self.CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
