from datetime import datetime

from extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reminders = db.relationship(
        "Reminder", backref="user", cascade="all, delete-orphan", lazy=True
    )
    messages = db.relationship(
        "ChatMessage", backref="user", cascade="all, delete-orphan", lazy=True
    )

    def to_public_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email}


class Reminder(db.Model):
    __tablename__ = "reminders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    medication_name = db.Column(db.String(200), nullable=False)
    dosage = db.Column(db.String(120))
    time_of_day = db.Column(db.String(5))  # "HH:MM", 24h
    frequency = db.Column(db.String(50), default="daily")
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "medication_name": self.medication_name,
            "dosage": self.dosage,
            "time_of_day": self.time_of_day,
            "frequency": self.frequency,
            "notes": self.notes,
            "active": self.active,
        }


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    role = db.Column(db.String(20), nullable=False)  # "user" | "assistant"
    content = db.Column(db.Text, nullable=False)
    symptoms = db.Column(db.Text)  # JSON-encoded list of symptom strings
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- Disease knowledge base -------------------------------------------------
#
# Scalable, data-driven replacement for the old hardcoded ALL_SYMPTOMS list /
# DISEASE_INFO dict / trained-at-boot decision tree. Diseases and symptoms are
# rows, not Python source; growing from 41 diseases to 1000+ means adding
# rows via backend/scripts/seed_diseases.py, not editing application code.


class Symptom(db.Model):
    __tablename__ = "symptoms"

    id = db.Column(db.Integer, primary_key=True)
    # Canonical machine identifier, underscored (e.g. "joint_pain"). This is
    # the same string format used throughout the existing `answers` API
    # contract (`[[symptom_name, bool], ...]`), so the chat request/response
    # shape doesn't need to change.
    name = db.Column(db.String(150), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(80), index=True)
    # Nullable — only set when there's an actual data source for it; never
    # fabricated just to fill the column.
    severity_relevance = db.Column(db.String(20))

    # Provenance metadata, populated by import scripts that actually have
    # it (e.g. scripts/import_disease_expansion.py). NULL for symptoms that
    # predate this — e.g. the original migrated dataset never carried this
    # level of citation, so there's nothing honest to backfill.
    source = db.Column(db.String(300))
    source_type = db.Column(db.String(150))
    reference = db.Column(db.String(300))
    verification_status = db.Column(db.String(150))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    aliases = db.relationship(
        "SymptomAlias", backref="symptom", cascade="all, delete-orphan", lazy=True
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "source_type": self.source_type,
            "reference": self.reference,
            "verification_status": self.verification_status,
        }


class SymptomAlias(db.Model):
    __tablename__ = "symptom_aliases"

    id = db.Column(db.Integer, primary_key=True)
    symptom_id = db.Column(db.Integer, db.ForeignKey("symptoms.id"), nullable=False, index=True)
    alias = db.Column(db.String(150), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint("symptom_id", "alias", name="uq_symptom_alias"),)


class Disease(db.Model):
    __tablename__ = "diseases"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    category = db.Column(db.String(100), index=True)
    # 0-100, migrated from the project's original doc_consult.csv. severity
    # label below is derived from this rather than stored redundantly.
    risk_score = db.Column(db.Integer, default=0)

    # Enrichment fields the schema supports but that are intentionally left
    # NULL for data we don't actually have — see README "Medical data
    # quality" section. Never auto-filled with generated text.
    causes = db.Column(db.Text)
    risk_factors = db.Column(db.Text)
    prevention = db.Column(db.Text)
    when_to_see_doctor = db.Column(db.Text)
    emergency_warning_signs = db.Column(db.Text)
    management = db.Column(db.Text)
    age_sex_notes = db.Column(db.Text)

    source = db.Column(db.String(300))
    # Populated by scripts/import_disease_expansion.py; NULL for the
    # originally-migrated dataset, which only ever had the free-text
    # `source` string above, not this level of structured citation.
    source_type = db.Column(db.String(150))
    reference = db.Column(db.String(300))
    verification_status = db.Column(db.String(150))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    symptom_links = db.relationship(
        "DiseaseSymptom", backref="disease", cascade="all, delete-orphan", lazy=True
    )
    aliases = db.relationship(
        "DiseaseAlias", backref="disease", cascade="all, delete-orphan", lazy=True
    )

    @property
    def severity_label(self):
        score = self.risk_score or 0
        if score >= 80:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 35:
            return "medium"
        return "low"

    def to_dict(self, include_enrichment=False):
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_score": self.risk_score,
            "severity": self.severity_label,
            "source": self.source,
        }
        if include_enrichment:
            data.update(
                {
                    "causes": self.causes,
                    "risk_factors": self.risk_factors,
                    "prevention": self.prevention,
                    "when_to_see_doctor": self.when_to_see_doctor,
                    "emergency_warning_signs": self.emergency_warning_signs,
                    "management": self.management,
                    "age_sex_notes": self.age_sex_notes,
                    "source_type": self.source_type,
                    "reference": self.reference,
                    "verification_status": self.verification_status,
                }
            )
        return data


class DiseaseAlias(db.Model):
    __tablename__ = "disease_aliases"

    id = db.Column(db.Integer, primary_key=True)
    disease_id = db.Column(db.Integer, db.ForeignKey("diseases.id"), nullable=False, index=True)
    alias = db.Column(db.String(200), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint("disease_id", "alias", name="uq_disease_alias"),)


class DiseaseSymptom(db.Model):
    """Many-to-many link between Disease and Symptom — the relational
    replacement for the old dense CSV matrix. `is_common` / `weight` let the
    scoring engine distinguish a defining symptom from an occasional one
    instead of treating every symptom of a disease as equally significant.
    """

    __tablename__ = "disease_symptoms"

    id = db.Column(db.Integer, primary_key=True)
    disease_id = db.Column(db.Integer, db.ForeignKey("diseases.id"), nullable=False, index=True)
    symptom_id = db.Column(db.Integer, db.ForeignKey("symptoms.id"), nullable=False, index=True)
    is_common = db.Column(db.Boolean, default=True, nullable=False)
    weight = db.Column(db.Float, default=1.0, nullable=False)

    # Raw source data for links imported with richer per-pair metadata (see
    # scripts/import_disease_expansion.py). `importance_label` is the
    # dataset's own categorical label ("high"/"medium"/"supporting"),
    # preserved verbatim — `is_common`/`weight` above are Healora's own
    # derived ranking heuristic, not a restatement of a clinical
    # probability. `rank` is the source's 1-based symptom ordering for that
    # disease. All NULL for links that came from the original CSV
    # migration, which didn't carry this metadata.
    rank = db.Column(db.Integer)
    importance_label = db.Column(db.String(20))
    source_type = db.Column(db.String(150))
    reference = db.Column(db.String(300))
    verification_status = db.Column(db.String(150))

    symptom = db.relationship("Symptom")

    __table_args__ = (
        db.UniqueConstraint("disease_id", "symptom_id", name="uq_disease_symptom"),
    )
