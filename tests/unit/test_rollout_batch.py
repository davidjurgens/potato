"""
Running the rollout judge over a project, and building the human side.

Most of this file is about :func:`human_consensus`, because that is where the
judgement calls are. Collapsing N annotators into one answer per stream can be
done several ways and most of them quietly invent agreement; these tests pin
the ones that do not.
"""

import json
import os

import pytest

from potato.rollouts import batch

SCHEMA = {"name": "rollouts", "annotation_type": "rollout_evaluation"}


def value(violations=None, clean=None):
    return json.dumps({"violations": violations or [], "clean": clean or [],
                       "preference": {}, "counterfactual": {}})


def mark(stream_id, t, category="gravity_violation", severity="major"):
    """
    The key is ``stream``, not ``stream_id``.

    ``rollout-eval.js:703`` writes ``{stream, t, type, severity}``; the panel
    manifest calls the same field ``stream_id``. Fixtures must use the key the
    client actually writes — inventing a plausible one produces a test that
    passes against nothing.
    """
    return {"stream": stream_id, "t": t, "type": category,
            "severity": severity}


class TestHumanConsensus:
    def test_the_consensus_time_is_the_median_not_the_mean(self):
        """
        One annotator who marked the wrong moment entirely should move the
        answer by one position, not drag it halfway across the clip.
        """
        rows = {"i0": {
            "a": value([mark("gen_a", 2.0)]),
            "b": value([mark("gen_a", 2.2)]),
            "c": value([mark("gen_a", 9.0)]),   # the outlier
        }}
        consensus = batch.human_consensus(SCHEMA, rows)
        assert consensus["i0::gen_a"]["t"] == 2.2   # mean would be 4.4

    def test_the_category_is_the_modal_one(self):
        rows = {"i0": {
            "a": value([mark("gen_a", 2.0, "interpenetration")]),
            "b": value([mark("gen_a", 2.1, "interpenetration")]),
            "c": value([mark("gen_a", 2.2, "gravity_violation")]),
        }}
        assert batch.human_consensus(SCHEMA, rows)["i0::gen_a"]["type"] == \
            "interpenetration"

    def test_a_majority_clean_is_a_real_answer_of_no_break(self):
        """
        Not a missing answer. "Nobody found a problem here" is something the
        judge can be right or wrong about, and dropping it would score the
        judge only on the rollouts that break.
        """
        rows = {"i0": {
            "a": value(clean=["gen_a"]),
            "b": value(clean=["gen_a"]),
            "c": value([mark("gen_a", 2.0)]),
        }}
        entry = batch.human_consensus(SCHEMA, rows)["i0::gen_a"]
        assert entry["t"] is None
        assert entry["n_clean"] == 2 and entry["n_marked"] == 1

    def test_a_majority_marked_wins_over_the_clean_votes(self):
        rows = {"i0": {
            "a": value([mark("gen_a", 2.0)]),
            "b": value([mark("gen_a", 2.4)]),
            "c": value(clean=["gen_a"]),
        }}
        assert batch.human_consensus(SCHEMA, rows)["i0::gen_a"]["t"] == 2.2

    def test_a_stream_nobody_answered_about_is_absent(self):
        """
        Silence is not a clean verdict. Counting it as one would manufacture
        agreement with a judge that also found nothing.
        """
        rows = {"i0": {"a": value([mark("gen_a", 2.0)]),
                       "b": value(clean=["gen_a"])}}
        consensus = batch.human_consensus(SCHEMA, rows)
        assert "i0::gen_a" in consensus
        assert "i0::gen_b" not in consensus

    def test_the_earliest_mark_on_a_stream_is_the_one_that_counts(self):
        """
        The question is where the rollout *stops* making sense. A later mark on
        the same stream is a further failure, not a competing answer.
        """
        rows = {"i0": {"a": value([mark("gen_a", 5.0), mark("gen_a", 2.0)]),
                       "b": value([mark("gen_a", 2.1)])}}
        assert batch.human_consensus(SCHEMA, rows)["i0::gen_a"]["t"] == \
            pytest.approx(2.05)

    def test_a_single_annotator_still_produces_a_consensus(self):
        """
        The judge is scored against people, so one person's answer is a fine
        thing to be right or wrong about. The agreement report's two-annotator
        floor does not apply here.
        """
        rows = {"i0": {"only": value([mark("gen_a", 3.0)])}}
        assert batch.human_consensus(SCHEMA, rows)["i0::gen_a"]["t"] == 3.0

    def test_an_unparseable_value_is_skipped_not_guessed(self):
        rows = {"i0": {"a": "not json at all",
                       "b": value([mark("gen_a", 2.0)])}}
        assert batch.human_consensus(SCHEMA, rows)["i0::gen_a"]["t"] == 2.0

    def test_a_mark_with_no_usable_time_does_not_become_zero(self):
        rows = {"i0": {"a": value([{"stream": "gen_a", "t": None}]),
                       "b": value([mark("gen_a", 2.0)])}}
        entry = batch.human_consensus(SCHEMA, rows)["i0::gen_a"]
        assert entry["t"] == 2.0

    def test_several_streams_are_kept_apart(self):
        rows = {"i0": {"a": value([mark("gen_a", 2.0), mark("gen_b", 4.0)]),
                       "b": value([mark("gen_a", 2.2), mark("gen_b", 4.4)])}}
        consensus = batch.human_consensus(SCHEMA, rows)
        assert consensus["i0::gen_a"]["t"] == pytest.approx(2.1)
        assert consensus["i0::gen_b"]["t"] == pytest.approx(4.2)


class TestTheClientAndTheReaderAgreeOnFieldNames:
    """
    The mark's stream field is called ``stream`` in the annotation and
    ``stream_id`` in the panel manifest. Nothing enforced that, and a reader
    that guessed ``stream_id`` would find no marks at all — producing an empty
    denominator, a clean run, and a silently meaningless alignment number.
    """

    def _source(self):
        import pathlib

        return (pathlib.Path(__file__).resolve().parents[2]
                / "potato/static/rollout-eval.js").read_text(encoding="utf-8")

    def test_the_client_writes_the_key_the_reader_reads(self):
        source = self._source()
        assert "stream: this.selectedStream" in source, (
            "rollout-eval.js no longer writes a mark's stream as `stream`; "
            "iaa/rollouts.by_stream and rollouts/batch read that key")

    def test_the_reader_reads_that_key(self):
        from potato.server_utils.iaa import rollouts as rollout_iaa

        marks = [{"stream": "gen_a", "t": 1.0}]
        assert list(rollout_iaa.by_stream(marks)) == ["gen_a"]

    def test_a_mark_using_the_manifest_name_finds_nothing(self):
        """Shows the failure is silent, which is why the guard above exists."""
        from potato.server_utils.iaa import rollouts as rollout_iaa

        assert list(rollout_iaa.by_stream([{"stream_id": "gen_a", "t": 1.0}])) \
            == [""]


class TestRolloutSchemas:
    def test_finds_them_at_the_top_level(self):
        config = {"annotation_schemes": [
            {"name": "a", "annotation_type": "radio"},
            {"name": "b", "annotation_type": "rollout_evaluation"}]}
        assert [s["name"] for s in batch.rollout_schemas(config)] == ["b"]

    def test_finds_them_inside_phases(self):
        config = {"phases": {"annotation": {"annotation_schemes": [
            {"name": "c", "annotation_type": "rollout_evaluation"}]}}}
        assert [s["name"] for s in batch.rollout_schemas(config)] == ["c"]

    def test_none_configured(self):
        assert batch.rollout_schemas({}) == []


class TestPredictionStorage:
    def test_round_trip(self, tmp_path):
        config = {"output_annotation_dir": str(tmp_path)}
        assert batch.load_predictions(config) == {}
        batch.save_predictions(config, {"v1": {"i0::s::gen_a": {"t": 2.0}}})
        assert batch.load_predictions(config)["v1"]["i0::s::gen_a"]["t"] == 2.0

    def test_it_does_not_share_a_file_with_the_llm_judge(self, tmp_path):
        """
        A break-point prediction and a label prediction are different shapes;
        one file would make both readers defensive about the other's rows.
        """
        from potato.server_utils import judge_alignment

        config = {"output_annotation_dir": str(tmp_path)}
        assert batch.predictions_path(config) != \
            judge_alignment.predictions_path(config)

    def test_an_unreadable_file_is_empty_not_fatal(self, tmp_path):
        config = {"output_annotation_dir": str(tmp_path)}
        path = batch.predictions_path(config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        assert batch.load_predictions(config) == {}


class TestTheBatchRefusesRatherThanPretends:
    def test_no_vision_endpoint(self, monkeypatch):
        monkeypatch.setattr("potato.rollouts.routes._visual_endpoint",
                            lambda: None)
        result = batch.run_judge_batch({"annotation_schemes": []})
        assert result["judged"] == 0
        assert "vision" in result["error"]

    def test_no_rollout_schema(self, monkeypatch):
        monkeypatch.setattr("potato.rollouts.routes._visual_endpoint",
                            lambda: object())
        monkeypatch.setattr("potato.item_state_management.get_item_state_manager",
                            lambda: object())
        result = batch.run_judge_batch({"annotation_schemes": [
            {"name": "a", "annotation_type": "radio"}]})
        assert result["judged"] == 0
        assert "rollout_evaluation" in result["error"]

    def test_alignment_without_predictions_says_so(self, tmp_path):
        result = batch.alignment_report({"output_annotation_dir": str(tmp_path)})
        assert result["n_predictions"] == 0
        assert "batch" in result["error"]
