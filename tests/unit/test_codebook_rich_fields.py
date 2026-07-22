"""Structured codebook fields: storage, service edits + history, prompt
rendering, YAML/CLI seeding, and output-change review flagging."""

import json

import pytest

from potato.codebook import (
    Codebook,
    clear_change_listeners,
    create_code,
    update_code_fields,
    rename_code,
    review,
)
from potato.codebook import changelog, store
from potato.codebook.prompt import (
    render_codebook_section,
    render_from_codebook,
    has_rich_detail,
)
from potato.codebook.schema_bridge import apply_codebook_to_schemes
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


RICH = dict(
    definition="a violent public disturbance by a crowd",
    clarification="includes property destruction",
    negative_clarification="NOT a peaceful protest",
    positive_examples=[{"text": "protesters smashed shop windows",
                        "why": "shows violence"}],
    negative_examples=[{"text": "thousands marched peacefully",
                        "why": "non-violent, so a demonstration"}],
)


class TestStorage:
    def test_create_persists_rich_fields(self, td):
        # Reads go through the effective (decoded / lazy-upgraded) view —
        # the JSON list fields are stored as canonical JSON in TEXT columns
        # and come back as Python lists via Codebook.detail.
        c = create_code(td, project="p", name="riot", created_by="u",
                        details=RICH)
        d = Codebook.load(td, "p").detail(c["id"])
        for k, v in RICH.items():
            assert d[k] == v

    def test_blank_fields_normalise_to_none(self, td):
        c = create_code(td, project="p", name="riot", created_by="u",
                        details={"definition": "  ", "clarification": ""})
        got = store.get_code(td, c["id"])
        assert got["definition"] is None
        assert got["clarification"] is None

    def test_code_without_fields_unaffected(self, td):
        c = create_code(td, project="p", name="plain", created_by="u")
        got = store.get_code(td, c["id"])
        assert got["definition"] is None
        assert got["name"] == "plain"


class TestServiceUpdateAndHistory:
    def test_update_logs_per_field_and_bumps_revision(self, td):
        from potato.codebook import current_revision
        c = create_code(td, project="p", name="riot", created_by="u",
                        details={"definition": "old def"})
        rev_before = current_revision(td, "p")
        update_code_fields(
            td, c["id"], project="p", actor="bob",
            details={"definition": "new def",
                     "negative_clarification": "NOT a protest"})
        assert current_revision(td, "p") == rev_before + 1
        hist = changelog.code_history(td, "p", c["id"])
        ops = {h["op"] for h in hist}
        assert "create" in ops
        assert "edit_definition" in ops
        assert "edit_negative_clarification" in ops
        defn = next(h for h in hist if h["op"] == "edit_definition")
        assert defn["old_value"] == "old def"
        assert defn["new_value"] == "new def"

    def test_noop_update_does_not_churn_revision(self, td):
        from potato.codebook import current_revision
        c = create_code(td, project="p", name="riot", created_by="u",
                        details={"definition": "same"})
        rev = current_revision(td, "p")
        update_code_fields(td, c["id"], project="p",
                           details={"definition": "same"})
        assert current_revision(td, "p") == rev

    def test_create_is_logged(self, td):
        c = create_code(td, project="p", name="riot", created_by="alice")
        hist = changelog.code_history(td, "p", c["id"])
        assert any(h["op"] == "create" and h["actor"] == "alice"
                   for h in hist)


class TestReadModel:
    def test_detail_and_tree_expose_fields(self, td):
        c = create_code(td, project="p", name="riot", created_by="u",
                        details=RICH)
        cb = Codebook.load(td, "p")
        assert cb.detail(c["id"])["definition"] == RICH["definition"]
        node = cb.as_tree()[0]
        assert node["negative_clarification"] == RICH["negative_clarification"]


class TestPromptRendering:
    def test_renders_structured_block(self, td):
        create_code(td, project="p", name="riot", created_by="u",
                    details=RICH)
        out = render_codebook_section(td, "p")
        assert "## Codebook" in out
        assert "### riot" in out
        assert "Definition: a violent public disturbance" in out
        assert "Exclude: NOT a peaceful protest" in out
        assert '✓ Example: "protesters smashed shop windows" — shows violence' in out
        assert "✗ Looks like this code but is NOT:" in out
        # the anti-lexical-overlap guard is present
        assert "NOT from surface wording" in out

    def test_empty_without_rich_fields(self, td):
        create_code(td, project="p", name="plain", created_by="u")
        assert render_codebook_section(td, "p") == ""
        assert has_rich_detail(td, "p") is False

    def test_has_rich_detail_true(self, td):
        create_code(td, project="p", name="riot", created_by="u",
                    details={"definition": "x"})
        assert has_rich_detail(td, "p") is True


class TestDistillOptions:
    """Codebook -> prompt distill Options: show_examples / max_examples /
    include_rationale, all defaulting to today's always-show behavior."""

    def test_defaults_match_previous_always_show_behavior(self, td):
        create_code(td, project="p", name="riot", created_by="u",
                    details=RICH)
        assert render_codebook_section(td, "p") == \
            render_codebook_section(td, "p", options={})

    def test_show_examples_false_omits_examples_but_keeps_prose(self, td):
        from potato.codebook.prompt import RenderOptions

        create_code(td, project="p", name="riot", created_by="u",
                    details=RICH)
        out = render_codebook_section(
            td, "p", options=RenderOptions(show_examples=False))
        assert "Definition: a violent public disturbance" in out
        assert "Example" not in out

    def test_include_rationale_false_drops_why_suffix(self, td):
        from potato.codebook.prompt import RenderOptions

        create_code(td, project="p", name="riot", created_by="u",
                    details=RICH)
        out = render_codebook_section(
            td, "p", options=RenderOptions(include_rationale=False))
        assert '✓ Example: "protesters smashed shop windows"' in out
        assert "shows violence" not in out

    def test_max_examples_caps_rendered_count(self, td):
        from potato.codebook.prompt import RenderOptions

        details = dict(RICH, positive_examples=[
            {"text": "a", "why": ""}, {"text": "b", "why": ""},
            {"text": "c", "why": ""},
        ])
        create_code(td, project="p", name="riot", created_by="u",
                    details=details)
        out = render_codebook_section(
            td, "p", options=RenderOptions(max_examples=1))
        assert out.count("✓ Example:") == 1

    def test_dict_and_distill_config_both_accepted(self, td):
        from potato.solo_mode.config import DistillConfig

        create_code(td, project="p", name="riot", created_by="u",
                    details=RICH)
        via_dict = render_codebook_section(
            td, "p", options={"show_examples": False})
        via_config = render_codebook_section(
            td, "p", options=DistillConfig(show_examples=False))
        assert via_dict == via_config
        assert "Example" not in via_dict


class TestSummarization:
    def test_summarizes_only_when_over_threshold(self, td):
        from potato.codebook.prompt import RenderOptions

        long_def = " ".join(["word"] * 50)
        create_code(td, project="p", name="riot", created_by="u",
                    details={"definition": long_def})

        calls = []

        def fake_summarize(code_id, field, text):
            calls.append((code_id, field))
            return "short summary"

        out = render_codebook_section(
            td, "p", options=RenderOptions(summarize_above_tokens=5),
            summarize=fake_summarize)
        assert "Definition: short summary" in out
        assert len(calls) == 1

        # Below threshold -> summarizer is never invoked, full text kept.
        calls.clear()
        out2 = render_codebook_section(
            td, "p", options=RenderOptions(summarize_above_tokens=500),
            summarize=fake_summarize)
        assert long_def in out2
        assert calls == []

    def test_summarizer_module_caches_by_content_hash(self, td):
        from potato.codebook.summarizer import make_summarizer
        from potato.codebook import summary_cache

        calls = []

        class FakeEndpoint:
            def query(self, prompt):
                calls.append(prompt)
                return {"summary": "compressed"}

        summarize = make_summarizer(td, FakeEndpoint())
        text = "some long instruction text"
        first = summarize("c1", "definition", text)
        second = summarize("c1", "definition", text)
        assert first == second == "compressed"
        assert len(calls) == 1  # second call hit the cache

        import hashlib
        cached = summary_cache.get_cached(
            td, "c1", "definition",
            hashlib.sha256(text.encode()).hexdigest())
        assert cached == "compressed"

    def test_summarizer_falls_back_to_full_text_on_failure(self, td):
        from potato.codebook.summarizer import make_summarizer

        class BrokenEndpoint:
            def query(self, prompt):
                raise RuntimeError("boom")

        summarize = make_summarizer(td, BrokenEndpoint())
        text = "original text"
        assert summarize("c1", "definition", text) == text


class TestYamlSeeding:
    def test_bridge_seeds_rich_fields_and_renders_onto_scheme(self, td):
        cfg = {
            "task_dir": td, "annotation_task_name": "P",
            "annotation_schemes": [{
                "name": "s", "annotation_type": "multiselect",
                "codebook": True,
                "labels": [
                    {"name": "riot", **RICH},
                    "plainlabel",
                ],
            }],
        }
        apply_codebook_to_schemes(cfg)
        scheme = cfg["annotation_schemes"][0]
        assert scheme["labels"] == ["riot", "plainlabel"]
        # rendered block is attached for the ICL prompt builder
        assert "### riot" in scheme["codebook_prompt"]
        # and it actually landed in the DB
        d = Codebook.load(td, "P").detail(
            Codebook.load(td, "P").label_to_id()["riot"])
        assert d["definition"] == RICH["definition"]


class TestSoloLabelerInjection:
    def test_codebook_section_helper_injects_block(self, td):
        """The solo labeler transparently augments the user's prompt with
        the structured codebook block; plain projects get nothing."""
        from potato.solo_mode.llm_labeler import LLMLabelingThread

        create_code(td, project="P", name="riot", created_by="u",
                    details=RICH)
        cfg = {"task_dir": td, "annotation_task_name": "P"}
        thread = LLMLabelingThread(
            config=cfg, solo_config=None,
            prompt_getter=lambda: "label this",
            result_callback=lambda r: None)
        section = thread._codebook_section()
        assert "## Codebook" in section
        assert "### riot" in section
        # trailing separator so it slots cleanly into the prompt
        assert section.endswith("\n\n")

    def test_codebook_section_empty_for_plain_project(self, td):
        from potato.solo_mode.llm_labeler import LLMLabelingThread
        create_code(td, project="P", name="plain", created_by="u")
        cfg = {"task_dir": td, "annotation_task_name": "P"}
        thread = LLMLabelingThread(
            config=cfg, solo_config=None,
            prompt_getter=lambda: "label this",
            result_callback=lambda r: None)
        assert thread._codebook_section() == ""

    def test_summary_endpoint_never_touched_when_nothing_is_over_threshold(
        self, td,
    ):
        """Regression: building the summary endpoint used to happen
        unconditionally on every prompt build (default
        summarize_above_tokens=400 > 0), which for Ollama does a blocking
        health-check in the constructor — hanging the synchronous
        /llm-suggestion request path even though nothing here needed
        summarizing. It must now stay lazy: no field exceeds the
        threshold, so the endpoint is never resolved at all."""
        from potato.solo_mode.llm_labeler import LLMLabelingThread

        create_code(td, project="P", name="riot", created_by="u",
                    details=RICH)  # RICH's fields are short prose
        cfg = {"task_dir": td, "annotation_task_name": "P"}
        thread = LLMLabelingThread(
            config=cfg, solo_config=None,
            prompt_getter=lambda: "label this",
            result_callback=lambda r: None)

        def boom():
            raise AssertionError(
                "endpoint should not be resolved when nothing needs "
                "summarizing")
        thread._get_summary_endpoint = boom

        section = thread._codebook_section()
        assert "### riot" in section

    def test_summary_endpoint_failure_is_not_retried_every_call(self, td):
        """Once every candidate model has failed to construct, later
        prompt builds in the same thread must not re-attempt the
        (potentially blocking) connection again."""
        from potato.solo_mode.config import ModelConfig
        from potato.solo_mode.llm_labeler import LLMLabelingThread

        long_def = " ".join(["word"] * 500)  # over the 400-token default
        create_code(td, project="P", name="riot", created_by="u",
                    details={"definition": long_def})
        cfg = {"task_dir": td, "annotation_task_name": "P"}

        class FakeSoloConfig:
            revision_models = [ModelConfig(endpoint_type="ollama",
                                            model="unreachable")]
            labeling_models = []

        thread = LLMLabelingThread(
            config=cfg, solo_config=FakeSoloConfig(),
            prompt_getter=lambda: "label this",
            result_callback=lambda r: None)

        calls = []

        def failing_create(model_config):
            calls.append(model_config)
            raise RuntimeError("connection refused")
        thread.create_endpoint_from_model_config = failing_create

        thread._codebook_section()
        thread._codebook_section()
        thread._codebook_section()

        assert len(calls) == 1  # tried once, then cached as failed


def _make_legacy_code(td, project, name, *, pos=None, pos_why=None,
                      neg=None, neg_why=None):
    """Create a code, then write data ONLY into the pre-0006 singular
    example columns (new *_examples columns left NULL) to simulate a
    codebook migrated up from before the structured-fields change."""
    c = create_code(td, project=project, name=name, created_by="u")
    conn = store._db(td)
    conn.execute(
        "UPDATE codes SET positive_example=?, positive_example_why=?, "
        "negative_example=?, negative_example_why=? WHERE id=?",
        (pos, pos_why, neg, neg_why, c["id"]))
    conn.commit()
    return c


class TestStructuredFields:
    """list[str] exclusion_rules + list[{text,why}] examples: canonical
    JSON storage, no-op churn guard, lazy-upgrade, and prompt rendering."""

    def test_json_round_trip_trims_and_drops_blanks(self, td):
        c = create_code(td, project="p", name="riot", created_by="u",
                        details={
                            "exclusion_rules": ["  rule one  ", "rule two", ""],
                            "positive_examples": [
                                {"text": "x", "why": "y"},
                                {"text": "  z  "},          # why omitted
                                {"text": "", "why": "drop me"}]})  # no text
        d = Codebook.load(td, "p").detail(c["id"])
        assert d["exclusion_rules"] == ["rule one", "rule two"]
        assert d["positive_examples"] == [
            {"text": "x", "why": "y"}, {"text": "z", "why": ""}]
        # Stored as canonical JSON (sorted object keys) in a TEXT column.
        raw = store.get_code(td, c["id"])
        assert raw["positive_examples"] == (
            '[{"text": "x", "why": "y"}, {"text": "z", "why": ""}]')

    def test_empty_list_normalises_to_none(self, td):
        c = create_code(td, project="p", name="riot", created_by="u",
                        details={"exclusion_rules": [],
                                 "negative_examples": [{"text": "  "}]})
        raw = store.get_code(td, c["id"])
        assert raw["exclusion_rules"] is None
        assert raw["negative_examples"] is None
        assert Codebook.load(td, "p").detail(c["id"])["exclusion_rules"] == []

    def test_json_field_noop_does_not_churn(self, td):
        from potato.codebook import current_revision
        c = create_code(td, project="p", name="riot", created_by="u")
        update_code_fields(td, c["id"], project="p",
                           details={"exclusion_rules": ["a", "b"]})
        rev = current_revision(td, "p")
        # Equivalent value (same canonical JSON) -> no edit, no churn.
        update_code_fields(td, c["id"], project="p",
                           details={"exclusion_rules": ["a", "b"]})
        assert current_revision(td, "p") == rev
        edits = [h for h in changelog.code_history(td, "p", c["id"])
                 if h["op"] == "edit_exclusion_rules"]
        assert len(edits) == 1

    def test_edit_exclusion_rules_logs_canonical_with_code_id(self, td):
        c = create_code(td, project="p", name="riot", created_by="u")
        update_code_fields(
            td, c["id"], project="p",
            details={"exclusion_rules": ["text merely mentions a riot"]})
        row = next(h for h in changelog.code_history(td, "p", c["id"])
                   if h["op"] == "edit_exclusion_rules")
        assert row["code_id"] == c["id"]              # resolvable for the sweep
        assert json.loads(row["new_value"]) == ["text merely mentions a riot"]

    def test_renders_multi_example_and_do_not_apply_block(self, td):
        create_code(td, project="p", name="riot", created_by="u", details={
            "definition": "violent crowd",
            "positive_examples": [
                {"text": "smashed windows", "why": "violence"},
                {"text": "set cars on fire", "why": "destruction"}],
            "negative_examples": [{"text": "peaceful march",
                                   "why": "non-violent"}],
            "exclusion_rules": ["the text only mentions the word riot",
                                "it describes a sports celebration"]})
        out = render_codebook_section(td, "p")
        assert '✓ Example: "smashed windows" — violence' in out
        assert '✓ Example: "set cars on fire" — destruction' in out
        assert ('✗ Looks like this code but is NOT: "peaceful march"'
                ' — non-violent') in out
        assert "Do NOT apply when:" in out
        assert "  • the text only mentions the word riot" in out
        assert "  • it describes a sports celebration" in out
        # guard now name-checks the do-not-apply rules
        assert "Do NOT apply when" in out

    def test_legacy_singular_code_renders_identically(self, td):
        """A pre-0006 code (singular columns only) renders byte-identically
        to a new-style code carrying the same example as a list."""
        create_code(td, project="new", name="riot", created_by="u", details={
            "positive_examples": [{"text": "protesters smashed shop windows",
                                   "why": "shows violence"}]})
        _make_legacy_code(td, "leg", "riot",
                          pos="protesters smashed shop windows",
                          pos_why="shows violence")
        assert render_codebook_section(td, "new") == \
            render_codebook_section(td, "leg")


class TestReviewFlagging:
    def test_significance_policy(self):
        assert review.significance("a", "b") == "high"
        assert review.significance(["a", "b"], ["a"]) == "high"
        assert review.significance("a", "a") is None
        assert review.significance("a", "a", 0.9, 0.5) == "medium"
        assert review.significance("a", "a", 0.9, 0.8) is None

    def test_evaluate_records_only_significant(self, td):
        flags = review.evaluate_relabels(
            td, project="p", change_id="c1", relabels=[
                {"instance_id": "i1", "schema_name": "s",
                 "old_label": "riot", "new_label": "protest"},
                {"instance_id": "i2", "schema_name": "s",
                 "old_label": "riot", "new_label": "riot"},
            ])
        assert len(flags) == 1
        assert flags[0]["instance_id"] == "i1"
        assert review.open_count(td, "p") == 1

    def test_resolve_flag(self, td):
        flags = review.evaluate_relabels(
            td, project="p", change_id=None, relabels=[
                {"instance_id": "i1", "old_label": "a", "new_label": "b"}])
        fid = flags[0]["id"]
        assert review.resolve_flag(
            td, fid, status="dismissed", reviewed_by="admin") is True
        # second resolve is a no-op (already resolved)
        assert review.resolve_flag(
            td, fid, status="reviewed", reviewed_by="admin") is False
        assert review.open_count(td, "p") == 0

    def test_resolve_rejects_bad_status(self, td):
        flags = review.evaluate_relabels(
            td, project="p", change_id=None, relabels=[
                {"instance_id": "i1", "old_label": "a", "new_label": "b"}])
        with pytest.raises(ValueError):
            review.resolve_flag(td, flags[0]["id"], status="bogus",
                                reviewed_by="admin")
