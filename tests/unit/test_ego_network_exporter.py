"""ego_network export: network measures, GraphML, and names kept out by default."""

import csv
import json
import os
import xml.etree.ElementTree as ET

import pytest

from potato.export.base import ExportContext
from potato.export.ego_network_exporter import EgoNetworkExporter, network_stats
from potato.export.registry import export_registry
from tests.helpers.test_utils import create_test_directory

NS = {"g": "http://graphml.graphdrawing.org/xmlns"}

SCHEME = {
    "annotation_type": "ego_network", "name": "net", "description": "Network",
    "stages": [
        {"type": "name_generator", "id": "discuss"},
        {"type": "name_interpreter", "id": "about", "questions": [
            {"name": "closeness", "type": "radio", "labels": ["very", "not"], "required": True},
            {"name": "roles", "type": "multiselect", "labels": ["kin", "work", "friend"]}]},
        {"type": "dyad_census", "id": "know"},
        {"type": "dyad_census", "id": "close", "relation": "close",
         "strength_labels": ["strong", "weak"]},
    ],
}

ANSWER = {
    "alters": [{"id": "a1", "name": "Ann Smith", "named_in": ["discuss"]},
               {"id": "a2", "name": "Bob Jones", "named_in": ["discuss"]},
               {"id": "a3", "name": "Cy Young", "named_in": ["discuss"]},
               {"id": "a4", "name": "Dee Long", "named_in": ["discuss"]}],
    "attributes": {"a1": {"closeness": "very", "roles": ["kin", "friend"]},
                   "a2": {"closeness": "not"}, "a3": {"closeness": "very"}, "a4": {"closeness": "not"}},
    # a1-a2 is tied on both relations; it is still one connected pair.
    "ties": [["a1", "a2"], ["a2", "a3"], ["a1", "a2", "close"]],
    "positions": {"a1": [0.25, 0.5], "a2": [0.75, 0.5]},
    "census": {"a1|a2": True, "a1|a3": False, "a1|a4": False, "a2|a3": True, "a2|a4": False,
               "a3|a4": False, "a1|a2|close": True, "a1|a3|close": False, "a1|a4|close": False,
               "a2|a3|close": False, "a2|a4|close": False, "a3|a4|close": False},
    "tie_attributes": {"a1|a2|close": {"strength": "strong"}},
}


def context(annotations=(), phase_responses=(), schemas=(SCHEME,), config=None):
    return ExportContext(config=config or {}, annotations=list(annotations), items={},
                         schemas=list(schemas), output_dir="", phase_responses=list(phase_responses))


def ann(user="u1", item="i1", answer=ANSWER):
    return {"user_id": user, "instance_id": item, "labels": {"net": {"net": json.dumps(answer)}}}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def out():
    return create_test_directory("ego_network_export")


class TestMeasures:
    def test_density_isolates_components(self):
        stats = network_stats(ANSWER["alters"], ANSWER["ties"])
        assert stats["network_size"] == 4
        assert stats["n_ties"] == 2            # a1-a2 counted once across relations
        assert stats["possible_ties"] == 6
        assert stats["density"] == pytest.approx(2 / 6, abs=1e-6)
        assert stats["isolates"] == 1           # a4
        assert stats["components"] == 2         # {a1, a2, a3} and {a4}
        assert stats["degree"] == {"a1": 1, "a2": 2, "a3": 1, "a4": 0}

    def test_complete_graph_and_tiny_networks(self):
        alters = [{"id": f"a{i}"} for i in range(5)]
        ties = [[f"a{i}", f"a{j}"] for i in range(5) for j in range(i + 1, 5)]
        assert network_stats(alters, ties)["density"] == 1.0
        one = network_stats([{"id": "a1"}], [])
        assert one["possible_ties"] == 0 and one["density"] == ""


class TestExport:
    def test_registered(self):
        assert export_registry.get("ego_network") is not None

    def test_files_and_rows(self, out):
        result = EgoNetworkExporter().export(context([ann()]), out)
        assert result.success
        egos = read_csv(os.path.join(out, "egos.csv"))
        assert len(egos) == 1
        e = egos[0]
        assert (e["user_id"], e["item"], e["source"], e["schema"]) == ("u1", "i1", "annotation", "net")
        assert e["network_size"] == "4" and e["n_ties"] == "2" and e["possible_ties"] == "6"
        assert float(e["density"]) == pytest.approx(1 / 3, abs=1e-5)
        assert e["relations"] == "tie|close"
        assert e["complete"] == "true"
        alters = read_csv(os.path.join(out, "alters.csv"))
        assert [a["alter_id"] for a in alters] == ["a1", "a2", "a3", "a4"]
        assert alters[0]["attr_roles"] == "kin|friend" and alters[0]["x"] == "0.25"
        assert alters[3]["degree"] == "0"
        edges = read_csv(os.path.join(out, "edges.csv"))
        assert [(r["source_alter"], r["target_alter"], r["relation"]) for r in edges] == [
            ("a1", "a2", "tie"), ("a2", "a3", "tie"), ("a1", "a2", "close")]
        assert edges[2]["tie_strength"] == "strong" and edges[0]["tie_strength"] == ""

    def test_names_are_left_out_by_default(self, out):
        result = EgoNetworkExporter().export(context([ann()]), out)
        assert "name" not in read_csv(os.path.join(out, "alters.csv"))[0]
        for root, _dirs, files in os.walk(out):
            for f in files:
                text = open(os.path.join(root, f), encoding="utf-8").read()
                for alter in ANSWER["alters"]:
                    assert alter["name"] not in text, f"{alter['name']} leaked into {f}"
        assert any("export_names=true" in w for w in result.warnings)

    @pytest.mark.parametrize("flag", [True, "true", "1", "yes"])
    def test_names_on_request(self, out, flag):
        EgoNetworkExporter().export(context([ann()]), out, {"export_names": flag})
        assert read_csv(os.path.join(out, "alters.csv"))[0]["name"] == "Ann Smith"
        tree = ET.parse(os.path.join(out, "graphml", "u1__i1.graphml"))
        keys = {k.get("attr.name"): k.get("id") for k in tree.getroot().findall("g:key", NS)}
        node = tree.getroot().find("g:graph/g:node[@id='a1']", NS)
        assert node.find(f"g:data[@key='{keys['name']}']", NS).text == "Ann Smith"

    def test_graphml_is_well_formed_with_attributes(self, out):
        EgoNetworkExporter().export(context([ann()]), out)
        tree = ET.parse(os.path.join(out, "graphml", "u1__i1.graphml"))
        root = tree.getroot()
        assert root.tag == "{http://graphml.graphdrawing.org/xmlns}graphml"
        keys = {k.get("id"): k.get("attr.name") for k in root.findall("g:key", NS)}
        assert "name" not in keys.values()
        graph = root.find("g:graph", NS)
        assert graph.get("edgedefault") == "undirected"
        nodes = {n.get("id"): {keys[d.get("key")]: d.text for d in n.findall("g:data", NS)}
                 for n in graph.findall("g:node", NS)}
        assert set(nodes) == {"a1", "a2", "a3", "a4"}
        assert nodes["a1"]["closeness"] == "very" and nodes["a1"]["roles"] == "kin|friend"
        assert nodes["a2"]["x"] == "0.75"
        edges = [(e.get("source"), e.get("target"),
                  {keys[d.get("key")]: d.text for d in e.findall("g:data", NS)})
                 for e in graph.findall("g:edge", NS)]
        assert len(edges) == 3
        assert edges[2][2] == {"relation": "close", "strength": "strong"}

    def test_incomplete_network_is_flagged(self, out):
        partial = dict(ANSWER, census={"a1|a2": True})
        EgoNetworkExporter().export(context([ann(answer=partial)]), out)
        e = read_csv(os.path.join(out, "egos.csv"))[0]
        assert e["complete"] == "false"
        assert "1 of 6 pairs answered" in e["incomplete_reason"]

    def test_survey_page_answers_are_exported(self, out):
        rows = [{"user_id": "p7", "phase": "prestudy", "page": "your_network", "sequence": 0,
                 "schema": "net", "label_name": "net", "value": json.dumps(ANSWER)}]
        ok, _ = EgoNetworkExporter().can_export(context(phase_responses=rows))
        assert ok
        EgoNetworkExporter().export(context(phase_responses=rows), out)
        e = read_csv(os.path.join(out, "egos.csv"))[0]
        assert (e["user_id"], e["item"], e["source"]) == ("p7", "your_network", "prestudy")
        assert os.path.exists(os.path.join(out, "graphml", "p7__your_network.graphml"))

    def test_scheme_declared_in_a_phase_file_is_found(self, out):
        survey = os.path.join(out, "surveys")
        os.makedirs(survey, exist_ok=True)
        with open(os.path.join(survey, "net.json"), "w") as f:
            json.dump([SCHEME], f)
        cfg = {"task_dir": out, "phases": {"order": ["net_page", "annotation"],
                                           "net_page": {"type": "prestudy", "file": "surveys/net.json"}}}
        ctx = context(schemas=[{"annotation_type": "radio", "name": "x", "description": "x",
                                "labels": ["a", "b"]}], config=cfg,
                      phase_responses=[{"user_id": "p1", "phase": "prestudy", "page": "net_page",
                                        "schema": "net", "label_name": "net", "value": json.dumps(ANSWER)}])
        assert EgoNetworkExporter().can_export(ctx)[0]
        EgoNetworkExporter().export(ctx, os.path.join(out, "x"))
        e = read_csv(os.path.join(out, "x", "egos.csv"))[0]
        assert e["complete"] == "true"   # completeness checked against the phase file's stages

    def test_nothing_to_export(self):
        ok, why = EgoNetworkExporter().can_export(context(schemas=[]))
        assert not ok and "ego_network" in why
