"""
The agreement normalizer unpacks a set however it arrives.

Reported by the auditor as a latent hazard rather than a live bug, and it had
already caught me once. Matching only ``list`` meant a caller who built the
tuple itself fell through to ``str(value)``: ``"('age', 'meds')"``. That is one
string per distinct set, so it compares correctly, sorts correctly, and passes
its tests -- while doing something nobody wrote down. The first draft of the
multiselect fix in 00fb6f21 did exactly that, and only an A/B against the line
it replaced showed the guard was not testing what it claimed.
"""

from potato.admin import AdminDashboard


def _normalize(value):
    """Called unbound: the method reads no instance state."""
    return AdminDashboard._normalize_annotation_value(None, value)


class TestNormalizeAnnotationValue:

    def test_a_set_of_labels_normalizes_the_same_from_any_container(self):
        """The container is the caller's choice; the answer is the same.

        Asserted as equality between the four forms rather than against a
        literal, because the defect was that one of them produced something
        different that still worked.
        """
        expected = ("age", "meds")
        assert _normalize(["meds", "age"]) == expected
        assert _normalize(("meds", "age")) == expected
        assert _normalize({"meds", "age"}) == expected
        assert _normalize(frozenset(["meds", "age"])) == expected

    def test_a_tuple_is_not_stringified(self):
        """The specific shape of the near-miss: a tuple must not become
        ``"('age', 'meds')"``."""
        result = _normalize(("age", "meds"))
        assert isinstance(result, tuple), result
        assert result == ("age", "meds")
        assert not isinstance(result, str)

    def test_order_does_not_change_the_answer(self):
        """Two annotators who picked the same labels in a different order
        agree, which is the whole reason this sorts."""
        assert _normalize(["b", "a", "c"]) == _normalize(("c", "b", "a"))

    def test_a_scalar_answer_is_left_as_a_string(self):
        """Radio and likert take this path, and the interval fallback below it
        depends on the value still being coercible to a number."""
        assert _normalize("eligible") == "eligible"
        assert _normalize(4) == "4"
        assert float(_normalize(4)) == 4.0

    def test_booleans_are_lowercased_rather_than_unpacked(self):
        """A bool is not a set, and `True` must not read as the string
        `"True"` beside a `"true"` written by another path."""
        assert _normalize(True) == "true"
        assert _normalize(False) == "false"
