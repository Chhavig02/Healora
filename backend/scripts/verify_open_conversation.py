"""Manual verification of the open-ended conversation architecture — the
exact multi-turn flow from the task spec, against the real, running
/api/chat endpoint."""

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
    extra = f"[{step.get('type')}"
    if step.get("type") == "result":
        extra += f": {step.get('disease')}"
    extra += f", chief_complaint={r['state'].get('chief_complaint')}, current_primary_condition={r['state'].get('current_primary_condition')}]"
    print(f"      {extra}")
    print()


answers, state = [], None

for msg in ["I've been feeling weird lately.", "I feel tired and weak.", "I also have fever and headache."]:
    r = post(msg, answers, state)
    answers, state = r["answers"], r["state"]
    show(msg, r)

for value in ("3 days", "7", "gradually"):
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

assert r["next_step"]["type"] == "result", "never reached a result"

for msg in ["What does that result mean?", "I'm worried.", "What should I tell my doctor?", "Actually, why does fever make you feel weak?"]:
    r = post(msg, answers, state)
    answers, state = r["answers"], r["state"]
    show(msg, r)
    assert r["next_step"]["type"] != "result", f"'{msg}' unexpectedly re-triggered the disease engine"

print("ALL CHECKS PASSED — conversation never became trapped inside the disease engine.")
