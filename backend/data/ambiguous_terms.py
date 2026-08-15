"""Curated clarification prompts for common words that are too ambiguous to
resolve to a single canonical symptom on their own.

This is deliberately small and hand-curated, the same spirit as
symptom_aliases_seed.py — not an attempt at general NLP disambiguation.
Only used when normal symptom extraction (local + Gemini, both constrained
to the real Symptom vocabulary) finds nothing at all; if the message also
contains a resolvable symptom, that takes priority and this is never
consulted. Extend this dict rather than adding one-off logic in chat.py.
"""

AMBIGUOUS_TERM_CLARIFICATIONS = {
    "cold": "Do you mean that you have a cold (runny nose and congestion), or that you're feeling unusually cold or having chills?",
    "weak": "When you say weak, do you mean overall tiredness, muscle weakness, dizziness, or feeling faint?",
    "sick": "Could you tell me a bit more about what you're feeling — nausea, general unwellness, or something else?",
    "unwell": "Could you describe that a bit more — is it nausea, fatigue, or something else?",
    "pain": "Where are you feeling the pain, and how would you describe it?",
    "hurting": "Where does it hurt, and how would you describe the pain?",
    "tired": "Do you mean physically fatigued, sleepy, or feeling weak/faint?",
    "dizzy": "Do you mean lightheaded and about to faint, or a spinning sensation?",
    "sore": "What's feeling sore, and is it more of an ache or a sharp pain?",
    "bad": "Could you tell me more specifically what's bothering you?",
    "off": "Could you describe that a bit more — what specifically feels off?",
    "funny": "Could you describe that feeling a bit more specifically?",
    "gross": "Could you describe what you're feeling a bit more specifically?",
}


def find_clarification(lower_text):
    tokens = set(lower_text.split())
    for term, clarification in AMBIGUOUS_TERM_CLARIFICATIONS.items():
        if term in tokens:
            return clarification
    return None
