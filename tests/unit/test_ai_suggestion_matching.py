"""A model declining to answer is not an endorsement.

`suggestive_choice` reached the client unchecked, and
`highlightSuggestedLabel` matched with four clauses, the fourth of which
tested in the opposite direction to the other three:

    suggestedLabelStr.includes(inputValue)

So any label whose NAME appeared anywhere inside the suggestion matched.
Measured in the browser on a radio scheme with labels yes/no:

    "The reviewer does not say anything about the food."  -> No   ("does not")
    "I know the answer is unclear."                       -> No   ("know")

The DOM afterwards read `<label class="ai-suggested-label">No ✨</label>` with
a title of "AI Suggested". A negated sentence endorses both sides at once:
"The image is not a circle, it is a square" matches square AND circle.

English makes that ordinary rather than exotic -- "not", "know", "another",
"north" all contain "no" -- and short labels are the normal case for a two-way
scheme.

Fixed in two places on purpose. Dropping the clause fixes the matching; the
client fix still assumes the model returns a bare label. Validating server-side
against the scheme's own labels does not assume anything about the model, and
it is the only one of the two that also catches a whole sentence of advice
arriving in that field.
"""

import pytest

from potato.ai.ai_cache import validate_suggested_choice


LABELS = ["yes", "no"]


class TestASentenceIsNotALabel:

    @pytest.mark.parametrize("suggestion", [
        "The reviewer does not say anything about the food.",
        "I know the answer is unclear.",
        "The image is not a circle, it is a square.",
        "This is neither positive nor negative.",
        "Look for the specific geometric properties of the object.",
    ])
    def test_it_is_rejected(self, suggestion):
        result = validate_suggested_choice(
            {"hint": "h", "suggestive_choice": suggestion}, LABELS)
        assert result["suggestive_choice"] == "", (
            f"{suggestion!r} would be rendered to the annotator as a "
            "suggestion with a sparkle")

    def test_what_the_model_said_is_kept(self):
        """Dropped, not deleted: the record still has to show the reply."""
        result = validate_suggested_choice(
            {"suggestive_choice": "I cannot tell."}, LABELS)
        assert result["suggestive_choice_rejected"] == "I cannot tell."


class TestARealLabelSurvives:

    def test_an_exact_label_passes(self):
        result = validate_suggested_choice(
            {"hint": "h", "suggestive_choice": "yes"}, LABELS)
        assert result["suggestive_choice"] == "yes"
        assert "suggestive_choice_rejected" not in result

    def test_case_is_normalized_to_the_configured_spelling(self):
        result = validate_suggested_choice(
            {"suggestive_choice": "No"}, LABELS)
        assert result["suggestive_choice"] == "no"

    def test_surrounding_whitespace_is_tolerated(self):
        assert validate_suggested_choice(
            {"suggestive_choice": "  yes  "}, LABELS)["suggestive_choice"] == "yes"

    def test_dict_labels_are_read_by_name(self):
        labels = [{"name": "positive"}, {"name": "negative"}]
        assert validate_suggested_choice(
            {"suggestive_choice": "positive"}, labels)["suggestive_choice"] == \
            "positive"


class TestMultipleChoices:

    def test_the_bad_ones_are_dropped_and_the_good_kept(self):
        result = validate_suggested_choice(
            {"suggestive_choices": ["yes", "banana"]}, LABELS)
        assert result["suggestive_choices"] == ["yes"]
        assert result["suggestive_choices_rejected"] == ["banana"]

    def test_a_list_stays_a_list_when_all_are_rejected(self):
        result = validate_suggested_choice(
            {"suggestive_choices": ["banana"]}, LABELS)
        assert result["suggestive_choices"] == []


class TestSchemesWithNothingToCheckAgainst:
    """Numeric scales and free-text schemes have no label vocabulary, and
    inventing a refusal for them would break working studies."""

    @pytest.mark.parametrize("labels", [[], None, "not a list"])
    def test_the_value_passes_through(self, labels):
        assert validate_suggested_choice(
            {"suggestive_choice": "42"}, labels)["suggestive_choice"] == "42"

    def test_a_non_dict_result_passes_through(self):
        assert validate_suggested_choice("Error: endpoint down", LABELS) == \
            "Error: endpoint down"

    def test_a_response_without_a_choice_is_untouched(self):
        assert validate_suggested_choice({"hint": "h"}, LABELS) == {"hint": "h"}


class TestItIsWiredIntoTheResponsePath:
    """Validating the function proves nothing unless the funnel calls it.

    `compute_help` is the single point every generator returns through, so the
    check is driven from there with a stubbed generator -- not by reading the
    call site.
    """

    def _compute(self, monkeypatch, generated, labels):
        from potato.ai import ai_cache

        scheme = {"annotation_type": "radio", "name": "s", "labels": labels}
        monkeypatch.setattr(ai_cache, "config",
                            {"annotation_schemes": [scheme]}, raising=False)
        monkeypatch.setattr(ai_cache, "_get_scheme_field",
                            lambda _id, field: scheme.get(field))

        manager = ai_cache.AiCacheManager.__new__(ai_cache.AiCacheManager)
        monkeypatch.setattr(
            manager, "_validate_assistant_compatibility",
            lambda *a, **k: (True, None), raising=False)
        monkeypatch.setattr(
            manager, "generate_radio",
            lambda *a, **k: dict(generated), raising=False)
        return manager.compute_help("i1", 0, "hint")

    def test_a_sentence_does_not_reach_the_client(self, monkeypatch):
        result = self._compute(
            monkeypatch,
            {"hint": "h",
             "suggestive_choice": "The reviewer does not say anything."},
            ["yes", "no"])
        assert result["suggestive_choice"] == "", (
            "compute_help returned the sentence unchecked, so the client "
            "highlights whatever label name it happens to contain")
        assert "suggestive_choice_rejected" in result

    def test_a_real_label_reaches_the_client(self, monkeypatch):
        result = self._compute(
            monkeypatch, {"hint": "h", "suggestive_choice": "yes"},
            ["yes", "no"])
        assert result["suggestive_choice"] == "yes"


class TestTheClientNoLongerMatchesBackwards:
    """The clause is gone from the source, and the shape it created is what
    this asserts against -- reproduced here so the rule is testable without a
    browser."""

    def _matches(self, suggestion, label):
        """The surviving three clauses, as the client now applies them."""
        s = suggestion.lower().strip()
        value = label.lower()
        return value == s or f"id_{value}".find(s) >= 0 or label.lower().find(s) >= 0

    def test_a_sentence_containing_a_label_does_not_match_it(self):
        assert not self._matches(
            "The reviewer does not say anything about the food.", "No")

    def test_an_exact_label_still_matches(self):
        assert self._matches("yes", "yes")

    def test_the_reversed_clause_is_gone_from_the_source(self):
        from pathlib import Path

        source = Path("potato/static/ai_assistant_manager.js").read_text()
        body = source.split("const isMatch =", 1)[1].split(";", 1)[0]
        assert "includes(inputValue)" not in body, (
            "the suggestion is being substring-searched for label names again")


class TestAnUnknownAssistantIsRefusedNotCrashed:
    """`aiAssistant` is user-supplied and was the one parameter in that handler
    not checked. An unrecognized name reached

        ai_prompt[annotation_type].get(ai_assistant).get("output_format")

    and raised AttributeError on None -- a 500, four lines after `annotationId`
    gets a clean 400 for the same class of mistake.

    Driven through the real handler so a rename of the check does not stop
    measuring it.
    """

    def _call(self, monkeypatch, assistant):
        import flask

        from potato import routes

        app = flask.Flask(__name__)
        app.secret_key = "test"
        monkeypatch.setattr(
            routes, "config",
            {"annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                     "labels": ["yes", "no"]}]},
            raising=False)
        monkeypatch.setattr(routes, "get_ai_cache_manager",
                            lambda: object(), raising=False)
        monkeypatch.setattr(
            routes, "get_ai_prompt",
            lambda: {"radio": {"hint": {}, "keyword": {}, "rationale": {}}},
            raising=False)
        monkeypatch.setattr(routes, "get_user_state",
                            lambda _u: object(), raising=False)

        handler = getattr(routes.get_ai_suggestion, "__wrapped__",
                          routes.get_ai_suggestion)
        with app.test_request_context(
                f"/get_ai_suggestion?annotationId=0&aiAssistant={assistant}"):
            flask.session["username"] = "u1"
            return handler()

    def test_an_unknown_name_is_a_400_naming_the_valid_ones(self, monkeypatch):
        response = self._call(monkeypatch, "label")
        body, status = response if isinstance(response, tuple) else (response, 200)
        assert status == 400, "an unrecognized assistant name returned a 500"
        payload = body.get_json()
        assert "label" in payload["error"]
        assert set(payload["available"]) == {"hint", "keyword", "rationale"}, (
            "the refusal has to say what the caller could have asked for")

    def test_a_missing_name_is_also_refused(self, monkeypatch):
        response = self._call(monkeypatch, "")
        _body, status = response if isinstance(response, tuple) else (response, 200)
        assert status == 400
