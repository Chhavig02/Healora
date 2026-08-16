"""Manual verification of the "every message treated as a symptom" fix —
runs the exact two conversations from the bug report against the real,
running /api/chat endpoint."""

import json
import urllib.request

URL = "http://localhost:5000/api/chat"


def post(message, answers, state):
    body = json.dumps({"message": message, "answers": answers, "state": state}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def show(user_msg, r):
    print(f"USER: {user_msg}")
    print(f"BOT:  {r.get('message')}")
    step = r.get("next_step", {})
    if step.get("type") == "result":
        print(f"      [RESULT CARD: {step.get('disease')}]")
    print(f"      (next_step={step.get('type')}, emergency={r.get('emergency')}, answers={r.get('answers')})")
    print()


print("=" * 70)
print("CONVERSATION 1: casual + pregnancy, no symptom pipeline expected")
print("=" * 70)
answers, state = [], None
for msg in ["I love you", "pregnent", "I think I'm pregnant", "I have abdominal pain", "what should I do?"]:
    r = post(msg, answers, state)
    answers, state = r["answers"], r["state"]
    show(msg, r)

print("=" * 70)
print("CONVERSATION 2: normal assessment, post-assessment question")
print("=" * 70)
answers, state = [], None
r = post("I have fever and headache", answers, state)
answers, state = r["answers"], r["state"]
show("I have fever and headache", r)

for value in ("3 days", "6", "gradually"):
    if state.get("pending_history_slot"):
        r = post(value, answers, state)
        answers, state = r["answers"], r["state"]
        show(value, r)

guard = 0
while r["next_step"]["type"] == "question" and guard < 8:
    r = post("yes", answers, state)
    answers, state = r["answers"], r["state"]
    show("yes", r)
    guard += 1

assert r["next_step"]["type"] == "result"

r = post("what medicines should I take?", answers, state)
answers, state = r["answers"], r["state"]
show("what medicines should I take?", r)
assert r["next_step"]["type"] != "result"
assert "couldn't" not in (r["message"] or "").lower()

print("ALL CHECKS PASSED.")
