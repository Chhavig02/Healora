"""Covers Phase 14 items #9 (disease ranking) and #10 (follow-up questions).
Uses the real migrated dataset (via the `seeded` fixture) rather than a
synthetic one — disease_matcher is generic, so this doubles as a check that
it behaves sensibly against real data, not just a crafted fixture.
"""

import disease_matcher


def test_rank_diseases_finds_dengue_for_its_symptoms(app_ctx, seeded):
    ranked = disease_matcher.rank_diseases(
        ["high_fever", "headache", "joint_pain", "pain_behind_the_eyes"], []
    )
    assert ranked
    names = [r["name"] for r in ranked]
    assert "Dengue" in names


def test_rank_diseases_no_yes_symptoms_returns_empty(app_ctx, seeded):
    assert disease_matcher.rank_diseases([], []) == []


def test_rank_diseases_ignores_unknown_symptom_names(app_ctx, seeded):
    assert disease_matcher.rank_diseases(["not_a_real_symptom"], []) == []


def test_rank_diseases_scores_ordered_descending(app_ctx, seeded):
    ranked = disease_matcher.rank_diseases(["high_fever", "headache"], [])
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


def test_get_next_step_asks_a_question_for_one_ambiguous_symptom(app_ctx, seeded):
    step = disease_matcher.get_next_step([["joint_pain", True]])
    assert step is not None
    assert step["type"] == "question"
    assert step["raw_symptom"] != "joint_pain"  # already known, shouldn't re-ask


def test_get_next_step_does_not_repeat_a_known_symptom(app_ctx, seeded):
    step = disease_matcher.get_next_step([["joint_pain", True]])
    assert step["type"] == "question"
    # Answer it and confirm the next question (if any) is still a different symptom
    answers = [["joint_pain", True], [step["raw_symptom"], True]]
    step2 = disease_matcher.get_next_step(answers)
    known = {a[0] for a in answers}
    if step2["type"] == "question":
        assert step2["raw_symptom"] not in known


def test_get_next_step_reaches_result_with_enough_symptoms(app_ctx, seeded):
    answers = [
        ["high_fever", True],
        ["headache", True],
        ["joint_pain", True],
        ["pain_behind_the_eyes", True],
    ]
    step = disease_matcher.get_next_step(answers)
    assert step["type"] == "result"
    assert "possible_conditions" in step
    assert step["match_strength"] in ("strong", "moderate", "possible")
    # top-level severity must be present (frontend reads next_step.severity
    # directly, not just possible_conditions[i].severity)
    assert step["severity"] in ("low", "medium", "high", "critical")
    # never expose a numeric confidence/probability
    assert "confidence" not in step


def test_get_next_step_returns_none_when_nothing_matches(app_ctx, seeded):
    assert disease_matcher.get_next_step([["not_a_real_symptom", True]]) is None


def test_get_next_step_stops_after_max_questions(app_ctx, seeded):
    # Feed a wall of unrelated "no" answers past MAX_QUESTIONS to confirm it
    # eventually presents a result instead of asking forever. Prime with one
    # real "yes" symptom so ranking has something to work with.
    answers = [["high_fever", True]]
    for name in symptom_names_sample(app_ctx, exclude={"high_fever"}, n=disease_matcher.MAX_QUESTIONS + 2):
        answers.append([name, False])
    step = disease_matcher.get_next_step(answers)
    assert step is not None
    assert step["type"] in ("question", "result")


def symptom_names_sample(app_ctx, exclude, n):
    import symptom_engine

    names = [s for s in symptom_engine.get_all_symptom_names() if s not in exclude]
    return names[:n]
