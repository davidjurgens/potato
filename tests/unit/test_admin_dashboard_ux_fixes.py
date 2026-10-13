"""
Admin-dashboard fixes from the 2026-10-08 UI/UX audit.

Each class pins one behaviour that was wrong before:

* the dashboard linked to none of the analysis pages;
* the login page named ``admin_api_key.txt`` even when the key was set inline;
* the overview had no agreement number at all;
* annotators whose annotations were imported without an interaction log were
  scored as low-interaction and flagged as suspicious;
* "Most Frequent Label" pooled every schema into one column.
"""

from types import SimpleNamespace

import pytest

from potato.item_state_management import Label


class TestAnalysisLinks:
    """Each analysis link appears exactly when its route would work."""

    def _links(self, monkeypatch, cfg):
        import potato.routes as routes
        monkeypatch.setattr(routes, "config", cfg)
        return {link["href"] for link in routes._admin_analysis_links()}

    def test_minimal_config_links_only_agreement(self, monkeypatch):
        hrefs = self._links(monkeypatch, {"annotation_schemes": [
            {"annotation_type": "textbox", "name": "notes"}]})
        assert hrefs == {"/admin/iaa"}

    def test_adjudication_link_follows_its_flag(self, monkeypatch):
        on = self._links(monkeypatch, {"adjudication": {"enabled": True}})
        off = self._links(monkeypatch, {"adjudication": {"enabled": False}})
        assert "/adjudicate" in on
        assert "/adjudicate" not in off

    def test_feature_pages_follow_their_flags(self, monkeypatch):
        hrefs = self._links(monkeypatch, {
            "review_workflow": {"enabled": True},
            "triage": {"enabled": True},
            "judge_alignment": {"enabled": True},
        })
        assert {"/admin/review", "/admin/triage-queue",
                "/admin/judge-alignment"} <= hrefs

    def test_integrity_needs_a_categorical_schema(self, monkeypatch):
        with_radio = self._links(monkeypatch, {"annotation_schemes": [
            {"annotation_type": "radio", "name": "s", "labels": ["a", "b"]}]})
        text_only = self._links(monkeypatch, {"annotation_schemes": [
            {"annotation_type": "textbox", "name": "t"}]})
        assert "/admin/annotation-integrity" in with_radio
        assert "/admin/annotation-integrity" not in text_only


class TestAdminKeySource:
    def test_inline_config_wins(self, monkeypatch):
        from potato.server_utils.admin_key import admin_api_key_source
        monkeypatch.setenv("POTATO_ADMIN_API_KEY", "from-env")
        assert admin_api_key_source({"admin_api_key": "inline"}) == "config"

    def test_environment_next(self, monkeypatch):
        from potato.server_utils.admin_key import admin_api_key_source
        monkeypatch.setenv("POTATO_ADMIN_API_KEY", "from-env")
        assert admin_api_key_source({}) == "env"

    def test_generated_file_last(self, monkeypatch):
        from potato.server_utils.admin_key import admin_api_key_source
        monkeypatch.delenv("POTATO_ADMIN_API_KEY", raising=False)
        assert admin_api_key_source({}) == "file"


class TestAgreementHeadlines:
    """The overview's one-number-per-schema summary."""

    def test_prefers_alpha_over_pairwise_kappa(self):
        from potato.server_utils.iaa.presentation import headlines
        report = {"schemas": {"sentiment": {
            "annotation_type": "radio", "kind": "nominal",
            "metrics": {"percent_agreement": 0.4, "cohen_kappa": -0.13,
                        "fleiss_kappa": -0.14, "alpha_nominal": -0.098,
                        "n_items": 8, "n_annotators": 3}}}}
        [row] = headlines(report)
        assert row["metric"] == "alpha_nominal"
        assert row["value"] == pytest.approx(-0.098)
        assert row["band"] == "weak"
        assert (row["n_items"], row["n_annotators"]) == (8, 3)

    def test_never_leads_with_raw_percent_agreement(self):
        from potato.server_utils.iaa.presentation import headlines
        report = {"schemas": {"s": {"annotation_type": "radio", "kind": "nominal",
                                    "metrics": {"percent_agreement": 0.9}}}}
        [row] = headlines(report)
        assert row["metric"] is None

    def test_schema_without_a_metric_keeps_its_note(self):
        from potato.server_utils.iaa.presentation import headlines
        report = {"schemas": {"s": {"annotation_type": "radio", "kind": "nominal",
                                    "metrics": {"note": "fewer than two annotators"}}}}
        [row] = headlines(report)
        assert row["metric"] is None
        assert row["note"] == "fewer than two annotators"


class _StubUSM:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_user_state(self, username):
        return self.mapping.get(username)


class TestUntrackedInteractions:
    """Imported annotations have changes but no interaction log."""

    def _run(self, monkeypatch, states):
        from potato.admin import AdminDashboard
        dashboard = AdminDashboard()
        monkeypatch.setattr(dashboard, "check_admin_access", lambda: True)
        monkeypatch.setattr("potato.admin.get_user_state_manager", lambda: _StubUSM(states))
        monkeypatch.setattr("potato.admin.get_users", lambda: list(states))
        monkeypatch.setattr(dashboard, "get_writing_process_data", lambda: {})
        monkeypatch.setattr(dashboard, "get_annotation_process_data", lambda: {})
        return dashboard.get_behavioral_analytics_data()

    def test_seeded_user_is_not_scored_low_interaction(self, monkeypatch):
        from potato.interaction_tracking import BehavioralData
        seeded = {}
        for i in range(4):
            bd = BehavioralData(instance_id=f"item_{i}")
            bd.total_time_ms = 30000
            bd.annotation_changes = [SimpleNamespace(source="user")]
            bd.scroll_depth_max = 0
            seeded[f"item_{i}"] = bd
        result = self._run(monkeypatch, {
            "seeded": SimpleNamespace(instance_id_to_behavioral_data=seeded)})

        assert result["aggregate_stats"]["instances_with_interaction_log"] == 0
        [user] = result["users"]
        assert user["instances_with_interaction_log"] == 0
        assert user["low_interaction_rate"] is None
        assert user["no_scroll_rate"] is None
        # Only the no-change rate is known, and every instance had a change.
        assert user["suspicion_score"] == 0.0
        assert user["quality_flag"] == "OK"

    def test_dict_record_without_the_field_is_unknown(self, monkeypatch):
        result = self._run(monkeypatch, {"legacy": SimpleNamespace(
            instance_id_to_behavioral_data={"item_0": {
                "total_time_ms": 45000, "annotation_changes": [{"source": "user"}, {"source": "user"}]}})})
        assert result["aggregate_stats"]["instances_with_interaction_log"] == 0

    def test_tracked_user_with_few_interactions_still_counts(self, monkeypatch):
        """A real low-effort annotator must still be caught."""
        from potato.interaction_tracking import BehavioralData
        bd = BehavioralData(instance_id="item_0")
        bd.total_time_ms = 2000
        bd.interactions = [{"event_type": "click"}]
        bd.annotation_changes = [SimpleNamespace(source="user")]
        result = self._run(monkeypatch, {
            "tracked": SimpleNamespace(instance_id_to_behavioral_data={"item_0": bd})})
        [user] = result["users"]
        assert user["instances_with_interaction_log"] == 1
        assert user["low_interaction_rate"] == 1.0


class TestLabelSummaryBySchema:
    def test_keeps_each_answer_with_its_question(self):
        from potato.admin import AdminDashboard
        by_schema = {}
        for labels in (
            {Label("sentiment", "positive"): True, Label("topics", "food"): True},
            {Label("sentiment", "positive"): True, Label("topics", "service"): True,
             Label("topics", "food"): True},
            {Label("sentiment", "negative"): True},
        ):
            AdminDashboard._collect_labels_by_schema(labels, by_schema)
        summary = AdminDashboard._label_summary_by_schema(by_schema)
        assert summary == [
            {"schema": "sentiment", "label": "positive", "count": 2, "total": 3},
            {"schema": "topics", "label": "food", "count": 2, "total": 3},
        ]
