"""Regression coverage for the "headache doesn't match" bug.

Root cause: create_app() never populated the database on its own — only a
manual `python scripts/seed_diseases.py` run did. A freshly created database
(first boot against a new DATABASE_URL, e.g. a new deploy) had zero Symptom
rows, so every symptom check — including the trivial "I have a headache" —
fell through to the generic "couldn't confidently match" message, no matter
how good the extraction/normalization logic downstream was.

This module builds its own app via create_app() against a brand-new, never
manually seeded database (same isolation pattern as
test_disease_expansion.py), to prove the auto-seed-on-empty-db behavior
added to app.py actually runs on startup rather than relying on the shared
`seeded` fixture other test modules use.
"""

import os
import tempfile
import uuid

import pytest

_DB_PATH = os.path.join(tempfile.gettempdir(), f"healora_startup_test_{uuid.uuid4().hex}.db")


@pytest.fixture(scope="module")
def fresh_app():
    original = {k: os.environ.get(k) for k in ("DATABASE_URL", "JWT_SECRET", "GEMINI_API_KEY")}

    os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
    os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-000000"
    os.environ["GEMINI_API_KEY"] = ""  # exercise the local deterministic pipeline only

    from app import create_app

    # No seed script called manually anywhere in this fixture — create_app()
    # itself must populate the database.
    flask_app = create_app()
    yield flask_app

    for key, value in original.items():
        if value is not None:
            os.environ[key] = value


@pytest.fixture()
def fresh_client(fresh_app):
    return fresh_app.test_client()


def test_create_app_auto_seeds_an_empty_database(fresh_app):
    with fresh_app.app_context():
        from models import Disease, Symptom

        assert Symptom.query.count() > 0
        assert Disease.query.count() > 0
        assert Symptom.query.filter_by(name="headache").first() is not None


def test_create_app_auto_seed_is_idempotent_on_second_boot(fresh_app):
    # A second create_app() call (e.g. a second gunicorn worker booting
    # against the same already-seeded database) must not duplicate rows.
    with fresh_app.app_context():
        from models import Disease, Symptom

        before_d, before_s = Disease.query.count(), Symptom.query.count()

    from app import create_app

    create_app()

    with fresh_app.app_context():
        from models import Disease, Symptom

        assert Disease.query.count() == before_d
        assert Symptom.query.count() == before_s


@pytest.mark.parametrize(
    "text,expected_symptom",
    [
        ("I have a headache", "headache"),
        ("headache", "headache"),
        ("I have fever", "high_fever"),
    ],
)
def test_single_symptom_input_is_recognized_not_rejected(fresh_client, text, expected_symptom):
    resp = fresh_client.post("/api/chat", json={"message": text, "answers": []})
    data = resp.get_json()
    assert [expected_symptom, True] in data["answers"]
    assert data["next_step"]["type"] in ("question", "result")
    # the generic "couldn't confidently match" fallback must not fire
    assert "couldn't confidently match" not in (data.get("message") or "")


def test_two_known_symptoms_reach_a_result_or_question(fresh_client):
    resp = fresh_client.post(
        "/api/chat", json={"message": "I have a fever and headache", "answers": []}
    )
    data = resp.get_json()
    assert {"high_fever", "headache"} <= {a[0] for a in data["answers"]}
    assert data["next_step"]["type"] in ("question", "result")


def test_known_plus_unknown_symptom_keeps_the_known_one(fresh_client):
    # "cold" isn't a canonical symptom (there's no generic "cold" — see
    # symptom_aliases_seed.py); "fever" is. The unknown word must not cause
    # the valid "fever" extraction to be discarded too.
    resp = fresh_client.post(
        "/api/chat", json={"message": "I have cold and fever", "answers": []}
    )
    data = resp.get_json()
    assert ["high_fever", True] in data["answers"]
    assert data["next_step"]["type"] in ("question", "result")


def test_completely_unknown_symptom_asks_for_more_detail_not_error(fresh_client):
    resp = fresh_client.post(
        "/api/chat", json={"message": "qwerty zzz nonsense", "answers": []}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["next_step"]["type"] == "waiting"
    assert data["answers"] == []
