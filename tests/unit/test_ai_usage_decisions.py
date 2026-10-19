"""
What a saved answer did with an AI suggestion: accepted, partial or rejected.

Decided on every save from the full set of labels saved for the scheme, so a
multiselect is judged as a set and a change of mind is recorded by the last
save, not the first click.
"""

from potato.interaction_tracking import AIUsageEvent, BehavioralData
from potato.server_utils.annotation_keys import chosen_labels as _chosen_labels


def record(shown, schema="topics"):
    bd = BehavioralData(instance_id="i1")
    bd.ai_usage.append(AIUsageEvent(request_timestamp=100.0, schema_name=schema,
                                    suggestions_shown=shown, response_timestamp=101.0))
    return bd


def decide(shown, saved, schema="topics"):
    bd = record(shown, schema)
    bd.record_decisions({schema: set(saved)}, now=103.5)
    return bd.ai_usage[0]


def test_single_choice():
    took = decide(["positive"], ["positive"], "sentiment")
    assert (took.decision, took.suggestion_accepted, took.time_to_decision_ms) == ("accepted", "positive", 2500)
    assert decide(["positive"], ["negative"], "sentiment").decision == "rejected"


def test_multiselect_is_judged_as_a_set():
    assert decide(["A", "B"], ["A", "C", "D"]).decision == "partial"
    assert decide(["A"], ["C", "A"]).decision == "accepted"
    assert decide(["A", "B"], ["A", "B", "C"]).suggestion_accepted == "A, B"
    assert decide(["A", "B"], ["C"]).suggestion_accepted is None


def test_the_last_save_decides():
    bd = record(["positive"], "sentiment")
    bd.record_decisions({"sentiment": {"positive"}}, now=102)
    bd.record_decisions({"sentiment": {"negative"}}, now=110)
    assert (bd.ai_usage[0].decision, bd.ai_usage[0].suggestion_accepted) == ("rejected", None)


def test_unsaved_schemes_and_no_suggestions_stay_undecided():
    bd = record(["A"])
    bd.ai_usage.append(AIUsageEvent(request_timestamp=1, schema_name="other", suggestions_shown=[]))
    assert bd.record_decisions({"elsewhere": {"A"}, "other": {"x"}}) == 0
    assert bd.ai_usage[0].decision is None


def test_the_decision_survives_a_round_trip():
    bd = record(["A"])
    bd.record_decisions({"topics": {"A"}})
    assert BehavioralData.from_dict(bd.to_dict()).ai_usage[0].decision == "accepted"


def test_chosen_labels_reads_every_selected_label():
    assert _chosen_labels({"topics:::A": "A", "topics:::B": "on", "topics:::C": "",
                           "sentiment:::negative": "negative", "notes:::text_box": "free text",
                           "plain": "x"}) == {
        "topics": {"A", "B"}, "sentiment": {"negative"}, "notes": {"free text"}}


def test_scalar_answers_are_their_values():
    """A slider at 1 is "1", free text "yes" is "yes", and 0 is an answer."""
    types = {"rating": "slider", "rating2": "slider", "n": "number", "free": "text"}
    assert _chosen_labels({"rating:rating": "1", "rating2:rating2": "4", "n:n": 0,
                           "free:text_box": "yes"}, types) == {
        "rating": {"1"}, "rating2": {"4"}, "n": {"0"}, "free": {"yes"}}
    took = decide(["1"], _chosen_labels({"rating:rating": "1"}, types)["rating"], "rating")
    assert took.decision == "accepted"
    assert decide(["yes"], _chosen_labels({"free:text_box": "yes"}, types)["free"], "free").decision == "accepted"
