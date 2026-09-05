"""Regressions for the audit-14 findings.

Each test names the finding it guards and fails on the behaviour that was
reported, not on an approximation of it.
"""

import json
import os

import pytest


# --------------------------------------------------------------- finding 1 --
# Span offsets are code points, not UTF-16 code units.

class TestSpanOffsetsAreCodePoints:
    """The JS conversion helpers, checked against Python's own indexing."""

    @staticmethod
    def _helpers():
        """The helper block from span-core.js, evaluated as a Python analogue.

        The JS itself is exercised by the browser tests; what matters here is
        that the *contract* holds -- a converted offset slices in Python to the
        text the annotator selected. The specimen offsets are the ones the
        audit measured in Chromium.
        """
        path = os.path.join("potato", "static", "span-core.js")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_conversion_helpers_are_present(self):
        source = self._helpers()
        for name in ("spanUtf16ToCodePoint", "spanCodePointToUtf16",
                     "spanCodePointLength", "spanSliceByCodePoints"):
            assert f"function {name}(" in source, f"{name} is missing"

    def test_offsets_leave_the_dom_as_code_points(self):
        source = self._helpers()
        assert "spanUtf16ToCodePoint(basis, absoluteStart)" in source, (
            "getOffsetsFromSelection must convert before returning")
        assert "start = spanCodePointToUtf16(offsetBasis, start)" in source, (
            "getPositionsFromOffsets must convert on the way in")

    def test_the_reported_specimen_now_slices_correctly(self):
        """W01's three spans, at the offsets Chromium produced."""
        text = ("\U0001F525\U0001F525 Evacuation order for Ridge Road issued "
                "at 14:20. Ridge Road is closed. Stay off Ridge Road.")
        # UTF-16 offsets as measured in the browser -> code points -> slice.
        def utf16_to_cp(s, idx):
            return len(s.encode("utf-16-le")[:idx * 2].decode("utf-16-le"))

        assert utf16_to_cp(text, 95) - utf16_to_cp(text, 81) == 14
        assert text[utf16_to_cp(text, 81):utf16_to_cp(text, 95)] == "off Ridge Road"
        assert text[utf16_to_cp(text, 26):utf16_to_cp(text, 39)] == "Ridge Road is"
        # And the end offset no longer runs past the string.
        assert utf16_to_cp(text, 95) <= len(text)


# --------------------------------------------------------------- finding 2 --
# The judge is sent the item, not the instance id.

class TestJudgeGetsTheItem:
    def test_get_text_prefers_the_configured_text_key(self):
        from potato.item_state_management import (
            Item, set_configured_text_key, get_configured_text_key)
        previous = get_configured_text_key()
        try:
            # Ordered so the id is the first string value, as a loader writes it.
            item = Item("P08", {"id": "P08", "review": "The novelty claim cannot stand."})
            set_configured_text_key(None)
            assert item.get_text() == "P08", "precondition: the old guess"
            set_configured_text_key("review")
            assert item.get_text() == "The novelty claim cannot stand."
        finally:
            set_configured_text_key(previous)

    def test_configured_key_is_published_by_the_manager(self):
        from potato.item_state_management import (
            ItemStateManager, get_configured_text_key, set_configured_text_key)
        previous = get_configured_text_key()
        try:
            ItemStateManager({"item_properties": {"text_key": "review"}})
            assert get_configured_text_key() == "review"
        finally:
            set_configured_text_key(previous)

    def test_judge_refuses_an_item_that_is_just_its_id(self):
        from potato.ai.judge import JudgeService

        service = JudgeService({})
        service._get_endpoint = lambda: object()   # would otherwise be None
        assert service.judge_instance("P08", {"name": "rec"}, "P08") is None
        assert service.judge_instance("P08", {"name": "rec"}, "   ") is None

    def test_judge_still_judges_a_genuinely_short_item(self):
        """A one-word item is legitimate; only empty-or-the-id is refused."""
        from potato.ai.judge import JudgeService

        service = JudgeService({})
        calls = []

        class _Endpoint:
            model = "m"

            def query(self, prompt, schema=None):
                calls.append(prompt)
                return json.dumps({"label": "yes", "confidence": 0.5,
                                   "reasoning": "r"})

        service._get_endpoint = lambda: _Endpoint()
        result = service.judge_instance("W08", {"name": "s", "labels": ["yes", "no"]}, "!")
        assert calls, "a one-character item must still reach the model"
        assert result is not None


# --------------------------------------------------------------- finding 3 --
# A refused save is an HTTP error, and the page says so.

class TestFailedSaveIsVisible:
    def test_updateinstance_refusals_carry_http_status(self):
        with open("potato/routes.py", encoding="utf-8") as f:
            source = f.read()
        for message, status in (
            ('"message": "No active session"}), 401', 401),
            ('"message": "Missing instance_id"}), 400', 400),
            ('"message": "Instance not assigned to user"}), 403', 403),
            ('"message": "User state not found"}), 401', 401),
        ):
            assert message in source, f"a refusal still answers 200: {message}"

    def test_the_page_reads_the_body_as_well_as_the_status(self):
        with open("potato/static/annotation.js", encoding="utf-8") as f:
            source = f.read()
        assert "result.status === 'error'" in source
        assert "function reportSaveRefused(" in source
        # A lost session has to interrupt: retrying cannot fix it.
        assert "httpStatus === 401" in source


class TestSessionGate:
    def test_the_allow_list_does_not_match_every_path(self):
        from potato.flask_server import (
            _UNAUTHENTICATED_PATHS, _UNAUTHENTICATED_PREFIXES)
        assert "/" in _UNAUTHENTICATED_PATHS
        assert not any(p == "/" for p in _UNAUTHENTICATED_PREFIXES), (
            "'/' as a prefix makes startswith() true for every path")
        assert "/annotate".startswith(_UNAUTHENTICATED_PREFIXES) is False

    def test_the_default_timeout_is_not_one_minute(self):
        from potato.flask_server import DEFAULT_SESSION_TIMEOUT_MINUTES
        assert DEFAULT_SESSION_TIMEOUT_MINUTES >= 60


# --------------------------------------------------------------- finding 4 --
# MCP submit_annotation writes typed objects.

class TestMcpSubmitAnnotation:
    def test_it_uses_the_typed_accessors(self):
        with open("potato/mcp_server/routes.py", encoding="utf-8") as f:
            source = f.read()
        assert "state.add_label_annotation(" in source
        assert "state.add_span_annotation(" in source
        assert "state.set_annotation(\n        instance_id,\n        annotations," not in source

    def test_the_audit_log_records_outcomes(self):
        with open("potato/mcp_server/routes.py", encoding="utf-8") as f:
            source = f.read()
        assert 'audit("error"' in source
        assert 'audit("refused"' in source


# --------------------------------------------------------------- finding 5 --
# Live MCP tools publish a real argument schema.

class TestMcpToolSchemas:
    def test_every_live_tool_publishes_its_parameters(self):
        from potato.mcp_server.live_tools import describe_tools
        described = {t["name"]: t for t in describe_tools()}
        assert "parameters" in described["get_item"]
        assert [p["name"] for p in described["get_item"]["parameters"]] == ["instance_id"]
        assert described["get_item"]["parameters"][0]["required"] is True
        limits = {p["name"] for p in described["list_items"]["parameters"]}
        assert limits == {"limit", "offset"}
        assign = {p["name"] for p in described["assign_items"]["parameters"]}
        assert "max_instances" in assign and "instance_ids" not in assign

    def test_the_forwarder_signature_matches_the_declaration(self):
        pytest.importorskip("mcp")
        import asyncio
        from mcp.server.fastmcp import FastMCP
        from potato.mcp_server.connect import PotatoClient, _register_forwarder
        from potato.mcp_server.live_tools import describe_tools

        server = FastMCP("t")
        client = PotatoClient("http://x", "tok")
        for entry in describe_tools():
            _register_forwarder(server, client, entry)
        tools = asyncio.new_event_loop().run_until_complete(server.list_tools())
        by_name = {t.name: t for t in tools}
        props = by_name["live_get_item"].inputSchema["properties"]
        assert "instance_id" in props and "arguments" not in props
        assert by_name["live_get_item"].inputSchema["required"] == ["instance_id"]

    def test_an_older_instance_still_bridges(self):
        """No `parameters` key means an unupgraded server, not a tool with none."""
        pytest.importorskip("mcp")
        import asyncio
        from mcp.server.fastmcp import FastMCP
        from potato.mcp_server.connect import PotatoClient, _register_forwarder

        server = FastMCP("t")
        _register_forwarder(server, PotatoClient("http://x", "tok"),
                            {"name": "get_item", "summary": "s"})
        tool = asyncio.new_event_loop().run_until_complete(server.list_tools())[0]
        assert "arguments" in tool.inputSchema["properties"]
        assert "nested object" in tool.description


# -------------------------------------------------------------- finding 11 --
class TestMcpAdminGate:
    def test_the_gate_honours_what_the_mcp_gate_granted(self):
        from potato.server_utils.rbac import (
            grant_mcp_permissions, mcp_granted_permissions)
        # Outside a request context this is empty and never raises.
        assert mcp_granted_permissions() == frozenset()
        grant_mcp_permissions({"view_admin_dashboard"})   # no app context: no-op
        assert mcp_granted_permissions() == frozenset()

    def test_check_consults_the_mcp_grant(self):
        with open("potato/server_utils/rbac.py", encoding="utf-8") as f:
            source = f.read()
        assert "if permission in mcp_granted_permissions():" in source


# ------------------------------------------------------------ findings 6/16 --
class TestCoreferenceChains:
    def test_the_entity_type_is_not_the_first_one_in_the_list(self):
        with open("potato/static/coreference-manager.js", encoding="utf-8") as f:
            source = f.read()
        assert "_entityTypeForSelection()" in source
        assert "entityType = checkedRadio ? checkedRadio.value : this.entityTypes[0];" not in source

    def test_mentions_are_looked_up_by_the_attribute_that_exists(self):
        with open("potato/static/coreference-manager.js", encoding="utf-8") as f:
            source = f.read()
        assert "_findSpanElement(spanId)" in source
        assert "data-annotation-id" in source


# ---------------------------------------------------------- findings 7 and 8 --
class TestSpanAndLikertOptions:
    def test_displaying_score_does_not_double_the_label(self):
        from potato.server_utils.schemas.span import generate_span_layout
        html, _ = generate_span_layout({
            "name": "entities", "description": "d",
            "labels": ["Defect", "Injury"], "displaying_score": True})
        assert "Defect.Defect" not in html
        assert "1. Defect" in html and "2. Injury" in html

    def test_bad_text_label_accepts_a_plain_string(self):
        from potato.server_utils.schemas.span import generate_span_layout
        html, _ = generate_span_layout({
            "name": "e", "description": "d", "labels": ["A"],
            "bad_text_label": "Nothing quotable"})
        assert "Nothing quotable" in html

    def test_bad_text_label_still_accepts_the_nested_form(self):
        from potato.server_utils.schemas.span import generate_span_layout
        html, _ = generate_span_layout({
            "name": "e", "description": "d", "labels": ["A"],
            "bad_text_label": {"label_content": "Nothing quotable"}})
        assert "Nothing quotable" in html

    def test_a_labelled_likert_honours_both_options(self):
        from potato.server_utils.schemas.likert import generate_likert_layout
        html, _ = generate_likert_layout({
            "name": "q", "description": "d", "size": 3,
            "min_label": "lo", "max_label": "hi",
            "labels": ["Disagree", "Neutral", "Agree"],
            "displaying_score": True, "bad_text_label": "Unreadable"})
        assert "Unreadable" in html
        assert "1. Disagree" in html

    def test_the_original_scheme_is_not_mutated(self):
        from potato.server_utils.schemas.likert import generate_likert_layout
        scheme = {"name": "q", "description": "d", "size": 2,
                  "min_label": "lo", "max_label": "hi",
                  "labels": ["Disagree", "Agree"],
                  "displaying_score": True, "bad_text_label": "Unreadable"}
        generate_likert_layout(scheme)
        assert scheme["labels"] == ["Disagree", "Agree"]


# --------------------------------------------------------------- finding 9 --
class TestUiLanguageDefault:
    def test_en_is_a_known_language(self):
        from potato.server_utils.i18n import available_language_codes, load_catalog
        assert "en" in available_language_codes()
        assert load_catalog("en") == {}

    def test_the_documented_default_produces_no_warning(self, caplog):
        from potato.server_utils.config_module import validate_ui_language_config
        with caplog.at_level("WARNING"):
            validate_ui_language_config({"ui_language": "en"})
        assert not [r for r in caplog.records if "unknown language code" in r.getMessage()]

    def test_a_real_typo_still_warns(self, caplog):
        from potato.server_utils.config_module import validate_ui_language_config
        with caplog.at_level("WARNING"):
            validate_ui_language_config({"ui_language": "xx"})
        assert any("unknown language code" in r.getMessage() for r in caplog.records)


# -------------------------------------------------------------- finding 10 --
class TestListValuedFields:
    def test_a_list_field_is_not_rendered_as_a_python_repr(self):
        from potato.server_utils.displays.text_display import _format_list
        rendered = _format_list(["open", "unverified", "priority-1"])
        assert "['open'" not in rendered
        assert "open" in rendered and "unverified" in rendered

    def test_list_as_text_true_is_accepted(self):
        import potato.flask_server as fs
        with open("potato/flask_server.py", encoding="utf-8") as f:
            source = f.read()
        assert 'list_config = config.get("list_as_text")' in source
        assert "if not isinstance(list_config, dict):" in source


# -------------------------------------------------------------- finding 12 --
class TestKeywordHighlightFormats:
    @pytest.mark.parametrize("raw,path,expected_words", [
        ("Word\tSchema\tLabel\nlatch\tkeyword\tHazard\n", "k.tsv", ["latch"]),
        ("keyword,label,schema\nlatch,Hazard,kw\nswell*,Hazard,kw\n", "k.csv",
         ["latch", "swell*"]),
        ("category,term\nHazard,latch\n", "k.csv", ["latch"]),
        ("latch\tHazard\n", "k.tsv", ["latch"]),
        ("latch\nswelled\n", "k.txt", ["latch", "swelled"]),
        ("keyword\nlatch\n", "k.txt", ["latch"]),
        ("# comment\nlatch\n", "k.txt", ["latch"]),
        ('["latch","swelled"]', "k.json", ["latch", "swelled"]),
        ('[{"keyword":"latch","label":"Hazard"}]', "k.json", ["latch"]),
        ('{"latch":"Hazard"}', "k.json", ["latch"]),
        ('{"keyword":"latch"}\n{"keyword":"swelled"}\n', "k.jsonl",
         ["latch", "swelled"]),
        ("- keyword: latch\n  label: Hazard\n- swelled\n", "k.yaml",
         ["latch", "swelled"]),
        ("latch: Hazard\n", "k.yml", ["latch"]),
    ])
    def test_every_documented_shape_loads(self, raw, path, expected_words):
        import potato.flask_server as fs
        entries, _fmt = fs._parse_keyword_highlight_entries(raw, path)
        assert [e["word"] for e in entries] == expected_words

    def test_labels_and_schemas_survive_a_reordered_header(self):
        import potato.flask_server as fs
        entries, _ = fs._parse_keyword_highlight_entries(
            "schema,label,keyword\nkw,Hazard,latch\n", "k.csv")
        assert entries == [{"word": "latch", "label": "Hazard",
                            "schema": "kw", "color": ""}]

    def test_an_empty_file_is_not_an_error(self):
        import potato.flask_server as fs
        assert fs._parse_keyword_highlight_entries("", "k.txt") == ([], "empty")

    def test_a_hex_colour_is_stored_as_an_rgb_triple(self):
        import potato.flask_server as fs
        assert fs._as_rgb_triple("#ffcc00") == "(255, 204, 0)"
        assert fs._as_rgb_triple("#fc0") == "(255, 204, 0)"
        assert fs._as_rgb_triple("(34, 197, 94)") == "(34, 197, 94)"


# -------------------------------------------------------------- finding 13 --
class TestValidateChecksPaths:
    def test_validate_runs_the_boot_path_checks(self):
        with open("potato/validate_cli.py", encoding="utf-8") as f:
            source = f.read()
        assert "validate_file_paths(config_data, config_file_dir, config_file_dir)" in source
        assert "warn_about_unreadable_optional_files" in source

    def test_a_dead_header_file_key_is_named(self):
        from potato.server_utils.config_module import (
            warn_about_unreadable_optional_files)
        messages = warn_about_unreadable_optional_files(
            {"task_dir": ".", "header_file": "nope.html"}, os.getcwd())
        assert any("header_file" in m for m in messages)

    def test_a_missing_optional_file_is_named(self):
        from potato.server_utils.config_module import (
            warn_about_unreadable_optional_files)
        messages = warn_about_unreadable_optional_files(
            {"task_dir": ".", "keyword_highlights_file": "definitely-not-here.tsv"},
            os.getcwd())
        assert any("keyword_highlights_file" in m for m in messages)


# --------------------------------------------------------- findings 14/15 --
class TestOptionOrderingAndFiltering:
    @staticmethod
    def _soup(html):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    def test_multiselect_options_are_actually_reordered(self):
        import potato.flask_server as fs
        from potato.server_utils import presentation_order as order
        from potato.server_utils.schemas.multiselect import generate_multiselect_layout

        scheme = {"annotation_type": "multiselect", "name": "hz",
                  "description": "Hazards", "option_randomization": True,
                  "labels": ["fire", "smoke", "flood", "gas", "debris", "heat"]}
        soup = self._soup(generate_multiselect_layout(scheme)[0])
        orders = order.orders_for_item([scheme], "ana@lab.org", "W01")
        out = fs.randomize_options(soup, {scheme["description"]: orders["hz"]})
        shown = [i.get("label_name") for i in out.find_all("input")
                 if i.get("label_name")]
        assert shown == orders["hz"]
        assert shown != scheme["labels"], "the shuffle must actually change the DOM"

    def test_radio_options_are_actually_reordered(self):
        import potato.flask_server as fs
        from potato.server_utils import presentation_order as order
        from potato.server_utils.schemas.radio import generate_radio_layout

        scheme = {"annotation_type": "radio", "name": "hz",
                  "description": "Hazards", "option_randomization": True,
                  "labels": ["fire", "smoke", "flood", "gas", "debris", "heat"]}
        soup = self._soup(generate_radio_layout(scheme)[0])
        orders = order.orders_for_item([scheme], "ana@lab.org", "W01")
        out = fs.randomize_options(soup, {scheme["description"]: orders["hz"]})
        shown = [i.get("label_name") for i in out.find_all("input")
                 if i.get("label_name")]
        assert shown == orders["hz"]

    def test_dynamic_options_removes_the_labels_the_item_omits(self):
        import potato.flask_server as fs
        from potato.server_utils.schemas.multiselect import generate_multiselect_layout

        scheme = {"annotation_type": "multiselect", "name": "hz",
                  "description": "d", "dynamic_options": True,
                  "dynamic_options_field": "reported_hazards",
                  "labels": ["fire", "smoke", "flood", "gas", "debris", "heat"]}
        soup = self._soup(generate_multiselect_layout(scheme)[0])
        out = fs.filter_dynamic_options(
            soup, [scheme], {"reported_hazards": ["fire", "flood"]})
        assert [i.get("value") for i in out.find_all("input")] == ["fire", "flood"]


# -------------------------------------------------------------- finding 17 --
class TestLinkBuilderGuidance:
    def test_it_does_not_name_labels_from_another_task(self):
        with open("potato/static/span-link-manager.js", encoding="utf-8") as f:
            source = f.read()
        assert "<strong>question</strong>" not in source
        assert "exampleSpanLabels()" in source


# -------------------------------------------------------------- finding 19 --
class TestJudgeCalibrationResults:
    def test_the_generated_labels_are_reachable(self):
        with open("potato/judge_calibration/routes.py", encoding="utf-8") as f:
            source = f.read()
        assert '@judge_calibration_bp.route("/results", methods=["GET"])' in source

    def test_progress_says_where_the_results_are(self):
        with open("potato/judge_calibration/manager.py", encoding="utf-8") as f:
            source = f.read()
        assert '"results_dir": self.config.state_dir' in source
        assert "def get_results(" in source


# -------------------------------------------------------------- finding 20 --
class TestErrorSpanSourceField:
    def test_the_field_is_declared_and_emitted(self):
        from potato.server_utils.schemas.error_span import generate_error_span_layout
        from potato.server_utils.schemas.registry import schema_registry

        html, _ = generate_error_span_layout({
            "name": "mqm", "description": "d",
            "error_types": [{"name": "Accuracy"}],
            "source_field": "translation"})
        assert 'data-source-field="translation"' in html

        declared = schema_registry.list_schemas()
        entry = next(s for s in declared if s["name"] == "error_span")
        assert "source_field" in entry["optional_fields"]

    def test_the_client_reads_it(self):
        with open("potato/static/annotation.js", encoding="utf-8") as f:
            source = f.read()
        assert "form.getAttribute('data-source-field')" in source
        assert "sourceText === instanceText" in source
