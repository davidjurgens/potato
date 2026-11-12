"""`require_fully_annotated: true` actually requires a full annotation.

The key was documented in `config_key_docs` ("Refuse to advance until every
scheme on the page has an answer"), accepted as a top-level key,
type-validated as a bool, published in `potato-config.schema.json`, and set to
`true` in Potato's own `examples/advanced/full-study-skeleton/config.yaml`.
Nothing read it at top level. An annotator could answer one of three schemes on
every item and advance each time, on a study whose config said they could not.

Measured before the fix, one study and one config line apart:

    require_fully_annotated: true          served i0, i1, i2, i3 -> 200
    label_requirement:{required:true} x3   served i0, i0, i0, i0 -> 400

The same name inside the `adjudication` block is a different, working feature
and is left alone.

Wired in `normalize_config_before_validation` rather than at the gate, because
the gate reads `_scheme_is_required` while the `required` attribute on the
rendered input comes from `label_requirement`. Wiring only the gate would give
a server refusal on a page that never marked the missing question.
"""

import pytest

from potato.server_utils.config_module import (
    _apply_require_fully_annotated, _scheme_is_required_for_test)


def apply(config):
    _apply_require_fully_annotated(config)
    return config


def schemes(*names):
    return [{"annotation_type": "radio", "name": n, "labels": ["a", "b"]}
            for n in names]


class TestTheFlagMakesEverySchemeRequired:

    def test_every_scheme_is_marked(self):
        config = apply({"require_fully_annotated": True,
                        "annotation_schemes": schemes("q", "t", "why")})
        assert all(s["label_requirement"] == {"required": True}
                   for s in config["annotation_schemes"]), (
            "an annotator could skip every question on every item")

    def test_the_flag_off_changes_nothing(self):
        config = apply({"annotation_schemes": schemes("q", "t")})
        assert all("label_requirement" not in s
                   for s in config["annotation_schemes"])

    def test_a_false_flag_changes_nothing(self):
        config = apply({"require_fully_annotated": False,
                        "annotation_schemes": schemes("q")})
        assert "label_requirement" not in config["annotation_schemes"][0]

    def test_a_truthy_non_true_value_does_not_count(self):
        """The key is type-validated as a bool; a string must not enable it by
        accident."""
        config = apply({"require_fully_annotated": "yes",
                        "annotation_schemes": schemes("q")})
        assert "label_requirement" not in config["annotation_schemes"][0]


class TestPerSchemeSettingsWin:
    """In both directions: the flag cannot un-require a scheme, and a scheme
    that opts out stays optional."""

    def test_an_explicit_opt_out_survives(self):
        config = apply({"require_fully_annotated": True, "annotation_schemes": [
            {"annotation_type": "text", "name": "optional_note",
             "label_requirement": {"required": False}}]})
        assert config["annotation_schemes"][0]["label_requirement"] == {
            "required": False}, "the flag overrode a scheme's own opt-out"

    def test_a_bare_required_false_survives(self):
        config = apply({"require_fully_annotated": True, "annotation_schemes": [
            {"annotation_type": "text", "name": "n", "required": False}]})
        assert "label_requirement" not in config["annotation_schemes"][0]
        assert config["annotation_schemes"][0]["required"] is False

    def test_an_existing_requirement_is_not_rewritten(self):
        config = apply({"require_fully_annotated": True, "annotation_schemes": [
            {"annotation_type": "radio", "name": "q",
             "label_requirement": {"required": True, "min_labels": 2}}]})
        assert config["annotation_schemes"][0]["label_requirement"] == {
            "required": True, "min_labels": 2}, (
            "stamping over it would have dropped min_labels")


class TestPhaseNestedSchemes:
    """Schemes can live under `phases` instead of at the top level."""

    def test_a_list_of_phases_is_covered(self):
        config = apply({"require_fully_annotated": True, "phases": [
            {"name": "p1", "annotation_schemes": schemes("q")}]})
        assert config["phases"][0]["annotation_schemes"][0][
            "label_requirement"] == {"required": True}

    def test_a_dict_of_phases_is_covered(self):
        config = apply({"require_fully_annotated": True, "phases": {
            "order": ["p1"],
            "p1": {"annotation_schemes": schemes("q")}}})
        assert config["phases"]["p1"]["annotation_schemes"][0][
            "label_requirement"] == {"required": True}


class TestTheGateReadsIt:
    """The stamped key has to be the one `_scheme_is_required` consults, or the
    normalization is decorative."""

    def test_a_stamped_scheme_is_required(self):
        config = apply({"require_fully_annotated": True,
                        "annotation_schemes": schemes("q")})
        assert _scheme_is_required_for_test(config["annotation_schemes"][0])

    def test_an_unstamped_scheme_is_not(self):
        config = apply({"annotation_schemes": schemes("q")})
        assert not _scheme_is_required_for_test(config["annotation_schemes"][0])


class TestMalformedInputDoesNotRaise:
    """Normalization runs before validation, so it meets configs that have not
    been checked yet."""

    @pytest.mark.parametrize("config", [
        {"require_fully_annotated": True},
        {"require_fully_annotated": True, "annotation_schemes": None},
        {"require_fully_annotated": True, "annotation_schemes": ["not a dict"]},
        {"require_fully_annotated": True, "phases": None},
        {"require_fully_annotated": True, "phases": "nonsense"},
    ])
    def test_it_survives(self, config):
        _apply_require_fully_annotated(config)
