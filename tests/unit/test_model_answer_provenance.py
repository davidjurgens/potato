"""A model's answer is distinguishable from a person's, from both ends.

Two features, opposite halves of one missing fact.

`ai_support` recorded what was ACCEPTED and never what was SAVED.
`final_annotation` is documented as "What the user ultimately annotated for
this schema", was declared, written to dict and read back -- and never
assigned. It read `null` on a record where the annotator accepted a suggestion
and saved it unchanged. `suggestion_accepted` records the click, so an
annotator who accepts and then changes their mind before saving leaves a record
saying they accepted it and nothing saying what they submitted. The acceptance
rate you can compute from that is the one at the moment of the click, not the
one that survived into the dataset, and the second is the number a paper
reports.

`pre_annotation` recorded what was SAVED and never that it came from a model.
An "accepter" who changed nothing stored exactly the prediction file, in a
record of identical shape to an annotator who worked it out. So a study using
either feature could not report its own model-acceptance rate from its own
data.

Two smaller findings in the same area: an `accept` with no preceding `request`
was dropped and answered `{"status": "ok"}`, identical to what a complete
sequence gets; and `pre_annotation.predictions_file` was accepted, published in
the JSON schema, and read by nothing -- while its sibling `field` worked, so an
author who set it and saw no pre-filled answers had no reason to suspect the
key.
"""

import json

import pytest

from potato.interaction_tracking import AIUsageEvent, BehavioralData


def event(schema="sentiment", accepted=None):
    return AIUsageEvent(request_timestamp=1.0, schema_name=schema,
                        response_timestamp=2.0, suggestion_accepted=accepted)


class TestFinalAnnotationIsRecorded:

    def test_what_was_saved_is_stamped(self):
        bd = BehavioralData(instance_id="i1")
        bd.ai_usage = [event(accepted="positive")]
        assert bd.record_final_annotations({"sentiment": "positive"}) == 1
        assert bd.ai_usage[0].final_annotation == "positive"

    def test_an_overridden_suggestion_is_visible(self):
        """The case the field exists for: accepted, then changed before save."""
        bd = BehavioralData(instance_id="i1")
        bd.ai_usage = [event(accepted="positive")]
        bd.record_final_annotations({"sentiment": "negative"})
        assert bd.ai_usage[0].suggestion_accepted == "positive"
        assert bd.ai_usage[0].final_annotation == "negative", (
            "the record said the suggestion was accepted and nothing said "
            "what was actually submitted")

    def test_other_schemas_are_left_alone(self):
        bd = BehavioralData(instance_id="i1")
        bd.ai_usage = [event(schema="sentiment"), event(schema="topic")]
        bd.record_final_annotations({"sentiment": "positive"})
        assert bd.ai_usage[1].final_annotation is None

    def test_a_schema_with_no_ai_event_stamps_nothing(self):
        bd = BehavioralData(instance_id="i1")
        bd.ai_usage = [event(schema="sentiment")]
        assert bd.record_final_annotations({"unrelated": "x"}) == 0

    def test_it_survives_serialization(self):
        bd = BehavioralData(instance_id="i1")
        bd.ai_usage = [event(accepted="positive")]
        bd.record_final_annotations({"sentiment": "negative"})
        restored = BehavioralData.from_dict(json.loads(json.dumps(bd.to_dict())))
        assert restored.ai_usage[0].final_annotation == "negative"


class TestSeedProvenanceIsRecorded:

    def test_the_seeded_value_is_noted(self):
        bd = BehavioralData(instance_id="i1")
        bd.record_pre_annotation_seeds({"sentiment": "positive"})
        assert bd.pre_annotation_seeds == {"sentiment": "positive"}

    def test_an_accepted_seed_is_now_distinguishable(self):
        """The measurement that was impossible: same stored answer, different
        provenance."""
        accepter = BehavioralData(instance_id="i1")
        accepter.record_pre_annotation_seeds({"sentiment": "positive"})
        independent = BehavioralData(instance_id="i1")
        assert accepter.pre_annotation_seeds != independent.pre_annotation_seeds

    def test_a_later_call_does_not_overwrite_the_original(self):
        """The point is comparing suggested with submitted, which needs both."""
        bd = BehavioralData(instance_id="i1")
        bd.record_pre_annotation_seeds({"sentiment": "positive"})
        bd.record_pre_annotation_seeds({"sentiment": "negative"})
        assert bd.pre_annotation_seeds["sentiment"] == "positive"

    def test_it_survives_serialization(self):
        bd = BehavioralData(instance_id="i1")
        bd.record_pre_annotation_seeds({"sentiment": "positive"})
        restored = BehavioralData.from_dict(json.loads(json.dumps(bd.to_dict())))
        assert restored.pre_annotation_seeds == {"sentiment": "positive"}

    def test_an_unseeded_instance_carries_an_empty_map(self):
        assert BehavioralData(instance_id="i1").to_dict()[
            "pre_annotation_seeds"] == {}


class TestAnOrphanAcceptIsRecorded:

    def test_the_event_is_marked_reconstructed(self):
        e = AIUsageEvent(request_timestamp=1.0, schema_name="s",
                         suggestion_accepted="positive")
        e.reconstructed = True
        assert e.to_dict()["reconstructed"] is True

    def test_it_survives_a_round_trip(self):
        e = AIUsageEvent(request_timestamp=1.0, schema_name="s",
                         suggestion_accepted="positive", reconstructed=True)
        assert AIUsageEvent.from_dict(e.to_dict()).reconstructed is True

    def test_a_normal_event_is_not_marked(self):
        assert event().to_dict()["reconstructed"] is False

    def test_the_route_records_rather_than_drops(self):
        """Driven through the handler with a behavioral store that has no open
        request for the schema."""
        import flask

        from potato import routes

        app = flask.Flask(__name__)
        app.secret_key = "test"
        store = {}
        handler = getattr(routes.track_ai_usage, "__wrapped__",
                          routes.track_ai_usage)

        class State:
            instance_id_to_behavioral_data = store

        import pytest as _pytest

        monkey = _pytest.MonkeyPatch()
        try:
            monkey.setattr(routes, "get_user_state", lambda _u: State(),
                           raising=False)
            with app.test_request_context(
                    json={"instance_id": "i1", "schema_name": "sentiment",
                          "event_type": "accept",
                          "accepted_value": "positive"}):
                flask.session["username"] = "u1"
                response = handler()
        finally:
            monkey.undo()

        body = response[0] if isinstance(response, tuple) else response
        payload = body.get_json()
        assert payload.get("reconstructed") is True, (
            "an accept with no open request was dropped and answered ok, so "
            "the annotator appears never to have used the assistant")
        assert store["i1"].ai_usage, "nothing was written"
        assert store["i1"].ai_usage[0].suggestion_accepted == "positive"
        assert store["i1"].ai_usage[0].response_timestamp is None, (
            "a response time that was never observed must not be invented")


class TestPredictionsFileIsRead:

    def _manager(self, tmp_path, payload, name="preds.json", field="predictions"):
        from potato.quality_control import QualityControlManager

        (tmp_path / name).write_text(json.dumps(payload))
        config = {"pre_annotation": {"enabled": True, "field": field,
                                     "predictions_file": name}}
        return QualityControlManager(config, str(tmp_path))

    def test_a_mapping_of_id_to_predictions_is_loaded(self, tmp_path):
        mgr = self._manager(tmp_path, {"i00": {"sentiment": "positive"}})
        assert mgr.extract_pre_annotations("i00", {"id": "i00"}) == {
            "sentiment": "positive"}, (
            "the key was accepted, published in the JSON schema, and read by "
            "nothing, while its sibling `field` worked")

    def test_a_list_of_records_is_loaded(self, tmp_path):
        mgr = self._manager(
            tmp_path, [{"id": "i00", "predictions": {"sentiment": "negative"}}])
        assert mgr.extract_pre_annotations("i00", {"id": "i00"}) == {
            "sentiment": "negative"}

    def test_the_configured_field_name_is_used_in_records(self, tmp_path):
        mgr = self._manager(
            tmp_path, [{"id": "i00", "model_out": {"sentiment": "positive"}}],
            field="model_out")
        assert mgr.extract_pre_annotations("i00", {"id": "i00"}) == {
            "sentiment": "positive"}

    def test_an_item_carrying_its_own_field_still_wins(self, tmp_path):
        """The working route must not be overridden by the one being added."""
        mgr = self._manager(tmp_path, {"i00": {"sentiment": "fromfile"}})
        assert mgr.extract_pre_annotations(
            "i00", {"id": "i00", "predictions": {"sentiment": "fromitem"}}) == {
            "sentiment": "fromitem"}

    def test_an_unlisted_item_gets_nothing(self, tmp_path):
        mgr = self._manager(tmp_path, {"i00": {"sentiment": "positive"}})
        assert mgr.extract_pre_annotations("i99", {"id": "i99"}) is None

    def test_a_missing_file_warns_rather_than_raising(self, tmp_path, caplog):
        from potato.quality_control import QualityControlManager

        import logging

        with caplog.at_level(logging.WARNING):
            mgr = QualityControlManager(
                {"pre_annotation": {"enabled": True,
                                    "predictions_file": "absent.json"}},
                str(tmp_path))
        assert mgr.file_pre_annotations == {}
        assert "absent.json" in " ".join(r.getMessage() for r in caplog.records)

    def test_an_unusable_file_says_what_was_expected(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            mgr = self._manager(tmp_path, ["not", "records"])
        assert mgr.file_pre_annotations == {}
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "item_id" in joined or "id" in joined
