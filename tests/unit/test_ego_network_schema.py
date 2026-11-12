"""ego_network scheme: page generation, config validation and completeness rules."""

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
from potato.server_utils.schemas.ego_network import (
    generate_ego_network_layout, incomplete_reasons, normalize_scheme, normalize_stages, parse_answer)
from potato.server_utils.schemas.registry import schema_registry

REPO = Path(__file__).resolve().parents[2]


def scheme(**over):
    base = {
        "annotation_type": "ego_network", "name": "net", "description": "Your network",
        "stages": [
            {"type": "name_generator", "id": "discuss", "min_alters": 2, "max_alters": 5,
             "sets": {"discuss": True}},
            {"type": "name_interpreter", "id": "about", "required": True, "questions": [
                {"name": "closeness", "type": "radio", "description": "How close to {name}?",
                 "labels": ["Very", "Somewhat", "Not"]},
                {"name": "years", "type": "number", "min": 0, "max": 99, "required": False}]},
            {"type": "dyad_census", "id": "know"},
            {"type": "sociogram", "id": "map", "rings": 2},
        ],
    }
    base.update(over)
    return base


def config_of(html_text):
    m = re.search(r"data-ego-config='([^']*)'", html_text)
    assert m, "the form carries its stage list"
    return json.loads(html.unescape(m.group(1)))


class TestGeneration:
    def test_renders_one_hidden_input_and_the_normalized_stages(self):
        out, keys = generate_ego_network_layout(scheme())
        assert keys == []
        assert 'data-annotation-type="ego_network"' in out
        hidden = re.findall(r'<input type="hidden"[^>]*class="annotation-input ego-network-input"', out)
        assert len(hidden) == 1
        assert 'label_name="net"' in out and 'name="net:::net"' in out
        cfg = config_of(out)
        assert cfg["layout"] == "steps"
        assert [s["type"] for s in cfg["stages"]] == [
            "name_generator", "name_interpreter", "dyad_census", "sociogram"]
        gen, interp, census, socio = cfg["stages"]
        assert gen["min_alters"] == 2 and gen["max_alters"] == 5 and gen["sets"] == {"discuss": True}
        # String labels become {name, text}; the stage-level `required` reaches
        # each question unless the question says otherwise.
        assert interp["questions"][0]["labels"][0] == {"name": "Very", "text": "Very"}
        assert interp["questions"][0]["required"] is True
        assert interp["questions"][1]["required"] is False
        assert census["prompt"] == "Do {a} and {b} know each other?"
        assert socio["rings"] == 2 and socio["allow_ties"] is True

    def test_stacked_layout_and_html_in_names_is_escaped(self):
        out, _ = generate_ego_network_layout(scheme(stage_layout="stacked",
                                                    description="<b>x</b>"))
        assert config_of(out)["layout"] == "stacked"
        assert "<b>x</b>" not in out

    def test_marker_for_frontend_assets_is_in_the_generated_html(self):
        from potato.flask_server import FRONTEND_ASSET_MARKERS
        out, _ = generate_ego_network_layout(scheme())
        assert all(m in out for m in FRONTEND_ASSET_MARKERS["ego_network"])

    def test_registered_with_every_key_it_reads(self):
        assert "ego_network" in schema_registry.get_supported_types()
        info = schema_registry.get("ego_network")
        assert {"stages"} <= set(info.required_fields)
        assert {"stage_layout"} <= set(info.optional_fields)


class TestValidation:
    def test_valid_scheme_passes(self):
        validate_single_annotation_scheme(scheme(), "annotation_schemes[0]")

    @pytest.mark.parametrize("over, fragment", [
        ({"stages": []}, "non-empty list"),
        ({"stages": [{"type": "roster_picker"}]}, "type must be one of"),
        ({"stages": [{"type": "dyad_census"}]}, "before any name_generator"),
        ({"stages": [{"type": "name_generator", "min_alters": 3, "max_alters": 2}]}, "max_alters is less"),
        ({"stages": [{"type": "name_generator", "roster": ["A"], "roster_field": "names"}]}, "not both"),
        ({"stages": [{"type": "name_generator", "colour": "red"}]}, "unknown key"),
        ({"stages": [{"type": "name_generator", "id": "a"}, {"type": "sociogram", "id": "a"}]},
         "used by another stage"),
        ({"stages": [{"type": "name_generator"}, {"type": "name_interpreter", "questions": [
            {"name": "q", "type": "radio", "labels": ["only one"]}]}]}, "at least two options"),
        ({"stages": [{"type": "name_generator"}, {"type": "name_interpreter", "questions": [
            {"name": "q", "type": "radio", "labels": [True, False]}]}]}, "quote Yes/No"),
        ({"stages": [{"type": "name_generator"},
                     {"type": "name_interpreter", "questions": [{"name": "q", "type": "text"}]},
                     {"type": "name_interpreter", "questions": [{"name": "q", "type": "text"}]}]},
         "used by another question"),
        ({"stages": [{"type": "name_generator"}, {"type": "sociogram", "rings": 9}]}, "between 0 and 6"),
        ({"layout": "stacked"}, "stage_layout"),
        ({"stage_layout": "tabs"}, "stage_layout must be one of"),
    ])
    def test_refuses(self, over, fragment):
        with pytest.raises(ConfigValidationError, match=re.escape(fragment)):
            validate_single_annotation_scheme(scheme(**over), "annotation_schemes[0]")

    def test_generator_shows_an_error_card_instead_of_raising(self):
        out, _ = generate_ego_network_layout(scheme(stages=[{"type": "sociogram"}]))
        assert "ego-network-input" not in out


def answer(alters, attributes=None, census=None, ties=None):
    return parse_answer(json.dumps({
        "alters": [{"id": f"a{i + 1}", "name": n, "named_in": ["discuss"]} for i, n in enumerate(alters)],
        "attributes": attributes or {}, "census": census or {}, "ties": ties or []}))


class TestCompleteness:
    stages = normalize_stages(scheme())

    def test_minimum_number_of_alters(self):
        reasons = incomplete_reasons(self.stages, answer(["Ann"]))
        assert any("name at least 2 people (1 so far)" in r for r in reasons)

    def test_required_question_counts_people_left(self):
        a = answer(["Ann", "Bob", "Cy"], attributes={"a1": {"closeness": "Very"}},
                   census={"a1|a2": True, "a1|a3": False, "a2|a3": False})
        reasons = incomplete_reasons(self.stages, a)
        assert reasons == ["About each person: 'How close to this person?' unanswered for 2 people"]

    def test_census_counts_answered_pairs(self):
        a = answer(["Ann", "Bob", "Cy"], attributes={k: {"closeness": "Not"} for k in ("a1", "a2", "a3")},
                   census={"a1|a2": True})
        assert incomplete_reasons(self.stages, a) == ["Who knows whom: 1 of 3 pairs answered"]

    def test_complete_network_has_no_reasons(self):
        a = answer(["Ann", "Bob"], attributes={"a1": {"closeness": "Very"}, "a2": {"closeness": "Not"}},
                   census={"a1|a2": False})
        assert incomplete_reasons(self.stages, a) == []

    def test_census_of_a_named_relation_uses_its_own_keys(self):
        stages = normalize_stages(scheme(stages=[{"type": "name_generator", "id": "discuss"},
                                                 {"type": "dyad_census", "relation": "work"}]))
        a = answer(["Ann", "Bob"], census={"a1|a2": True})
        assert incomplete_reasons(stages, a) == ["Who knows whom: 0 of 1 pairs answered"]
        a = answer(["Ann", "Bob"], census={"a1|a2|work": True})
        assert incomplete_reasons(stages, a) == []

    def test_parse_answer_drops_ties_to_unknown_alters(self):
        a = answer(["Ann", "Bob"], ties=[["a1", "a2"], ["a1", "a9"], ["a2", "a2"], ["a1", "a2", "work"]])
        assert a["ties"] == [["a1", "a2"], ["a1", "a2", "work"]]
        assert parse_answer("") is None and parse_answer("not json") is None


class TestClientScript:
    def test_script_parses(self):
        node = shutil.which("node")
        if not node:
            pytest.skip("node is not installed")
        js = REPO / "potato" / "static" / "ego-network.js"
        result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_client_and_server_share_the_reason_wording(self):
        """declare() in the JS mirrors incomplete_reasons(); the phrases must match."""
        js = (REPO / "potato" / "static" / "ego-network.js").read_text()
        for phrase in ("name at least ", " so far)", " pairs answered", "' unanswered for ", "this person"):
            assert phrase in js, phrase


def test_example_config_validates():
    import yaml
    cfg = yaml.safe_load((REPO / "examples" / "advanced" / "ego-network" / "config.yaml").read_text())
    for i, s in enumerate(cfg["annotation_schemes"]):
        validate_single_annotation_scheme(s, f"annotation_schemes[{i}]")
    page = json.loads((REPO / "examples" / "advanced" / "ego-network" / "surveys" / "your-network.json").read_text())
    ego = [q for q in page if q["annotation_type"] == "ego_network"]
    assert ego and normalize_scheme(ego[0])["layout"] == "steps"
