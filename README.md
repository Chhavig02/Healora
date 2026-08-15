# 🩺 Healora – AI-Assisted Symptom Support

## 👋 What is Healora?

**Healora** is an educational symptom-support assistant, not a diagnostic
tool. It helps you think through what you're feeling, points you toward
possible conditions worth discussing with a doctor, and lets you keep
medication reminders tied to your account.

**Healora does not diagnose disease.** Every result is framed as "possible
conditions to discuss with a doctor," never a definitive answer. Always
consult a licensed healthcare professional, especially for anything severe,
persistent, or worsening.

---

## 🌟 What Healora Does

* 💬 **Symptom-support chat** – Describe how you're feeling in your own
  words; Healora extracts known symptoms, ranks candidate conditions from
  its database, and asks a targeted follow-up question when it needs more
  information to narrow things down.
* 🧠 **Hybrid AI** – A deterministic, database-backed engine does the actual
  symptom matching and ranking (free, always available, no external calls).
  Gemini is layered on top purely as the language/NLP layer: turning free
  text into known symptom names, phrasing follow-up questions naturally, and
  writing an explanation grounded in the facts the database already
  determined. Gemini never decides what disease is being discussed and never
  invents medical facts — see [The Gemini boundary](#-the-gemini-boundary).
* 🗄️ **Scalable disease knowledge base** – Diseases and symptoms are rows in
  a database (`Disease`, `Symptom`, `DiseaseSymptom`), not a hardcoded Python
  dict or a model retrained from a CSV on every boot. Growing from dozens of
  conditions to hundreds means adding data, not editing code — see
  [Scaling the knowledge base](#-scaling-the-knowledge-base).
* 🚨 **Independent emergency safety layer** – A hardcoded keyword check
  (chest pain, can't breathe, suicidal ideation, uncontrolled bleeding, etc.)
  runs *before* any database lookup or Gemini call and is final. Nothing
  downstream — including Gemini — can see or override it.
* ⏰ **Medication reminders** – Create an account and Healora stores your
  reminders (medication, dosage, time, frequency, notes).
* 🔐 **Accounts** – Email/password signup and login (JWT-based), so
  reminders and chat history are yours alone.
* 🧾 **Personalized context** – Logged-in users' recent chat history is fed
  back into result explanations so they can reference what you've told
  Healora before, without changing what the underlying match actually is.
* 💡 **Daily tip** – A rotating wellness tip (AI-generated when Gemini is
  configured, otherwise a curated static list).

---

## 🏗️ Architecture

```
backend/
├── app.py                 Flask app factory, blueprint registration
├── config.py               Env-var-driven config
├── models.py                User/Reminder/ChatMessage + Disease/Symptom/DiseaseSymptom
├── auth.py, reminders.py, chat.py, diseases.py   Blueprints
├── disease_matcher.py      Generic DB-driven ranking + follow-up questions
├── symptom_engine.py       Free-text -> canonical symptom name matching
├── emergency.py            Independent keyword-based emergency detection
├── gemini_client.py        Gemini wrapper + the "Gemini boundary" contract
├── health_tips.py
├── data/                   Legacy dataset descriptions + curated symptom aliases
├── scripts/seed_diseases.py  Idempotent CSV/JSON -> database importer
└── tests/                  pytest suite

frontend/   React + Vite SPA — marketing site, auth pages, dashboard, chat widget
```

### The disease knowledge base

Replaces the original hardcoded ~41-disease `DISEASE_INFO` dict and a
`sklearn.DecisionTreeClassifier` retrained from a CSV on every server boot.

- **`Disease`** — name, description, category, `risk_score` (0-100, drives a
  computed `severity_label`), plus optional enrichment fields (`causes`,
  `risk_factors`, `prevention`, `when_to_see_doctor`,
  `emergency_warning_signs`, `management`, `age_sex_notes`) and a `source`
  attribution. Enrichment fields are `NULL` unless there's real data behind
  them — never auto-filled with generated text (see
  [Medical data quality](#-medical-data-quality)).
- **`Symptom`** — canonical underscored name (the same identifier used in
  the `answers` API contract), display name, optional category.
- **`DiseaseSymptom`** — the many-to-many link, with `is_common` and a
  continuous `weight` so a defining symptom counts for more than an
  occasional one. Unique-constrained on `(disease_id, symptom_id)`.
- **`SymptomAlias` / `DiseaseAlias`** — conversational phrasings mapped to a
  canonical name (`"my joints hurt"` → `joint_pain`), and disease name
  variants, respectively.

All four tables are indexed on their name columns and the foreign keys used
for lookups, so ranking queries stay targeted (`WHERE symptom_id IN (...)`)
instead of scanning every disease — see [Performance](#-performance) for
why this matters as the dataset grows.

### `disease_matcher.py` — generic ranking, no per-disease logic

`rank_diseases(yes_symptoms, no_symptoms)` scores every disease sharing at
least one confirmed symptom: `(matched_weight × 10) − (contradicted_weight
× 6) − (total_weight × 0.15)`, ranked descending. `get_next_step(answers)`
decides whether to ask another question or present a result:

- **Result** once the top candidate clears a score threshold *and* has at
  least 2 corroborating symptoms (not just one high-weight match — see the
  regression note in the source), or the user has volunteered 4+ symptoms,
  or a question budget (`MAX_QUESTIONS`) is exhausted.
- **Question** otherwise: `pick_next_symptom` looks at the top 5 candidate
  diseases' full symptom sets and picks the unanswered symptom present in
  roughly half of them — the one whose answer actually changes the ranking,
  not just any unasked symptom.

Nothing in this file references a disease by name. Add a disease to the
database and it participates in ranking and questioning automatically.

### `symptom_engine.py` — free text → canonical symptom names

Three passes, in order, all backed by the `Symptom`/`SymptomAlias` tables
(no hardcoded vocabulary):

1. **Exact phrase match** — canonical name, display name, or a known alias
   appears verbatim (word-bounded) in the message.
2. **All-significant-words match** — every non-stopword of a multi-word
   symptom/alias appears somewhere in the message, in any order (so "pain
   behind eyes" still matches "pain behind the eyes").
3. **Fuzzy single-token match** (`difflib`, cutoff 0.84) — catches typos
   like "haedache" — only attempted if the first two passes found nothing,
   to keep false positives down.

This is the always-available fallback; the vocabulary it's constrained to
is queried from the database, not hardcoded, so it grows automatically as
the dataset does.

---

## 🤖 The Gemini boundary

Gemini is the language layer only — it is never Healora's source of medical
truth. This is enforced structurally, not just by prompt wording:

| Rule | How it's enforced |
|---|---|
| Gemini never creates/edits a Disease or Symptom row | Only `scripts/seed_diseases.py` writes to those tables; no code path lets a Gemini response reach `db.session.add()` |
| Symptom names Gemini extracts are validated | `chat.py`'s `_gemini_extract_symptoms` filters every returned item against `symptom_engine.get_all_symptom_names()` (the real `Symptom` table); unresolved items are discarded and logged, never inserted |
| Disease ranking is Gemini-free | `disease_matcher.py` only reads the database; which disease is presented is decided *before* Gemini is ever called |
| Explanations are grounded, not generated from scratch | The result-explanation prompt includes the specific `Disease` row's fields and explicitly lists the only condition names Gemini is allowed to mention |
| Emergency detection is fully independent | `emergency.py` has no Gemini dependency and runs before any database lookup or model call; its decision is final |
| JSON responses are shape-validated | `gemini_client.generate_json` accepts a `validator` callable; a shape mismatch is treated exactly like an API failure |
| The disease list is never dumped into a prompt | Only the top-5 already-ranked candidates (from the database) are ever named to Gemini per turn — bounded regardless of how large the dataset gets |
| Token usage stays practical for the free tier | At most 2 Gemini calls per chat turn (extraction + phrasing), each capped at a 10s timeout (the server-enforced minimum — anything shorter is rejected outright) with no SDK-level retry — the app's own fallback is faster and just as safe as waiting on a retry loop |

This is enforced by code structure and prompt constraints, not a guarantee
against every possible model deviation — see [Limitations](#-limitations).

---

## 🚨 Emergency safety layer

`emergency.py` checks the raw message against a hardcoded phrase list
(chest pain, can't breathe, loss of consciousness, stroke-like symptoms,
suicidal ideation, uncontrolled bleeding, anaphylaxis, etc.) **before**
anything else in the request — before symptom extraction, before any
database query, before any Gemini call. If it matches, the response is a
fixed, concise safety message telling the user to contact emergency
services; nothing else in the pipeline runs, and nothing downstream can
override that decision.

---

## 📊 Scaling the knowledge base

Going from the current dataset to 500 or 1000+ diseases requires **adding
data, not changing code** — `disease_matcher.py` and `symptom_engine.py` are
fully generic.

### Adding diseases without touching source code

```bash
cd backend
python scripts/seed_diseases.py --json path/to/more_diseases.json
```

JSON shape (see `DISEASE_JSON_SCHEMA` in `scripts/seed_diseases.py`):

```json
[
  {
    "name": "Dengue",
    "description": "...",
    "category": "Infectious disease",
    "risk_score": 65,
    "source": "https://www.who.int/news-room/fact-sheets/detail/dengue-and-severe-dengue",
    "symptoms": [
      {"name": "high_fever", "is_common": true, "weight": 2.5},
      {"name": "headache", "is_common": true, "weight": 2.0}
    ]
  }
]
```

The importer is **idempotent** — diseases are matched by unique name,
symptoms by unique name, links by a `(disease_id, symptom_id)` unique
constraint. Re-running the same file updates existing rows rather than
duplicating them, and malformed records (missing name, no symptoms) are
skipped with a printed warning rather than crashing the import.

### Re-running the original migration

```bash
python scripts/seed_diseases.py            # migrates Training.csv/doc_consult.csv
python scripts/seed_diseases.py --skip-csv --json more.json   # JSON only
```

### The 150-disease expansion

`scripts/import_disease_expansion.py` merges a second dataset — 150
additional diseases, 360 additional symptoms, 750 disease-symptom
mappings, sourced from `backend/data/expansion/*.xlsx` — into the same
tables:

```bash
python scripts/import_disease_expansion.py                 # uses backend/data/expansion/
python scripts/import_disease_expansion.py --xlsx-dir path/to/files
```

Also idempotent, and specifically careful about not blindly merging
similarly-named records — see the `DISEASE_MERGE_MAP` /
`SYMPTOM_MERGE_MAP` comments at the top of that script for the exact,
hand-reviewed list of genuine duplicates (case variants, one dataset typo,
true symptom synonyms) versus look-alikes that were kept as distinct,
separate records on purpose (e.g. "Gastritis" is not "Arthritis"; `eye_pain`
is not `knee_pain`). The `importance` column in the source data
(`high`/`medium`/`supporting`) is preserved verbatim in
`DiseaseSymptom.importance_label` — it is a category from the source
dataset, not a clinical probability, and is never presented as one.

---

## 🧪 Medical data quality

The bundled migration ports the project's original ~41-disease dataset
(`Training.csv`, `doc_consult.csv`, and its curated descriptions)
faithfully — nothing was invented to pad it out, and nothing was dropped:

- **Disease/symptom associations** come from per-disease symptom *frequency*
  across the dataset's training rows (not the old code's lossy
  `.groupby().max()` collapse), so a symptom present in only some of a
  disease's rows is distinguishable from one present in all of them.
- **Enrichment fields** (`causes`, `prevention`, `when_to_see_doctor`, etc.)
  are left `NULL` for the migrated data — there was no real source for them
  in the original project, and generating plausible-sounding text for them
  would be exactly the kind of fabrication this schema exists to avoid.
  They're there for data you actually have a source for.
- **Every migrated disease has a `source`** field crediting the original
  dataset/project, not a fabricated citation.
- **This app does not fabricate large disease datasets from scratch.** The
  150-disease expansion (below) is real curated data with citations, not
  generated filler, and it's explicitly marked as needing clinical review
  — see the next section.

### The 150-disease expansion's data quality

`backend/data/expansion/*.xlsx` adds 150 diseases / 360 symptoms / 750
mappings, citing MedlinePlus and Columbia's Disease-Symptom Knowledge
Database. Every record in this dataset carries its own
`verification_status`, and it is **"Needs source-backed enrichment/clinical
review before production"** for all of it — not a claim of clinical
validation. **Do not present the combined ~188-disease dataset as clinically
validated** — a large fraction of it explicitly isn't yet. Descriptions for
all 150 new diseases are blank on import for the same no-fabrication reason
as the original migration.

### Dirty-data findings

Found and fixed while building the migrations:

- `Training.csv`'s header lists `fluid_overload` **twice** — an upstream
  duplication. Both columns correctly collapse to one `Symptom` row (their
  disease links are unioned, nothing lost), so the true unique symptom count
  from the original dataset is **131**, not 132.
- The raw CSV has `"Hypertension "` (trailing space) as a prognosis value,
  and the original `DISEASE_INFO` dict separately had `"Diabetes "`
  (trailing space, not matching the CSV's clean `"Diabetes"` at all). Both
  would have silently ended up with a `NULL` description without
  normalization — fixed by stripping both sides before matching.
- Within-disease symptom frequencies in the original dataset are almost all
  95-100% — there's little genuine common-vs-rare variation to capture, so
  `is_common`/`weight` mostly saturate for that data. The schema is ready
  for richer data where that distinction matters more.
- The 150-disease expansion overlaps the original dataset on 2 diseases
  under a different casing (`"Hepatitis A"` vs `"hepatitis A"`, `"Common
  cold"` vs `"Common Cold"`) and 1 under a different spelling — the
  original dataset has `"Osteoarthristis"` (not a real medical term, a typo
  baked into the original data) where the expansion correctly has
  `"Osteoarthritis"`. All three were merged into the existing row (with the
  correct spelling added as an alias) rather than duplicated; see
  `DISEASE_MERGE_MAP` in `scripts/import_disease_expansion.py`. 6 symptom
  names were similarly merged as true synonyms (`diarrhea`/`diarrhoea`,
  `blisters`/`blister`, etc.) — and several superficially similar pairs
  were deliberately **not** merged because they're medically distinct
  (`eye_pain` vs `knee_pain`, `lower_abdominal_pain` vs generic
  `abdominal_pain`) — see `SYMPTOM_MERGE_MAP` in the same file for the full,
  reasoned list.

---

## ⚡ Performance

Ranking queries filter by `symptom_id IN (...)` against indexed columns
rather than iterating every disease, and the app no longer trains a model
from a CSV at every boot (the old `sklearn` decision tree did — that
dependency has been removed entirely). The symptom vocabulary used for
Gemini-constrained extraction is cached in-process after first load; if it
grows very large (several hundred+ symptoms) that vocabulary dump is worth
revisiting, but at the current dataset size it's a trivial ~1-2KB of prompt
text.

---

## 🚀 Running locally

### Backend

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # or .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt   # includes pytest; use requirements.txt for prod-only
cp .env.example .env            # then fill in GEMINI_API_KEY if you have one
python scripts/seed_diseases.py # populate the disease knowledge base
python app.py
```

Runs on `http://localhost:5000`. Without `GEMINI_API_KEY` set, the app still
works fully — symptom extraction and phrasing just fall back to the local,
zero-cost logic.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL, defaults to http://localhost:5000
npm run dev
```

Runs on `http://localhost:5173`.

### Running tests

```bash
cd backend
python -m pytest tests/ -v
```

Runs entirely offline against a temporary SQLite database — no real Gemini
API calls are made (a couple of tests monkeypatch `gemini_client` to
simulate a failing call and assert the fallback still works).

### Getting a free Gemini API key

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Create a key (free tier, rate-limited)
3. Put it in `backend/.env` as `GEMINI_API_KEY=...`

---

## 🔌 API endpoints

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/chat` | POST | optional | `{message, answers}` → `{message, next_step, answers, emergency}`. `answers` is `[[symptom_name, bool], ...]`. `next_step.type` is `question`, `result`, `emergency`, `waiting`, or `reset`. |
| `/api/symptoms` | GET | — | All known symptom display names |
| `/api/diseases` | GET | — | Paginated/searchable disease list (`?q=`, `?page=`, `?page_size=`) |
| `/api/diseases/<id>` | GET | — | Full disease detail including its symptom links |
| `/api/tips` | GET | — | Daily wellness tip |
| `/api/auth/signup` | POST | — | `{name, email, password}` → `{token, user}` |
| `/api/auth/login` | POST | — | `{email, password}` → `{token, user}` |
| `/api/auth/me` | GET | required | Current user |
| `/api/reminders` | GET/POST | required | List / create |
| `/api/reminders/<id>` | PUT/DELETE | required | Update / delete |

---

## 📦 Deploying

- **Backend**: any Python host works (`Procfile` runs
  `gunicorn --workers 2 --threads 4 --timeout 30 app:app` — threaded so a
  slow Gemini call can't block unrelated requests). Set `DATABASE_URL` to a
  real Postgres instance (e.g. a free tier on
  [Supabase](https://supabase.com) or [Neon](https://neon.tech)) — most free
  hosts (Render, Railway, Heroku) reset the local filesystem on every
  deploy, which would wipe a SQLite file and every account/reminder/disease
  row in it. Run `python scripts/seed_diseases.py` once against the
  production database after first deploy, then
  `python scripts/import_disease_expansion.py` for the 150-disease
  expansion. Also set `JWT_SECRET`, `GEMINI_API_KEY`, and `CORS_ORIGINS`
  (comma-separated list of your frontend's origin(s)).
- **Frontend**: static build (`npm run build`) deploys anywhere (Vercel,
  Netlify, etc.). Set `VITE_API_URL` to your deployed backend's URL.

---

## ⚠️ Limitations

- **188 diseases, not 1000+, and most of it needs clinical review.** The
  architecture scales; the data is a real but explicitly-unvalidated
  starter set for 147 of those 188 — see
  [Medical data quality](#-medical-data-quality). Do not present this as a
  clinically validated dataset.
- **Gemini grounding is prompt-enforced, not runtime-guaranteed.** The
  explanation prompt explicitly lists the only condition names Gemini may
  mention, but an LLM can still occasionally deviate from instructions —
  there's no automated post-hoc check that its prose never names anything
  outside that list.
- **No real database migrations tool.** `schema_sync.py` auto-adds missing
  *nullable* columns to an existing table (what made the disease-expansion
  schema change work against an already-deployed database without wiping
  it) but it can't alter or rename an existing column, backfill a NOT NULL
  addition, or drop anything. Introducing Alembic is a reasonable next step
  before the schema needs a change that isn't purely additive.
- **Symptom aliases are hand-curated, not exhaustive.** ~30 of the original
  131 symptoms have conversational aliases seeded; the 320 symptoms added
  by the expansion have none yet beyond their own display name. Extend
  `data/symptom_aliases_seed.py` (or add an `alias` value in future
  expansion data) and re-run the relevant seed script — no code changes
  needed.

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
