"""
Presentation order: which options were shown, in what order, and recorded.

Potato showed every annotator the same options in the same order on every item
and never wrote down that it had. Both halves matter, and the recording half
matters more: randomisation only helps data collected after it is switched on,
whereas a recorded order lets an already-finished study be corrected.

Position bias is worse for a measurement tool than for a collection tool.
Because every annotator shares the pull toward the first option, it does not
cancel -- it *inflates* agreement while biasing the estimate, so the
reliability number comes out confidently wrong.

Three defects in the shipped implementation these tests pin down:

* the seed came from the builtin ``hash()``, which is salted per process, so
  every option set re-ordered on each server restart
* the seed did not include the item, so one annotator saw one arrangement for
  the whole study and their bias was perfectly correlated rather than averaged
* ``randomize_options`` was called from inside the loop that built its own
  argument, so it re-shuffled the page once per configured scheme
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from potato.server_utils import presentation_order as po

RADIO = {
    "annotation_type": "radio",
    "name": "tone",
    "description": "Tone",
    "labels": [{"name": "positive"}, {"name": "neutral"}, {"name": "negative"}],
    "randomize_order": True,
}

FIXED = dict(RADIO, name="fixed", randomize_order=False)

TEXTBOX = {"annotation_type": "textbox", "name": "notes", "description": "d"}


class TestTheSeedIsStable:
    def test_the_same_triple_always_gives_the_same_order(self):
        first = po.presentation_order(RADIO, "alice", "i1")
        second = po.presentation_order(RADIO, "alice", "i1")
        assert first == second, (
            "an annotator who reloads must see the same arrangement; a "
            "different one each time is a different question each time")

    def test_it_survives_a_fresh_interpreter_with_a_different_hash_seed(self):
        """
        The original bug. Python salts string hashing per process unless
        PYTHONHASHSEED is pinned, so a builtin hash() re-ordered every option
        set on every server restart.
        """
        script = (
            "from potato.server_utils.presentation_order import order_seed;"
            "print(order_seed('alice', 'i1', 'tone'))"
        )
        runs = set()
        for seed_env in ("0", "1", "random"):
            out = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True,
                env={"PYTHONHASHSEED": seed_env, "PATH": "/usr/bin:/bin"},
            )
            assert out.returncode == 0, out.stderr
            runs.add(out.stdout.strip())
        assert len(runs) == 1, (
            f"order_seed changed with PYTHONHASHSEED: {runs}. An annotator "
            f"returning to an item after a restart would be asked a "
            f"different question.")

    def test_different_items_get_different_orders(self):
        """
        Seeding on the annotator alone gives one person the same arrangement
        on every item, so their first-position preference lands on the same
        label every time and is correlated across the whole study rather than
        averaged out.
        """
        orders = {tuple(po.presentation_order(RADIO, "alice", f"i{n}"))
                  for n in range(40)}
        assert len(orders) > 1

    def test_different_annotators_get_different_orders(self):
        orders = {tuple(po.presentation_order(RADIO, f"u{n}", "i1"))
                  for n in range(40)}
        assert len(orders) > 1

    def test_different_schemes_on_one_item_are_independent(self):
        a = po.presentation_order(dict(RADIO, name="a"), "alice", "i1")
        b = po.presentation_order(dict(RADIO, name="b"), "alice", "i1")
        assert a is not None and b is not None
        # Not an assertion that they differ -- two shuffles can coincide --
        # only that the scheme name reaches the seed at all.
        assert po.order_seed("alice", "i1", "a") != po.order_seed("alice", "i1", "b")


class TestPermutationDoesNotTouchGlobalRandom:
    def test_the_global_stream_is_left_alone(self):
        """
        `random.seed()` reaches into state shared by every caller in the
        process, so seeding it to lay out one radio group would silently reset
        the stream task assignment or QC sampling was drawing from.
        """
        import random

        random.seed(1234)
        expected = [random.random() for _ in range(3)]

        random.seed(1234)
        first = random.random()
        po.permutation(5, po.order_seed("alice", "i1", "tone"))
        rest = [random.random(), random.random()]
        assert [first, *rest] == expected


class TestWhatGetsAnOrder:
    def test_a_shuffled_scheme_is_a_permutation_of_its_labels(self):
        order = po.presentation_order(RADIO, "alice", "i1")
        assert sorted(order) == ["negative", "neutral", "positive"]

    def test_an_unshuffled_scheme_records_the_configured_order(self):
        """
        The point of recording. "Shown as configured" is a fact worth having,
        and it is the only thing that makes an already-finished study
        correctable.
        """
        assert po.presentation_order(FIXED, "alice", "i1") == [
            "positive", "neutral", "negative"]

    def test_a_scheme_with_no_ordered_options_gets_nothing(self):
        assert po.presentation_order(TEXTBOX, "alice", "i1") is None

    def test_a_single_option_gets_nothing(self):
        single = dict(RADIO, labels=[{"name": "only"}])
        assert po.presentation_order(single, "alice", "i1") is None

    def test_bare_string_labels_work(self):
        scheme = dict(RADIO, labels=["a", "b", "c"])
        assert sorted(po.presentation_order(scheme, "alice", "i1")) == ["a", "b", "c"]

    def test_orders_for_item_covers_every_ordered_scheme(self):
        orders = po.orders_for_item([RADIO, FIXED, TEXTBOX], "alice", "i1")
        assert set(orders) == {"tone", "fixed"}


class TestRandomizationIsOnlyPromisedWhereItWorks:
    def test_the_legacy_key_still_works(self):
        scheme = dict(RADIO)
        scheme.pop("randomize_order")
        scheme["option_randomization"] = True
        assert po.wants_randomization(scheme)

    def test_an_unsupported_type_warns_instead_of_silently_doing_nothing(self, caplog):
        """
        Declaring a key that the renderer cannot honour is worse than not
        having it: the researcher believes their study is de-biased.
        """
        scheme = {"annotation_type": "ranking", "name": "r", "description": "d",
                  "labels": ["a", "b"], "randomize_order": True}
        with caplog.at_level("WARNING"):
            assert po.wants_randomization(scheme) is False
        assert "cannot be reordered" in caplog.text

    def test_an_unsupported_type_still_gets_its_order_recorded(self):
        scheme = {"annotation_type": "ranking", "name": "r", "description": "d",
                  "labels": ["a", "b"], "randomize_order": True}
        assert po.presentation_order(scheme, "alice", "i1") == ["a", "b"]

    def test_every_randomizable_type_is_order_sensitive(self):
        assert po.RANDOMIZABLE_TYPES <= po.ORDER_SENSITIVE_TYPES

    def test_every_randomizable_type_declares_the_key(self):
        """
        A key a generator reads but optional_fields omits does not exist as
        far as the JSON Schema, the docs or an agent are concerned.
        """
        from potato.server_utils.schemas.registry import schema_registry

        for name in sorted(po.RANDOMIZABLE_TYPES):
            fields = schema_registry.get_accepted_fields(name)
            assert "randomize_order" in fields, (
                f"{name} can be randomized but does not declare "
                f"randomize_order, so no editor or agent knows it exists")


class TestDataDrivenSchemes:
    PAIRWISE = {"annotation_type": "pairwise", "name": "better",
                "description": "d", "items_key": "responses",
                "randomize_order": True}

    def test_the_order_is_source_indices(self):
        """
        Pairwise candidates are per-item text, so "this annotator saw the
        second one first" is the only fact an analyst can condition on.
        """
        order = po.item_order(self.PAIRWISE, {"responses": ["A", "B"]},
                              "alice", "i1")
        assert sorted(order) == [0, 1]

    def test_it_is_stable(self):
        data = {"responses": ["A", "B"]}
        assert (po.item_order(self.PAIRWISE, data, "alice", "i1")
                == po.item_order(self.PAIRWISE, data, "alice", "i1"))

    def test_both_orders_are_produced_across_annotators(self):
        """
        If every annotator saw the same order the bias would not cancel,
        which is the whole point.
        """
        data = {"responses": ["A", "B"]}
        seen = {tuple(po.item_order(self.PAIRWISE, data, f"u{n}", "i1"))
                for n in range(40)}
        assert seen == {(0, 1), (1, 0)}

    def test_a_non_randomized_pairwise_scheme_is_left_alone(self):
        scheme = dict(self.PAIRWISE, randomize_order=False)
        assert po.item_order(scheme, {"responses": ["A", "B"]}, "a", "i") is None

    def test_fewer_than_two_candidates_gets_nothing(self):
        assert po.item_order(self.PAIRWISE, {"responses": ["A"]}, "a", "i") is None
        assert po.item_order(self.PAIRWISE, {}, "a", "i") is None

    def test_it_does_not_also_get_a_label_order(self):
        """
        Two meanings under one scheme name would make the record
        uninterpretable without the config that produced it.
        """
        scheme = dict(self.PAIRWISE, labels=["A wins", "B wins"])
        assert po.presentation_order(scheme, "alice", "i1") is None


class TestRecording:
    class FakeState:
        def __init__(self):
            self.store = {}

        def record_presentation_order(self, instance_id, orders):
            stored = self.store.setdefault(instance_id, {})
            for name, order in orders.items():
                stored.setdefault(name, list(order))

        def get_presentation_order(self, instance_id):
            return self.store.get(instance_id, {})

    def test_the_first_order_shown_is_the_one_kept(self):
        """
        A later re-render -- after an admin edits the config, say -- must not
        rewrite history and make a stored answer look as though it was given
        under an arrangement nobody ever saw.
        """
        state = self.FakeState()
        po.record(state, "i1", {"tone": ["a", "b"]})
        result = po.record(state, "i1", {"tone": ["b", "a"]})
        assert result["tone"] == ["a", "b"]

    def test_a_new_scheme_can_still_be_added_to_an_existing_item(self):
        state = self.FakeState()
        po.record(state, "i1", {"tone": ["a", "b"]})
        result = po.record(state, "i1", {"topic": ["x", "y"]})
        assert result == {"tone": ["a", "b"], "topic": ["x", "y"]}

    def test_a_state_object_without_the_method_does_not_take_down_the_page(self):
        """
        The presentation order is diagnostic metadata. Nobody can annotate
        anything if failing to write it 500s the annotation page.
        """
        assert po.record(object(), "i1", {"tone": ["a", "b"]}) == {
            "tone": ["a", "b"]}

    def test_a_raising_state_object_is_survived(self, caplog):
        class Broken:
            def record_presentation_order(self, *_a):
                raise RuntimeError("disk full")

            def get_presentation_order(self, _i):
                return {}

        with caplog.at_level("WARNING"):
            assert po.record(Broken(), "i1", {"tone": ["a"]}) == {"tone": ["a"]}
        assert "presentation order" in caplog.text

    def test_nothing_to_record_is_a_no_op(self):
        assert po.record(object(), "i1", {}) == {}


class TestPositionOf:
    def test_it_finds_the_position(self):
        assert po.position_of(["b", "a", "c"], "a") == 1

    def test_a_label_not_shown_is_none(self):
        assert po.position_of(["b", "a"], "z") is None


class TestItSurvivesUserStateRoundTrip:
    def test_the_order_persists_through_save_and_load(self, tmp_path):
        """
        A recorded order that does not survive a restart cannot correct
        anything, because the analysis happens long after the study.
        """
        from potato.user_state_management import InMemoryUserState

        state = InMemoryUserState("alice", 10)
        state.record_presentation_order("i1", {"tone": ["b", "a", "c"]})
        state.save(str(tmp_path))

        reloaded = InMemoryUserState.load(str(tmp_path))
        assert reloaded.get_presentation_order("i1") == {"tone": ["b", "a", "c"]}
