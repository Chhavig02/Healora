"""Curated conversational aliases for the most commonly-mentioned symptoms.

Maps a canonical symptom name (matching Training.csv's column names, which
are also the identifiers used in the `answers` API contract) to phrases a
real user might type instead of the clinical term. This is what lets
"my joints hurt" resolve to `joint_pain` without an LLM call.

Not exhaustive — extend this dict and re-run
`python scripts/seed_diseases.py` to add more; no application code changes
are needed to add coverage.

Note: the bundled dataset has no generic "fever" symptom, only
`high_fever` / `mild_fever`. Fever-ish phrasing is mapped to `high_fever`
as the closer clinical match; this is a matching heuristic, not a claim
that mild and high fever are the same thing.
"""

SYMPTOM_ALIASES_SEED = {
    "high_fever": [
        "fever",
        "feeling very hot",
        "feeling hot",
        "high temperature",
        "burning up",
        "running a temperature",
        "bukhar",
        "bukhar hai",
        "tez bukhar",
    ],
    "mild_fever": [
        "slight fever",
        "low grade fever",
        "feeling a bit warm",
    ],
    "headache": [
        "head is hurting",
        "head hurts",
        "my head hurts",
        "pain in head",
        "head pain",
        "sir dard",
        "sir mein dard",
        "sar dard",
    ],
    "joint_pain": [
        "joints hurt",
        "my joints hurt",
        "aching joints",
        "sore joints",
        "pain in joints",
    ],
    "breathlessness": [
        "can't breathe",
        "cant breathe",
        "cannot breathe properly",
        "can't breathe properly",
        "difficulty breathing",
        "shortness of breath",
        "trouble breathing",
        "hard to breathe",
        "saans lene me dikkat",
        "saans lene mein dikkat",
        "saans phoolna",
    ],
    "stomach_pain": [
        "stomach",
        "stomach hurts",
        "my stomach hurts",
        "pain in stomach",
        "tummy ache",
        "tummy hurts",
    ],
    "abdominal_pain": [
        "belly hurts",
        "abdomen hurts",
        "pain in belly",
        "pain in abdomen",
    ],
    "chest_pain": [
        "chest hurts",
        "pain in chest",
        "my chest hurts",
    ],
    "back_pain": [
        "back hurts",
        "my back hurts",
        "pain in back",
        "backache",
    ],
    "neck_pain": [
        "neck hurts",
        "sore neck",
        "pain in neck",
    ],
    "muscle_pain": [
        "muscles hurt",
        "sore muscles",
        "aching muscles",
        "body pain",
        "body ache",
        "body aches",
    ],
    "vomiting": [
        "throwing up",
        "throwing up a lot",
        "puking",
    ],
    "nausea": [
        "feel sick",
        "feeling nauseous",
        "queasy",
        "want to vomit",
        "feel like vomiting",
    ],
    "diarrhoea": [
        "diarrhea",
        "loose motions",
        "loose stools",
        "watery stools",
    ],
    "cough": [
        "coughing",
        "coughing a lot",
        "khansi",
        "khaansi",
    ],
    "fatigue": [
        "tired",
        "tierd",
        "tird",
        "exhausted",
        "no energy",
        "very tired",
        "feeling weak",
    ],
    "dizziness": [
        "feeling dizzy",
        "lightheaded",
        "light headed",
        "feel dizzy",
    ],
    "itching": [
        "itchy",
        "itchy skin",
        "skin itches",
    ],
    "skin_rash": [
        "rash",
        "red rash",
        "skin rash all over",
    ],
    "runny_nose": [
        "nose is running",
        "runny nose",
        "nose running",
    ],
    "congestion": [
        "stuffy nose",
        "blocked nose",
        "nasal congestion",
    ],
    "loss_of_appetite": [
        "not hungry",
        "don't want to eat",
        "no appetite",
    ],
    "constipation": [
        "can't poop",
        "unable to pass stool",
        "constipated",
    ],
    "sweating": [
        "sweating a lot",
        "excessive sweating",
    ],
    "chills": [
        "feeling cold",
        "shivering cold",
        "cold chills",
    ],
    "weakness_in_limbs": [
        "weak arms and legs",
        "limbs feel weak",
        "weak limbs",
    ],
    "swelling_joints": [
        "swollen joints",
        "joints are swollen",
    ],
    "knee_pain": [
        "knee hurts",
        "pain in knee",
        "sore knee",
    ],
    "hip_joint_pain": [
        "hip hurts",
        "pain in hip",
    ],
    "palpitations": [
        "heart racing",
        "heart pounding",
        "racing heartbeat",
    ],
    "throat_irritation": [
        "sore throat",
        "throat hurts",
        "scratchy throat",
    ],
}
