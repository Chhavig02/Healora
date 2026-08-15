<div align="center">

# Healora

**AI-assisted symptom support for clearer, safer health guidance.**

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](frontend/package.json)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)](frontend/package.json)
[![Flask](https://img.shields.io/badge/Flask-black?logo=flask&logoColor=white)](backend/requirements.txt)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](backend/requirements.txt)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-D71F00?logo=sqlalchemy&logoColor=white)](backend/models.py)
[![Gemini](https://img.shields.io/badge/Gemini-language%20layer-8E75B2?logo=googlegemini&logoColor=white)](backend/gemini_client.py)
[![JWT Auth](https://img.shields.io/badge/Auth-JWT-000000?logo=jsonwebtokens&logoColor=white)](backend/auth.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-4CAF50)](LICENSE)

[**Live Demo**](https://healora-six.vercel.app) · [**Backend API**](https://healora-l3nl.onrender.com) · [**Repository**](https://github.com/Chhavig02/Healora)

</div>

<br />

<div align="center">
  <img src="docs/images/home.png" alt="Healora landing page" width="90%" />
</div>

<br />

> ⚠️ **Healora is an educational symptom-support application and is not a medical diagnostic tool.** It never states a definitive diagnosis — every result is framed as a *possible condition to discuss with a doctor*. Always consult a licensed healthcare professional, especially for anything severe, persistent, or worsening.

---

## Table of contents

- [What is Healora?](#what-is-healora)
- [Product preview](#-product-preview)
- [Key features](#-key-features)
- [How it works](#-how-it-works)
- [Architecture](#-architecture)
- [The Gemini boundary](#-the-gemini-boundary)
- [Emergency safety layer](#-emergency-safety-layer)
- [Scaling the knowledge base](#-scaling-the-knowledge-base)
- [Medical data quality](#-medical-data-quality)
- [Getting started](#-getting-started)
- [Testing](#-testing)
- [API reference](#-api-reference)
- [Deployment](#-deployment)
- [Limitations](#-limitations)
- [License](#-license)

---

## What is Healora?

Healora is a full-stack health-tech application that helps people put words to what they're feeling and understand what it might mean — without pretending to be a doctor. It's built as a genuine multi-turn conversation, not a single-shot symptom form: it remembers what you've already said, asks only the follow-up questions that are still relevant, and understands interruptions ("what medicine should I take?") without losing the thread.

A user describes their symptoms **in plain, natural language** ("I have a fever and headache", or in Hinglish — "mujhe bukhar hai, khansi nahi hai"). Healora:

1. Normalizes that free text into known, canonical symptom names — a fast local matcher first (clause-aware, so it correctly separates "fever **but no** cough" into present/absent), with Gemini as an optional NLP layer for phrasing the local matcher can't resolve on its own.
2. Tracks a structured **conversation state** across turns — chief complaint, duration/severity/onset, confirmed and denied symptoms, volunteered context (age, sex, medications, allergies, existing conditions), and which conversational phase it's in — round-tripped through the client each request rather than stored server-side (see [Architecture](#-architecture)).
3. Matches the resulting symptom set against a **structured, relational disease/symptom knowledge base** (not a hardcoded list), ranking candidate conditions by weighted symptom overlap.
4. Asks a targeted follow-up question when the signal isn't strong enough yet, or presents a **differential assessment** — a short summary, positive/negative symptoms, ranked possible conditions each with *why* it's being considered, what's still uncertain, and a recommended next step — always framed as possibilities to discuss with a doctor, never a diagnosis.
5. Understands **intent, not just keywords** — a message mid-conversation can be a new symptom, an answer, a medication question, a general health question ("Why does fever happen?"), or a request to restart, and gets routed accordingly instead of forcing everything through the symptom pipeline.
6. Runs every message through an **independent emergency-safety check** first, before any database lookup or model call, so a phrase like "chest pain" or "can't breathe" is never held up waiting on an AI response — and this decision can never be seen or overridden by Gemini.
7. Wraps every explanation in **educational framing**, grounded only in facts the database actually contains — Gemini writes the prose, but never decides the medical facts, invents a condition name, or recommends a medication/dosage.

Everything above is real, running code — described in detail (with file references) further down this document.

---

## 🖥️ Product Preview

### Landing page

![Healora home page](docs/images/home.png)

### AI symptom assistant

Natural-language input, quick-start prompts, and a conversational follow-up flow.

![Healora chat widget](docs/images/chat.png)

### Possible conditions

Ranked results with match strength, matched symptoms, and other possibilities — always paired with an educational, non-diagnostic disclaimer.

![Healora possible conditions result](docs/images/results.png)

### Emergency safety layer

A hardcoded, Gemini-independent check intercepts emergency phrasing before anything else runs.

![Healora emergency safety alert](docs/images/emergency.png)

### Authentication

![Healora signup page](docs/images/auth.png)

### Dashboard & medication reminders

![Healora dashboard](docs/images/dashboard.png)

![Healora medication reminders](docs/images/reminders.png)

### Responsive / mobile

![Healora on mobile](docs/images/mobile.png)

*All screenshots above are real captures of the live deployment — no mockups or stock imagery.*

---

## ✨ Key Features

- 💬 **Natural-language symptom input** — describe how you feel in your own words, no medical jargon required, including common Hinglish phrasing ("sir dard ho raha hai", "khansi nahi hai").
- 🧵 **Multi-turn conversation memory** — a structured `conversation_state` (chief complaint, duration/severity/onset, confirmed/denied symptoms, volunteered age/sex/medications/allergies/existing conditions, conversation phase) survives across `/api/chat` requests without a server-side session — the client round-trips it each turn, the same pattern the original `answers` list already used.
- 🙅 **Clause-aware negation** (`negation.py`) — "I have fever but no cough" correctly records fever present, cough denied, instead of one negation flag applied to the whole message. Handles English lead-ins ("don't have", "no") and the Hinglish postpositive particle ("nahi"/"nahin").
- 🔀 **Intent-aware routing, not just keyword matching** (`intent_classifier.py`) — distinguishes a new symptom, an answer to a pending question, a medication question, a general health question, or a restart request — and a user can interrupt a pending question ("what medicine should I take?") without the conversation losing its place.
- 🎯 **Deterministic follow-up question engine** — history-taking (duration/severity/onset) runs once per complaint (`history_taking.py`), then `disease_matcher.py`'s information-gain question selection takes over, capped at a configurable question budget — never re-asking something already answered.
- 🧭 **Differential assessment, not a verdict** — results include a short symptom summary, positive *and* negative symptoms, each candidate condition's specific matched symptoms ("why it's being considered"), what's still uncertain, and a severity-derived recommended next step — always "possible conditions to discuss with a doctor," never "you have X."
- ❓ **General health questions answered on their own terms** — "What is migraine?", "Why does fever happen?", "What should I do for dehydration?" are recognized and answered (grounded in the disease database when a known condition is named, scoped general-education guardrails otherwise) instead of forcing everything through the symptom pipeline.
- 🧠 **Local symptom extraction** — a deterministic, three-pass matcher (`symptom_engine.py`) resolves free text to canonical symptom names using exact phrase, multi-word, and fuzzy-typo matching. Always available, zero external calls, zero cost.
- 🔤 **Symptom normalization & aliases** — conversational phrasings ("my joints hurt", "can't breathe properly", "bukhar") map to canonical symptom names via a curated `SymptomAlias` table.
- 🗄️ **Structured disease/symptom knowledge base** — `Disease`, `Symptom`, and `DiseaseSymptom` are database rows with weighted, many-to-many links, not a hardcoded Python dict.
- 📊 **Weighted disease matching & ranking** — `disease_matcher.py` scores every candidate disease by matched vs. contradicted symptom weight; nothing in this module is disease-specific.
- ✅ **Possible-condition results** — ranked, qualitative match strength ("possible" / "moderate" / "strong"), never a numeric confidence score.
- 🚨 **Independent emergency detection** — a fixed keyword check runs before any database query, conversation-state update, or Gemini call, and its decision is final — nothing downstream, including the intent classifier, can override or soften it.
- 💊 **Safe medication handling** — medication/dosage questions always get a fixed, never-Gemini-generated guardrail message, since the schema has no verified treatment data to ground a real answer in.
- 🤖 **Gemini NLP layer** — used for intent classification, negation-aware symptom extraction, natural follow-up question phrasing, grounded result explanations, and history summarization. Never the source of medical truth — see [The Gemini boundary](#-the-gemini-boundary).
- 🔁 **Graceful Gemini fallback** — every Gemini call degrades to a deterministic local fallback if no API key is configured, the call fails, times out, rate-limits, or returns a malformed/invalid response. The app is fully functional with zero AI calls.
- 🌱 **Automatic knowledge-base initialization** — on a fresh database, the app seeds itself from the bundled dataset on first boot; no manual migration step required to get a working instance.
- 🔐 **Authentication** — JWT-based email/password signup and login.
- 📋 **User dashboard** — quick actions, recent-activity surface, and reminders in one place.
- ⏰ **Medication reminders** — create, edit, pause, and delete reminders (medication, dosage, time, frequency, notes), scoped to your account.
- 🧾 **Personalized context** — a logged-in user's recent chat history is fed back into result explanations.
- 💡 **Daily wellness tip** — AI-generated when Gemini is configured, otherwise a curated static list.
- 📱 **Responsive frontend** — a React 19 + Vite single-page app that works from mobile to desktop.

---

## 🔍 How It Works

```mermaid
flowchart TD
    A[User describes symptoms] --> B{Emergency safety check}
    B -->|Emergency phrase detected| C[Fixed emergency guidance<br/>final — nothing downstream can override it]
    B -->|Normal| D[Local symptom extraction<br/>symptom_engine.py]
    B -->|Normal| E[Gemini NLP extraction<br/>constrained to known vocabulary]
    D --> F[Canonical symptom set<br/>unresolved terms discarded, valid ones kept]
    E --> F
    F --> G[disease_matcher.py<br/>weighted symptom-overlap ranking]
    G --> H{Confident enough?}
    H -->|Not yet| I[Targeted follow-up question]
    I --> A
    H -->|Yes| J[Ranked possible conditions]
    J --> K[Gemini-phrased explanation<br/>grounded only in DB facts]
```

A few things worth calling out about this flow:

- **Emergency detection always wins.** It runs first, needs no database or network call, and its result can't be seen or overridden by anything downstream — including Gemini.
- **Extraction is two independent sources merged, not a pipeline.** Local keyword matching and Gemini's extraction both run against the *same* canonical vocabulary and their results are unioned — so if Gemini is down, rate-limited, or simply not configured, local matching alone still works.
- **An unresolved symptom never poisons a valid one.** If a user says "I have cold and fever" and "cold" doesn't resolve to any canonical symptom, `fever` still reaches the matcher on its own — the invalid term is dropped, not the whole extraction.
- **The matcher decides the medical result; Gemini decides the words.** Which condition is presented is fully determined by `disease_matcher.py` reading the database — Gemini is only called afterward, to phrase an explanation grounded in the facts that decision already produced.

---

## 🏗️ Architecture

```
backend/
├── app.py                    Flask app factory — blueprint registration + first-boot DB seeding
├── config.py                 Env-var-driven configuration
├── models.py                 User/Reminder/ChatMessage + Disease/Symptom/DiseaseSymptom
├── auth.py, reminders.py,
│   chat.py, diseases.py      Flask blueprints
├── conversation_state.py     Structured, stateless multi-turn conversation state
├── intent_classifier.py      Intent routing (new symptom / answer / medication / general question / restart / ...)
├── negation.py                Clause-aware negation splitting (English + Hinglish)
├── profile_extraction.py     Age/sex/medications/allergies/existing-conditions extraction
├── history_taking.py         Generic duration/severity/onset follow-up questions
├── disease_matcher.py        Generic, DB-driven ranking + adaptive follow-up questions
├── symptom_engine.py         Free-text → canonical symptom name matching
├── emergency.py              Independent, keyword-based emergency detection
├── gemini_client.py          Gemini wrapper + the "Gemini boundary" contract
├── health_tips.py            Daily wellness tip (AI or curated fallback)
├── schema_sync.py            Additive auto-migration (adds missing nullable columns)
├── data/                     Legacy dataset descriptions + curated symptom/ambiguous-term aliases
├── scripts/
│   ├── seed_diseases.py      Idempotent CSV/JSON → database importer
│   └── import_disease_expansion.py   Optional 150-disease dataset merge
└── tests/                    130-test pytest suite

frontend/
└── src/
    ├── pages/                Home, Login, Signup, Dashboard
    ├── components/
    │   ├── ChatWidget.jsx    The symptom-check conversational UI
    │   └── ui/               ConditionCard, MessageBubble, Alert, Badge, ...
    ├── context/               Auth context (JWT persisted client-side)
    └── lib/api.js             Thin fetch wrapper around the backend API
```

<details>
<summary><strong>The disease knowledge base — schema details</strong></summary>

<br />

Replaces an original hardcoded ~41-disease dict and a `sklearn.DecisionTreeClassifier` retrained from a CSV on every server boot.

- **`Disease`** — name, description, category, `risk_score` (0–100, drives a computed `severity_label`), plus optional enrichment fields (`causes`, `risk_factors`, `prevention`, `when_to_see_doctor`, `emergency_warning_signs`, `management`, `age_sex_notes`) and a `source` attribution. Enrichment fields are `NULL` unless there's real data behind them — never auto-filled with generated text (see [Medical data quality](#-medical-data-quality)).
- **`Symptom`** — canonical underscored name (the same identifier used in the `answers` API contract), display name, optional category.
- **`DiseaseSymptom`** — the many-to-many link, with `is_common` and a continuous `weight` so a defining symptom counts for more than an occasional one. Unique-constrained on `(disease_id, symptom_id)`.
- **`SymptomAlias` / `DiseaseAlias`** — conversational phrasings mapped to a canonical name (`"my joints hurt"` → `joint_pain`), and disease name variants, respectively.

All four tables are indexed on their name columns and the foreign keys used for lookups, so ranking queries stay targeted instead of scanning every disease.

### `disease_matcher.py` — generic ranking, no per-disease logic

`rank_diseases(yes_symptoms, no_symptoms)` scores every disease sharing at least one confirmed symptom: `(matched_weight × 10) − (contradicted_weight × 6) − (total_weight × 0.15)`, ranked descending. `get_next_step(answers)` decides whether to ask another question or present a result — a result requires the top candidate to clear a score threshold *and* have at least 2 corroborating symptoms (not just one high-weight match), or the user has volunteered 4+ symptoms, or a question budget is exhausted. Nothing in this file references a disease by name — add a disease to the database and it participates automatically.

### `symptom_engine.py` — free text → canonical symptom names

Three passes, in order, all backed by the `Symptom`/`SymptomAlias` tables (no hardcoded vocabulary):

1. **Exact phrase match** — canonical name, display name, or a known alias appears verbatim (word-bounded) in the message.
2. **All-significant-words match** — every non-stopword of a multi-word symptom/alias appears somewhere in the message, in any order.
3. **Fuzzy single-token match** (`difflib`, cutoff 0.84) — catches typos like "haedache", only attempted if the first two passes found nothing.

</details>

<details>
<summary><strong>The conversation layer — state, phases, negation, intent routing</strong></summary>

<br />

The chat pipeline is stateless server-side, same as the rest of this backend — `conversation_state.py` defines a plain dict (`chief_complaint`, `duration`/`severity`/`onset`, `age`/`sex`, volunteered `medications`/`allergies`/`existing_conditions`, `current_primary_condition`, `conversation_stage`, `questions_asked`, `conversation_summary`, ...) that the client sends back on every request alongside `answers`, rather than a server-side session store. `answers` (`[[symptom_name, bool], ...]`) stays the single source of truth for confirmed/denied symptoms — the state dict never duplicates it.

**Conversation phases** (`conversation_stage`): `GREETING → CHIEF_COMPLAINT → HISTORY_TAKING → SYMPTOM_CLARIFICATION → FOLLOW_UP`, with `EMERGENCY`, `GENERAL_QUESTION`, and `COMPLETED` as phases a conversation can enter at any point when the user interrupts the normal flow.

**Intent routing** (`intent_classifier.py`) decides what a message *is* before deciding what to do with it — `NEW_SYMPTOM`, `SYMPTOM_ANSWER`, `HISTORY_ANSWER`, `MEDICATION_QUESTION`, `QUESTION_ABOUT_CONDITION`, `CAUSE_QUESTION`, `RESTART`, and more. Gemini-assisted when configured, but always backed by a deterministic keyword/regex fallback — every test in this codebase runs against that fallback, since it's the floor the app has to guarantee with no API key. A pending question (a history slot or a yes/no symptom question) doesn't blindly consume the next message as its answer: a genuinely new symptom, an unrelated question, or "restart" are all recognized as interruptions first, and the interrupted response gently reminds the user what was being asked so the thread isn't lost.

**Negation** (`negation.py`) splits a message into clauses (on "but"/"however"/punctuation) and classifies each clause independently, so "I have fever but no cough" records fever present *and* cough denied — not one negation flag applied to everything. Recognizes English lead-ins ("don't have", "never had") and the Hinglish postpositive particle ("khansi **nahi** hai"). Gemini's own extraction is asked for the same present/absent structure, but only ever fills in a symptom the deterministic splitter missed entirely — it can't override a local determination.

**Profile context** (`profile_extraction.py`) recognizes clearly-stated volunteered details — age ("I'm 34"), sex, medications ("I'm taking metformin"), allergies, and a curated list of chronic conditions — and remembers them for the rest of the conversation. Purely additive (never overwrites a value already given) and, like the rest of conversation state, never written to the database.

</details>

---

## 🤖 The Gemini Boundary

Gemini is the language layer only — it is never Healora's source of medical truth. This is enforced structurally, not just by prompt wording:

| Rule | How it's enforced |
|---|---|
| Gemini never creates/edits a `Disease` or `Symptom` row | Only `scripts/seed_diseases.py` writes to those tables; no code path lets a Gemini response reach `db.session.add()` |
| Symptom names Gemini extracts are validated | `chat.py`'s `_gemini_extract_structured` filters every returned item against the real `Symptom` table; unresolved items are discarded and logged, never inserted |
| An unresolved symptom can't discard a valid one | Extraction is a per-item filter, not an all-or-nothing check — one bad term never drops the good ones alongside it |
| Gemini can't invent negation either | Its present/absent extraction only ever fills in a symptom the deterministic clause splitter (`negation.py`) didn't already find — it never overrides a local determination |
| Disease ranking is Gemini-free | `disease_matcher.py` only reads the database; which disease is presented is decided *before* Gemini is ever called |
| Explanations are grounded, not generated from scratch | The result-explanation prompt includes the specific `Disease` row's fields and explicitly lists the only condition names Gemini is allowed to mention |
| Intent classification can't touch emergency | `intent_classifier.py` never runs until *after* `emergency.py` has already returned — there's no code path where a classified intent can suppress or soften an emergency response |
| General health questions are scoped, not open-ended | Questions unrelated to any tracked complaint or named disease (e.g. "why does fever happen?") get a distinct, narrower system instruction permitting only well-established general education — never a medication name/dosage or a diagnosis |
| Emergency detection is fully independent | `emergency.py` has no Gemini dependency and runs before any database lookup, conversation-state update, or model call; its decision is final |
| JSON responses are shape-validated | `gemini_client.generate_json` accepts a `validator` callable; a shape mismatch is treated exactly like an API failure |
| Every Gemini call has a bounded fallback | No API key, a failed call, a timeout, a rate limit, or a malformed response all resolve to the same deterministic local fallback — never an error shown to the user |

This is enforced by code structure and prompt constraints, not a guarantee against every possible model deviation — see [Limitations](#-limitations).

---

## 🚨 Emergency Safety Layer

`emergency.py` checks the raw message against a hardcoded phrase list (chest pain, can't breathe, loss of consciousness, stroke-like symptoms, suicidal ideation, uncontrolled bleeding, anaphylaxis, and more) **before** anything else in the request — before symptom extraction, before any database query, before any Gemini call. If it matches, the response is a fixed, concise safety message directing the user to emergency services; nothing else in the pipeline runs, and nothing downstream can override that decision.

---

## 📊 Scaling the Knowledge Base

<details>
<summary><strong>Adding diseases without touching source code</strong></summary>

<br />

Going from the current dataset to hundreds more diseases requires **adding data, not changing code** — `disease_matcher.py` and `symptom_engine.py` are fully generic.

```bash
cd backend
python scripts/seed_diseases.py --json path/to/more_diseases.json
```

```json
[
  {
    "name": "Dengue",
    "description": "...",
    "category": "Infectious disease",
    "risk_score": 65,
    "source": "https://www.who.int/news-room/fact-sheets/detail/dengue-and-severe-dengue",
    "symptoms": [
      { "name": "high_fever", "is_common": true, "weight": 2.5 },
      { "name": "headache", "is_common": true, "weight": 2.0 }
    ]
  }
]
```

The importer is **idempotent** — diseases and symptoms are matched by unique name, links by a `(disease_id, symptom_id)` unique constraint. Re-running the same file updates existing rows rather than duplicating them.

### The optional 150-disease expansion

`scripts/import_disease_expansion.py` can merge a second, larger dataset — 150 additional diseases, 360 additional symptoms, 750 disease-symptom mappings, sourced from `backend/data/expansion/*.xlsx` — into the same tables:

```bash
python scripts/import_disease_expansion.py
```

Also idempotent, and specifically careful about not blindly merging similarly-named records — see `DISEASE_MERGE_MAP` / `SYMPTOM_MERGE_MAP` in that script for the hand-reviewed list of genuine duplicates versus medically-distinct look-alikes kept separate on purpose (e.g. `eye_pain` is not `knee_pain`).

This expansion is **not** run automatically — the live demo above runs on the base ~41-disease / 131-symptom dataset, seeded automatically on first boot (see [Deployment](#-deployment)).

</details>

---

## 🧪 Medical Data Quality

<details>
<summary><strong>Data provenance, quality notes, and known dirty-data findings</strong></summary>

<br />

The bundled migration ports the project's original dataset faithfully — nothing was invented to pad it out, and nothing was dropped:

- **Disease/symptom associations** come from per-disease symptom *frequency* across the dataset's training rows, so a symptom present in only some of a disease's rows is distinguishable from one present in all of them.
- **Enrichment fields** (`causes`, `prevention`, `when_to_see_doctor`, etc.) are left `NULL` for the migrated data — there was no real source for them in the original project, and generating plausible-sounding text would be exactly the kind of fabrication this schema exists to avoid.
- **Every migrated disease has a `source`** field crediting the original dataset, not a fabricated citation.
- **This app does not fabricate large disease datasets from scratch.** The optional 150-disease expansion is real curated data with citations (MedlinePlus, Columbia's Disease-Symptom Knowledge Database) — not generated filler — and every record in it carries its own `verification_status` of *"Needs source-backed enrichment/clinical review before production."*

**Do not present this dataset as clinically validated.** The architecture scales to hundreds of diseases; the data is a real but explicitly-unvalidated starter set for a meaningful fraction of it.

### Dirty-data findings (found and fixed during migration)

- The source CSV's header lists one symptom column **twice** — an upstream duplication, correctly collapsed to a single `Symptom` row with its disease links unioned, so the true unique symptom count is 131, not 132.
- The raw CSV and the original curated-description dict had inconsistent trailing whitespace on disease names (`"Hypertension "`, `"Diabetes "`) that would have silently produced a `NULL` description without normalization — fixed by stripping both sides before matching.
- The optional expansion dataset overlaps the base dataset on a few diseases under different casing or a dataset typo (`"Osteoarthristis"` vs. the correct `"Osteoarthritis"`) — all merged into the existing row (with the correct spelling preserved as an alias) rather than duplicated.

</details>

---

## ⚡ Performance

Ranking queries filter by `symptom_id IN (...)` against indexed columns rather than iterating every disease, and the app does not train a model from a CSV at every boot. The symptom vocabulary used for Gemini-constrained extraction is cached in-process after first load.

---

## 🚀 Getting Started

### Backend

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # or .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt   # includes pytest; use requirements.txt for prod-only
cp .env.example .env            # then fill in GEMINI_API_KEY if you have one
python app.py
```

Runs on `http://localhost:5000`. **No manual seed step needed** — on a fresh, empty database, `create_app()` automatically seeds the knowledge base from the bundled dataset on first boot. Without `GEMINI_API_KEY` set, the app still works fully — symptom extraction and phrasing just fall back to the local, zero-cost logic.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL, defaults to http://localhost:5000
npm run dev
```

Runs on `http://localhost:5173`.

### Getting a free Gemini API key

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Create a key (free tier, rate-limited)
3. Put it in `backend/.env` as `GEMINI_API_KEY=...`

---

## 🧪 Testing

```bash
cd backend
python -m pytest tests/ -v
```

**130 tests**, covering symptom matching/aliasing, disease ranking, the full `/api/chat` conversation pipeline (multi-turn memory, negation — English and Hinglish, intent switching/interruption, general health questions, restart, differential-assessment structure), emergency detection, authentication, reminders, the disease-expansion importer, and first-boot auto-seeding. Runs entirely offline against a temporary SQLite database — no real Gemini API calls are made; a dedicated set of tests monkeypatches `gemini_client` to simulate no API key, a timeout, a rate limit, and a malformed/invalid response, asserting the deterministic fallback holds in every case.

---

## 🔌 API Reference

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/api/chat` | POST | optional | `{message, answers, state}` → `{message, next_step, answers, state, emergency}`. `answers` is `[[symptom_name, bool], ...]`; `state` is the conversation-state dict (see [Architecture](#-architecture)) — round-trip whatever the previous response returned. `next_step.type` is `question`, `result`, `emergency`, `waiting`, or `reset`. A `result` step includes the full differential-assessment payload: `symptom_summary`, `symptoms_present`/`symptoms_denied`, `possible_conditions` (each with `matched_symptoms`), `uncertain_symptoms`, and `next_step_recommendation`, all additive to the original contract. |
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

## 📦 Deployment

- **Backend**: any Python host works (`Procfile` runs `gunicorn --workers 2 --threads 4 --timeout 30 app:app` — threaded so a slow Gemini call can't block unrelated requests). Set `DATABASE_URL` to a real Postgres instance — most free hosts reset the local filesystem on every deploy, which would wipe a SQLite file. `config.py` normalizes Render/Heroku-style `postgres://` URLs to the `postgresql://` scheme SQLAlchemy 1.4+/psycopg2 expect, so pointing `DATABASE_URL` at a Render Postgres instance works without further changes. The app **auto-seeds the base knowledge base on first boot** against an empty database; run `python scripts/import_disease_expansion.py` afterward if you also want the optional 150-disease expansion. Also set `JWT_SECRET`, `GEMINI_API_KEY`, and `CORS_ORIGINS` (comma-separated list of your frontend's origin(s)).
  - The conversation layer (chief complaint, history, negation, profile context, ...) adds **no new tables or columns** — it's stateless and client-round-tripped exactly like the pre-existing `answers` list, so it has no bearing on the database schema or a Postgres migration.
- **Frontend**: static build (`npm run build`) deploys anywhere (Vercel, Netlify, etc.). Set `VITE_API_URL` to your deployed backend's URL. This project's frontend is deployed on Vercel; the backend on Render, backed by Render's managed Postgres.

---

## ⚠️ Limitations

- **A real but explicitly-unvalidated dataset.** The architecture scales to hundreds of diseases; a meaningful fraction of the optional expansion data needs clinical review before it should be treated as validated — see [Medical data quality](#-medical-data-quality).
- **Gemini grounding is prompt-enforced, not runtime-guaranteed.** The explanation prompt explicitly lists the only condition names Gemini may mention, but an LLM can still occasionally deviate from instructions — there's no automated post-hoc check that its prose never names anything outside that list.
- **No real database migrations tool.** `schema_sync.py` auto-adds missing *nullable* columns to an existing table, but it can't alter or rename an existing column, backfill a `NOT NULL` addition, or drop anything. Introducing Alembic is a reasonable next step before the schema needs a non-additive change.
- **Symptom aliases are hand-curated, not exhaustive.** A subset of the base symptom set has conversational aliases seeded (including a small set of common Hinglish phrasings); symptoms added by the optional expansion have none yet beyond their own display name.
- **Negation splitting handles the documented cases, not full sentence parsing.** Clauses split on "but"/"however"/"although"/"though" and punctuation — a construction like "fever and no cough" (no "but") isn't split into separate clauses today, so a negation joined with a bare "and" can be missed. Hindi duration phrasing ("3 din se") is kept as raw text rather than parsed into a structured value, same as any duration answer that doesn't cleanly reduce to a number.
- **Profile-context extraction (age/sex/medications/allergies/conditions) is curated regex, not open-ended NLP** — deliberately, in the same spirit as the symptom-alias table, but it will miss phrasings outside the patterns it recognizes rather than guessing.
- **Client-side routing on static hosts needs a rewrite rule.** As a React Router SPA, deep links (e.g. `/signup` loaded directly, not navigated to from within the app) require the host to rewrite unmatched paths to `index.html` — otherwise a direct load 404s while in-app navigation still works fine.

---

## 📄 License

This project is open-source under the [MIT License](LICENSE).
