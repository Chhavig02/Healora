import os
import sys
import tempfile
import uuid

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Must happen before `app`/`config` are imported anywhere (including by
# other test modules pytest collects) so the real dev/production database
# is never touched by the test suite.
_TMP_DB_PATH = os.path.join(tempfile.gettempdir(), f"healora_test_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-000000"
# Empty, not popped: app.py's load_dotenv() only fills in keys that are
# *absent* from the environment (override=False). A pop here would leave
# GEMINI_API_KEY absent, and load_dotenv() would then load the real key
# from backend/.env right back in — silently making tests hit the network.
os.environ["GEMINI_API_KEY"] = ""

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from scripts.seed_diseases import migrate_legacy_csv  # noqa: E402


@pytest.fixture(scope="session")
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    yield flask_app


@pytest.fixture(scope="session")
def seeded(app):
    """Runs the real migration once per test session against the temp DB —
    this both is the integration test for the seed script itself, and gives
    every other test the actual 41-disease dataset to work against."""
    with app.app_context():
        stats = migrate_legacy_csv(verbose=False)
    return stats


@pytest.fixture()
def client(app, seeded):
    return app.test_client()


@pytest.fixture()
def app_ctx(app, seeded):
    with app.app_context():
        yield app


@pytest.fixture()
def unique_email():
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture()
def auth_headers(client, unique_email):
    resp = client.post(
        "/api/auth/signup",
        json={"name": "Test User", "email": unique_email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.get_json()
    token = resp.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}
