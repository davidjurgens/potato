"""`labels: [Yes, No]` must fail validation, not boot and then vanish.

YAML 1.1 reads Yes/No/On/Off/Y/N/True/False in any capitalisation as booleans,
so PyYAML hands Potato `[True, False]` for the most ordinary label pair there
is. Seven validation sites checked that `labels` was a non-empty list and none
looked inside it. The only element-type check lived in the schema generator,
which runs at boot and logs rather than raising, so the config validated clean,
started clean, and rendered an error card where the question should have been.

If the scheme was required and `require_fully_annotated` was on, the annotator
was then stuck on item one with no visible question and no message naming one.
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_label_list_elements,
    validate_single_annotation_scheme,
)


def _radio(labels):
    return {
        "annotation_type": "radio",
        "name": "q1",
        "description": "Plain",
        "labels": labels,
    }


class TestBooleanLabelsAreRejected:
    @pytest.mark.parametrize("labels", [
        [True, False],       # Yes/No, On/Off, Y/N, True/False
        ["Maybe", False],    # one bad element among good ones
        [False],
    ])
    def test_boolean_element_fails(self, labels):
        with pytest.raises(ConfigValidationError):
            validate_label_list_elements(_radio(labels), "annotation_schemes[0]")

    def test_the_message_names_the_cause(self):
        """"Invalid label format: True" does not point back at `Yes`."""
        with pytest.raises(ConfigValidationError) as exc:
            validate_label_list_elements(_radio([True, False]), "annotation_schemes[0]")

        message = str(exc.value)
        assert "boolean" in message
        assert "Yes/No" in message
        assert "Quote it" in message

    def test_the_message_locates_the_element(self):
        with pytest.raises(ConfigValidationError) as exc:
            validate_label_list_elements(_radio(["ok", True]), "annotation_schemes[3]")

        assert "annotation_schemes[3].labels[1]" in str(exc.value)


class TestOtherBadElements:
    def test_a_number_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="must be a string or a mapping"):
            validate_label_list_elements(_radio([1, 2]), "annotation_schemes[0]")

    def test_a_mapping_without_name_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="without a 'name' key"):
            validate_label_list_elements(
                _radio([{"tooltip": "no name here"}]), "annotation_schemes[0]")

    def test_a_mapping_whose_name_is_a_boolean_is_rejected(self):
        # `- name: Yes` inside a label mapping is the same trap one level down.
        with pytest.raises(ConfigValidationError, match="name must be a string"):
            validate_label_list_elements(
                _radio([{"name": True}]), "annotation_schemes[0]")

    def test_options_are_checked_too(self):
        """multirate's `options` reaches the same generator check."""
        scheme = {
            "annotation_type": "multirate",
            "name": "m",
            "description": "d",
            "labels": ["1", "2"],
            "options": [True, "Relevance"],
        }
        with pytest.raises(ConfigValidationError, match=r"\.options\[0\]"):
            validate_label_list_elements(scheme, "annotation_schemes[0]")


class TestGoodLabelsStillPass:
    @pytest.mark.parametrize("labels", [
        ["Yes", "No"],
        ["Positive", "Negative", "Neutral"],
        [{"name": "PERSON", "tooltip": "people"}, {"name": "ORG"}],
        [{"name": "a"}, "b"],
    ])
    def test_accepted(self, labels):
        validate_label_list_elements(_radio(labels), "annotation_schemes[0]")

    def test_a_scheme_without_labels_is_untouched(self):
        validate_label_list_elements(
            {"annotation_type": "textbox", "name": "t", "description": "d"},
            "annotation_schemes[0]")

    def test_labels_that_are_not_a_list_are_left_to_the_type_check(self):
        """A string `labels` is a different error, raised by the type block."""
        validate_label_list_elements(_radio("Yes"), "annotation_schemes[0]")


class TestReachedFromFullSchemeValidation:
    def test_the_boolean_label_fails_the_whole_scheme(self):
        with pytest.raises(ConfigValidationError, match="boolean"):
            validate_single_annotation_scheme(_radio([True, False]), "annotation_schemes[0]")

    def test_a_good_scheme_still_validates(self):
        validate_single_annotation_scheme(_radio(["Yes", "No"]), "annotation_schemes[0]")
