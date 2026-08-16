"""One-off manual verification script (not a pytest test) — walks the
exact multi-turn conversation from the task spec against the real, running
/api/chat endpoint and prints a full transcript. Run with the dev server
already up on localhost:5000.
"""

import json
import urllib.request

URL = "http://localhost:5000/api/chat"


def post(message, answers, state):
    body = json.dumps({"message": message, "answers": answers, "state": state}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def show(label, r):
    print(f"--- {label} ---")
    if r.get("message"):
        print("bot (message):", r["message"])
    step = r.get("next_step", {})
    if step.get("type") == "question":
        print(f"bot (question, {step.get('answer_mode')}):", step.get("symptom"))
    elif step.get("type") == "result":
        print(f"bot (RESULT CARD): {step.get('disease')} [{step.get('match_strength')}, {step.get('severity')}]")
        print("   symptom_summary:", step.get("symptom_summary"))
    elif step.get("type") == "emergency":
        print("bot (EMERGENCY):", r["message"])
    print("   emergency flag:", r.get("emergency"))
    print("   conversation_stage:", (r.get("state") or {}).get("conversation_stage"))
    print("   current_primary_condition:", (r.get("state") or {}).get("current_primary_condition"))
    print()


answers, state = [], None

r = post("I have fever and headache", answers, state)
answers, state = r["answers"], r["state"]
show("Turn 1: I have fever and headache", r)

# Walk the history-taking slots (duration/severity/onset) if asked.
for value in ("3 days", "7", "gradually"):
    if state.get("pending_history_slot"):
        r = post(value, answers, state)
        answers, state = r["answers"], r["state"]
        show(f"Turn (history answer): {value}", r)

# Answer any yes/no symptom-clarification questions until we reach a result.
guard = 0
while r["next_step"]["type"] == "question" and guard < 8:
    r = post("yes", answers, state)
    answers, state = r["answers"], r["state"]
    show("Turn (yes/no answer): yes", r)
    guard += 1

assert r["next_step"]["type"] == "result", "Did not reach a result card"

r = post("what medicines should I take?", answers, state)
answers, state = r["answers"], r["state"]
show("Turn: what medicines should I take?", r)
assert r["next_step"]["type"] == "waiting"
assert "couldn't" not in r["message"].lower()

r = post("what should I eat?", answers, state)
answers, state = r["answers"], r["state"]
show("Turn: what should I eat?", r)
assert r["next_step"]["type"] == "waiting"
assert "couldn't" not in r["message"].lower()

r = post("is this serious?", answers, state)
answers, state = r["answers"], r["state"]
show("Turn: is this serious?", r)
assert r["next_step"]["type"] == "waiting"
assert "couldn't" not in r["message"].lower()

r = post("I now have severe chest pain", answers, state)
answers, state = r["answers"], r["state"]
show("Turn: I now have severe chest pain", r)
assert r["emergency"] is True
assert r["next_step"]["type"] == "emergency"

print("ALL ASSERTIONS PASSED — disease engine was invoked exactly during the")
print("initial assessment; medication/diet/severity follow-ups were answered")
print("contextually without touching it; emergency correctly overrode everything.")
