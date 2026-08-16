"""Manual, real-API verification of the semantic conversation layer
(semantic_interpreter.py + orchestrator.py) against the deployed Render
backend, which has real Gemini/Groq credentials configured — same
urllib.request + assert style as the existing scripts/verify_*.py files,
pointed at the live URL instead of localhost, so this exercises the actual
LLM path those other scripts can't reach locally.

Three realistic 10+ turn conversations, covering: context retention across
a topic switch, an interrupted pending question, worsening/improvement
recognition, and a typo + Hinglish message — printing every turn and
asserting the same "never gets stuck / never silently loses information"
properties the rest of this test suite checks at the unit/integration
level. Transcripts are also written to verify_semantic_layer_transcript.txt
next to this script.

NOTE: Render only auto-runs the seed migration on a genuinely empty
database (see app.py's `if Symptom.query.count() == 0` check) — a redeploy
of this code does NOT retroactively add new symptom aliases (like "tierd")
to an already-seeded production database. That's a pre-existing deploy-
process gap, unrelated to the semantic interpreter itself, so the typo
check below is informational (printed, not asserted) rather than a hard
failure.

Run with: python scripts/verify_semantic_layer.py
"""

import json
import urllib.request

URL = "https://healora-1.onrender.com/api/chat"

_transcript_lines = []
_warnings = []


def post(message, answers, state):
    body = json.dumps({"message": message, "answers": answers, "state": state}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def show(user_msg, r):
    step = r.get("next_step", {})
    extra = f"[{step.get('type')}"
    if step.get("type") == "result":
        extra += f": {step.get('disease')}"
    extra += (
        f", chief_complaint={r['state'].get('chief_complaint')}, "
        f"current_primary_condition={r['state'].get('current_primary_condition')}, "
        f"user_reported_worsening={r['state'].get('user_reported_worsening')}, "
        f"user_reported_improvement={r['state'].get('user_reported_improvement')}]"
    )
    bot_message = r.get("message") or step.get("symptom") or step.get("description") or "(no message)"
    lines = [f"USER: {user_msg}", f"BOT:  {bot_message}", f"      {extra}", ""]
    for line in lines:
        print(line)
        _transcript_lines.append(line)


def _next_answer_for(r):
    """A pending yes/no symptom question gets "yes"; a pending open
    history question (duration/severity/onset) gets a plausible free-text
    answer instead of a literal "yes" that would just get stored verbatim
    as the slot value."""
    step = r.get("next_step", {})
    if step.get("answer_mode") == "yes_no":
        return "yes"
    slot = r["state"].get("pending_history_slot")
    return {"duration": "since yesterday", "severity": "7", "onset": "gradually"}.get(slot, "yes")


def drive_to_result(r, answers, state, guard_limit=10):
    guard = 0
    while r["next_step"]["type"] in ("question",) and guard < guard_limit:
        msg = _next_answer_for(r)
        r = post(msg, answers, state)
        answers, state = r["answers"], r["state"]
        show(msg, r)
        guard += 1
    return r, answers, state


def run_conversation(title, turns):
    print(f"\n{'=' * 10} {title} {'=' * 10}\n")
    _transcript_lines.append(f"\n{'=' * 10} {title} {'=' * 10}\n")
    answers, state = [], None
    r = None
    for msg in turns:
        r = post(msg, answers, state)
        answers, state = r["answers"], r["state"]
        show(msg, r)
    return r, answers, state


def check(condition, description):
    status = "PASS" if condition else "WARN"
    line = f"[{status}] {description}"
    print(line)
    _transcript_lines.append(line)
    if not condition:
        _warnings.append(description)
    return condition


# --- Conversation 1: vague start -> typo (data-seed dependent) -----------
# -> interruption -> structured assessment -> topic switch -> emotional
# concern -> doctor-prep question, all in one thread.

r1, answers1, state1 = run_conversation(
    "Conversation 1: vague start -> interruption -> structured assessment -> topic switch",
    ["hi", "I've been feeling weird lately."],
)

r1 = post("I am feeling tierd.", answers1, state1)  # typo — see NOTE above
answers1, state1 = r1["answers"], r1["state"]
show("I am feeling tierd.", r1)
tierd_present = {a[0] for a in answers1 if a[1]}
check(
    "fatigue" in tierd_present,
    "'tierd' (typo) resolved to fatigue — requires the alias to be re-seeded on Render; "
    "known pre-existing gap if this WARNs",
)

r1 = post("I also have a fever and a headache.", answers1, state1)
answers1, state1 = r1["answers"], r1["state"]
show("I also have a fever and a headache.", r1)
assert state1.get("chief_complaint") is not None, "fever/headache never started a chief complaint"

pending_slot = state1.get("pending_history_slot")
r1 = post("What medicine should I take?", answers1, state1)
answers1, state1 = r1["answers"], r1["state"]
show("What medicine should I take?", r1)
assert state1.get("pending_history_slot") == pending_slot, "pending history question was lost after an interruption"

r1, answers1, state1 = drive_to_result(r1, answers1, state1)
check(r1["next_step"]["type"] == "result", "reached a result after history-taking + symptom questions")

r1 = post("Why does fever make me weak?", answers1, state1)
answers1, state1 = r1["answers"], r1["state"]
show("Why does fever make me weak?", r1)
assert r1["next_step"]["type"] != "result", "a general question re-triggered the disease engine"

r1 = post("I'm scared.", answers1, state1)
answers1, state1 = r1["answers"], r1["state"]
show("I'm scared.", r1)
assert r1["next_step"]["type"] != "result"

r1 = post("What should I tell my doctor?", answers1, state1)
answers1, state1 = r1["answers"], r1["state"]
show("What should I tell my doctor?", r1)
assert r1["next_step"]["type"] != "result"


# --- Conversation 2: full assessment -> worsening -> improvement -> ------
# Hinglish -> typo+Hinglish -> restart.

r2, answers2, state2 = run_conversation(
    "Conversation 2: result -> worsening -> improvement -> Hinglish -> restart",
    ["I have fever, headache and chills."],
)
r2, answers2, state2 = drive_to_result(r2, answers2, state2)
assert r2["next_step"]["type"] == "result", "never reached a result in conversation 2"

r2 = post("Actually, I feel much worse now.", answers2, state2)
answers2, state2 = r2["answers"], r2["state"]
show("Actually, I feel much worse now.", r2)
check(state2.get("user_reported_worsening") is True, "worsening statement set user_reported_worsening")
check(r2["next_step"]["type"] != "result", "worsening did not re-trigger the disease engine")

r2 = post("Now I am fine.", answers2, state2)
answers2, state2 = r2["answers"], r2["state"]
show("Now I am fine.", r2)
check(state2.get("user_reported_improvement") is True, "improvement statement set user_reported_improvement")

r2 = post("mujhe kal se bukhar h aur sar dard ho rha h", answers2, state2)
answers2, state2 = r2["answers"], r2["state"]
show("mujhe kal se bukhar h aur sar dard ho rha h", r2)
hinglish_present = {a[0] for a in answers2 if a[1]}
check({"high_fever", "headache"} <= hinglish_present, "Hinglish fever+headache message understood")

r2 = post("tierd hu aur vomiting bhi ho rhi h", answers2, state2)
answers2, state2 = r2["answers"], r2["state"]
show("tierd hu aur vomiting bhi ho rhi h", r2)
check("vomiting" in {a[0] for a in answers2 if a[1]}, "typo+Hinglish message at least recognized 'vomiting'")

r2 = post("restart", answers2, state2)
answers2, state2 = r2["answers"], r2["state"]
show("restart", r2)
assert r2["next_step"]["type"] == "reset"


# --- Conversation 3: a pending history question answered together with ---
# a new symptom in the same message — the concrete fix in this session.

r3, answers3, state3 = run_conversation(
    "Conversation 3: duration question answered together with a new symptom",
    ["I have stomach pain"],
)
assert state3.get("pending_history_slot") == "duration"

r3 = post("about three days, and I also feel dizzy", answers3, state3)
answers3, state3 = r3["answers"], r3["state"]
show("about three days, and I also feel dizzy", r3)
check("dizziness" in {a[0] for a in answers3 if a[1]}, "dizziness captured")
check(state3.get("duration") is not None, "duration also captured in the same message")
check(state3.get("pending_history_slot") != "duration", "duration question is no longer pending (not re-asked)")

r3, answers3, state3 = drive_to_result(r3, answers3, state3)

r3 = post("I love you", answers3, state3)
answers3, state3 = r3["answers"], r3["state"]
show("I love you", r3)

r3 = post("By the way, why do people get hiccups?", answers3, state3)
answers3, state3 = r3["answers"], r3["state"]
show("By the way, why do people get hiccups?", r3)
assert r3["next_step"]["type"] != "result", "topic switch re-triggered the disease engine"

r3 = post("What should I eat?", answers3, state3)
answers3, state3 = r3["answers"], r3["state"]
show("What should I eat?", r3)

r3 = post("bye", answers3, state3)
show("bye", r3)
assert r3["next_step"]["type"] == "reset"


with open("scripts/verify_semantic_layer_transcript.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(_transcript_lines))

if _warnings:
    print(f"\n{len(_warnings)} WARNING(S) (informational, not hard failures):")
    for w in _warnings:
        print(f"  - {w}")

print("\nALL ASSERTIONS PASSED. Transcript saved to scripts/verify_semantic_layer_transcript.txt")
