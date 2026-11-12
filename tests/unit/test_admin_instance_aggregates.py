"""
The Instances tab used to be quadratic in the corpus.

`get_instances_data` builds a row for every instance before it filters, sorts
and paginates -- it has to, because you cannot sort by disagreement without
computing disagreement everywhere. The cost was in how each row got its
statistics: three helpers, each walking every annotator, called once per
instance. Worse, the label helper reached for `get_all_annotations()`, which
rebuilds a dict of every instance an annotator has touched. So one page of 25
rows cost instances x annotators x annotations, quadratic in the corpus.

Measured on a synthetic project, five annotators, asking for 25 rows:

    250 items    100 ms          2000 items    15.1 s
    500 items    488 ms          5000 items    ~94 s (extrapolated)
   1000 items    2.9 s          50000 items    hours

`_build_instance_aggregates` inverts the loop: one pass over annotators, each
contributing to the instances it actually touched. Same numbers, cost
proportional to the annotations that exist.

These tests pin the two things that could regress -- the arithmetic, and the
loop shape. The arithmetic tests compare against values computed by hand rather
than against the implementation, so a wrong aggregate cannot agree with a wrong
expectation.
"""

import pytest

from potato.item_state_management import Label
from potato.phase import UserPhase


@pytest.fixture
def project(monkeypatch, tmp_path):
    """A small project with known, deliberately uneven annotations."""
    from potato.server_utils.config_module import config
    import potato.item_state_management as ism_mod
    import potato.user_state_management as usm_mod

    # Save the whole config and both singletons. Nulling the singletons and
    # putting back only the keys this fixture knows about leaks state into
    # whatever runs next -- the shared managers other unit tests rely on would
    # be gone, and they fail in ways that point at themselves rather than here.
    saved_config = dict(config)
    saved_ism = ism_mod.ITEM_STATE_MANAGER
    saved_usm = usm_mod.USER_STATE_MANAGER

    config.update({
        "task_dir": str(tmp_path),
        "output_annotation_dir": str(tmp_path),
        "max_annotations_per_item": 3,
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_task_name": "aggregates",
        "annotation_schemes": [
            {"annotation_type": "multiselect", "name": "topics",
             "description": "t", "labels": ["a", "b", "c"]},
        ],
    })
    ism_mod.ITEM_STATE_MANAGER = None
    usm_mod.USER_STATE_MANAGER = None

    ism = ism_mod.init_item_state_manager(config)
    ism.add_items({str(i): {"id": str(i), "text": f"item {i}"} for i in range(4)})
    usm = usm_mod.init_user_state_manager(config)

    def annotator(uid):
        state = usm.get_or_create_user(uid)
        state.current_phase_and_page = (UserPhase.ANNOTATION, 0)
        return state

    # item 0: unanimous "a" from two annotators
    # item 1: split "a" / "b" -- disagreement 0.5
    # item 2: one annotator, two labels on the same item
    # item 3: never annotated
    a, b = annotator("ann_a"), annotator("ann_b")
    for state in (a, b):
        state.add_label_annotation("0", Label(schema="topics", name="a"), True)
        ism.register_annotator("0", state.get_user_id())
    a.add_label_annotation("1", Label(schema="topics", name="a"), True)
    b.add_label_annotation("1", Label(schema="topics", name="b"), True)
    ism.register_annotator("1", "ann_a")
    ism.register_annotator("1", "ann_b")
    a.add_label_annotation("2", Label(schema="topics", name="b"), True)
    a.add_label_annotation("2", Label(schema="topics", name="c"), True)
    ism.register_annotator("2", "ann_a")

    # timing: item 0 gets 2s and 4s (mean 3s); item 1 gets one timed and one
    # untimed annotation, so the mean must ignore the untimed one.
    a.instance_id_to_behavioral_data["0"] = {"total_time_ms": 2000, "ai_usage": [1]}
    b.instance_id_to_behavioral_data["0"] = {"total_time_ms": 4000, "ai_usage": [1, 1]}
    a.instance_id_to_behavioral_data["1"] = {"total_time_ms": 9000}
    b.instance_id_to_behavioral_data["1"] = {"ai_usage": [1]}      # no timing

    from potato.admin import admin_dashboard
    monkeypatch.setattr(admin_dashboard, "check_admin_access", lambda *a, **k: True)

    yield admin_dashboard

    ism_mod.ITEM_STATE_MANAGER = saved_ism
    usm_mod.USER_STATE_MANAGER = saved_usm
    config.clear()
    config.update(saved_config)


class TestAggregateArithmetic:
    def test_unanimous_item_has_zero_disagreement(self, project):
        agg = project._build_instance_aggregates()
        label, disagreement = project._label_stats_from_names(agg["0"]["labels"])
        assert label == "a"
        assert disagreement == 0.0

    def test_split_item_reports_the_split(self, project):
        agg = project._build_instance_aggregates()
        _, disagreement = project._label_stats_from_names(agg["1"]["labels"])
        assert disagreement == 0.5

    def test_multiple_labels_from_one_annotator_all_count(self, project):
        agg = project._build_instance_aggregates()
        assert sorted(agg["2"]["labels"]) == ["b", "c"]

    def test_untouched_item_is_absent_rather_than_empty(self, project):
        """Absent, so callers must supply the zero row themselves -- an empty
        bucket would make item 3 look annotated-but-unanimous."""
        assert "3" not in project._build_instance_aggregates()

    def test_mean_time_ignores_annotations_with_no_timing(self, project):
        agg = project._build_instance_aggregates()
        assert agg["0"]["total_seconds"] == 6.0 and agg["0"]["timed_count"] == 2
        # item 1: 9s from one annotator, the other contributed no timing at all
        assert agg["1"]["total_seconds"] == 9.0 and agg["1"]["timed_count"] == 1

    def test_ai_counts_sum_across_annotators(self, project):
        agg = project._build_instance_aggregates()
        assert agg["0"]["ai_count"] == 3     # 1 + 2
        assert agg["1"]["ai_count"] == 1

    def test_no_labels_yields_no_modal_label(self, project):
        assert project._label_stats_from_names([]) == (None, 0.0)


class TestTheEndpointAgrees:
    def test_rows_match_the_single_instance_helpers(self, project):
        """The fast path and the per-instance helpers must not drift apart."""
        data = project.get_instances_data(page=1, page_size=10, sort_by="id",
                                          sort_order="asc")
        rows = {row["id"]: row for row in data["instances"]}

        for instance_id in ("0", "1", "2", "3"):
            expected_label, expected_dis = project._calculate_label_statistics(instance_id)
            expected_ai = project._calculate_total_instance_ai(instance_id)
            expected_time = project._calculate_average_time_per_annotation(instance_id)

            row = rows[instance_id]
            assert row["most_frequent_label"] == expected_label, instance_id
            assert row["label_disagreement"] == round(expected_dis, 2), instance_id
            assert row["num_ai_instance"] == expected_ai, instance_id
            assert row["average_time_per_annotation"] == (
                project._format_seconds(expected_time) if expected_time else None
            ), instance_id

    def test_untouched_item_still_appears(self, project):
        data = project.get_instances_data(page=1, page_size=10, sort_by="id",
                                          sort_order="asc")
        row = next(r for r in data["instances"] if r["id"] == "3")
        assert row["annotation_count"] == 0
        assert row["most_frequent_label"] is None
        assert row["label_disagreement"] == 0.0
        assert row["average_time_per_annotation"] is None
        assert row["num_ai_instance"] == 0


class TestLoopShape:
    def test_annotator_state_is_read_once_per_annotator(self, project):
        """The regression that mattered: reading each annotator once per
        *instance* rather than once per request. Counting the reads is the only
        way to catch it -- the output is identical either way, just slower by a
        factor of the corpus size."""
        from potato.user_state_management import get_user_state_manager

        usm = get_user_state_manager()
        calls = []
        original = usm.get_user_state
        usm.get_user_state = lambda uid: (calls.append(uid), original(uid))[1]
        try:
            project._build_instance_aggregates()
        finally:
            usm.get_user_state = original

        assert sorted(calls) == ["ann_a", "ann_b"], (
            f"expected one read per annotator, got {len(calls)}: {calls}"
        )

    def test_label_lookup_does_not_rebuild_every_annotation(self, project):
        """`_calculate_label_statistics` used `get_all_annotations()`, which
        materializes every instance an annotator has touched. For one instance
        that is the wrong question to ask."""
        from potato.user_state_management import get_user_state_manager

        state = get_user_state_manager().get_user_state("ann_a")
        calls = []
        state.get_all_annotations = lambda: (calls.append(1), {})[1]

        project._calculate_label_statistics("0")
        assert not calls, "single-instance label lookup rebuilt the full annotation set"

class TestDisagreementIsRealAgain:
    """The column showed 0.00 for every item in every project.

    ``sentiment:positive`` is stored as a Label named "positive" carrying the
    value ``True``. The old code asked for a ``label_name`` attribute Label does
    not have, fell through to ``str(value)``, and counted "True" -- so every
    annotator on every item contributed the same token, the modal label was
    always "True", and disagreement was always 1 - n/n = 0. Two annotators
    choosing opposite labels scored perfect agreement, which is the same shape
    as the adjudication bug fixed in Wave 0.4b.
    """

    def test_modal_label_is_a_label_not_its_truthiness(self, project):
        label, _ = project._label_stats_from_names(
            project._build_instance_aggregates()["0"]["labels"])
        assert label == "a"
        assert label != "True", "reading the value instead of the name is back"

    def test_disagreeing_annotators_do_not_score_as_unanimous(self, project):
        """Item 1 is one 'a' and one 'b'. Before the fix this was 0.0."""
        _, disagreement = project._label_stats_from_names(
            project._build_instance_aggregates()["1"]["labels"])
        assert disagreement == 0.5

    def test_sorting_by_disagreement_orders_by_something(self, project):
        """With every value 0.0 the sort was a no-op, so the 'most contentious
        items first' affordance did nothing."""
        rows = project.get_instances_data(
            page=1, page_size=10, sort_by="disagreement", sort_order="desc")["instances"]
        scores = [r["label_disagreement"] for r in rows]
        assert scores == sorted(scores, reverse=True)
        assert len(set(scores)) > 1, "every instance still reports the same disagreement"

    def test_a_bare_string_key_still_falls_back_to_its_value(self, project):
        """Not every stored key is a Label; the fallback has to survive."""
        assert project._label_stats_from_names(["x", "x", "y"])[0] == "x"

