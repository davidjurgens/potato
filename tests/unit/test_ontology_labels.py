"""
Ontology-backed labels (`label_source`): the OBO reader, search, config
validation, the OLS4 proxy (HTTP mocked, never the network), the page markup
and restore hook, agreement on obo_id, and what the exports write.

Fixture: tests/data/ontology/scl-sample.obo, a synthetic sample (prefix SCL).
"""

import json
import os
import shutil
from unittest.mock import MagicMock, patch

import pytest
import yaml

from potato.ontology import obo as obo_mod
from potato.ontology.obo import OboError, load_obo_file, parse_obo_text, term_iri
from potato.ontology.source import (
    DEFAULT_OLS4_BASE_URL, FileSource, LabelSourceError, Ols4Source,
    OntologyServiceError, TermLedger, check_label_source, clear_source_caches,
    normalize_record,
)
from tests.helpers.test_utils import create_test_directory

HERE = os.path.dirname(os.path.abspath(__file__))
OBO = os.path.join(os.path.dirname(HERE), "data", "ontology", "scl-sample.obo")
VERSION = "scl/releases/2026-10-01"


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_source_caches()
    yield
    clear_source_caches()


@pytest.fixture(scope="module")
def onto():
    return load_obo_file(OBO)


def _rec(obo_id, label, version=VERSION):
    return json.dumps({"obo_id": obo_id, "label": label, "iri": term_iri(obo_id),
                       "ontology_version": version})


# ---------------------------------------------------------------------------
# OBO reader
# ---------------------------------------------------------------------------

class TestOboReader:
    def test_header_and_terms(self, onto):
        assert onto.version == VERSION
        assert onto.name == "scl"
        # 20 [Term] stanzas, one obsolete; the [Typedef] is not a term.
        assert len(onto.terms) == 19
        assert "develops_from" not in onto.terms
        assert onto.get("SCL:0000014").namespace == "synthetic_cell"  # default-namespace

    def test_obsolete_terms_are_skipped_but_known(self, onto):
        assert onto.get("SCL:0000018") is None
        assert "SCL:0000018" in onto.obsolete_ids
        assert "SCL:0000018" not in onto.descendants("SCL:0000003")

    def test_tags_are_unescaped_and_comments_dropped(self, onto):
        t = onto.get("SCL:0000004")
        assert t.name == "T cell"
        assert t.definition == 'A lymphocyte in the sample hierarchy. Used to test "escaped" quotes.'
        assert ("T-lymphocyte", "EXACT") in t.synonyms
        assert t.is_a == ["SCL:0000003"]
        # `is_a: X ! comment {qualifier}` keeps only the id.
        assert onto.get("SCL:0000003").is_a == ["SCL:0000002"]

    def test_relationship_is_not_an_is_a_edge(self, onto):
        # macrophage `relationship: develops_from monocyte` must not make it a child.
        assert "SCL:0000011" not in onto.descendants("SCL:0000010")

    def test_alt_id_resolves_to_primary(self, onto):
        assert onto.get("SCL:0000099").id == "SCL:0000004"

    def test_subtree_follows_is_a_transitively(self, onto):
        sub = onto.descendants("SCL:0000001")
        assert {"SCL:0000001", "SCL:0000005", "SCL:0000011"} <= sub
        assert not sub & {"SCL:0000000", "SCL:0000013", "SCL:0000015"}

    def test_iri(self):
        assert term_iri("CL:0000236") == "http://purl.obolibrary.org/obo/CL_0000236"
        assert term_iri("http://x.org/a") == "http://x.org/a"

    def test_version_falls_back_to_file_hash(self):
        o = parse_obo_text("format-version: 1.4\n\n[Term]\nid: X:1\nname: a\n", sha256="ab" * 32)
        assert o.version == "sha256:abababababab"

    def test_owl_file_is_refused_with_conversion_advice(self, tmp_path_factory):
        d = create_test_directory("ontology_owl")
        p = os.path.join(d, "x.owl")
        with open(p, "w") as fh:
            fh.write('<?xml version="1.0"?>\n<rdf:RDF><owl:Ontology/></rdf:RDF>\n')
        with pytest.raises(OboError, match="robot convert"):
            load_obo_file(p)

    def test_size_limit(self):
        with pytest.raises(OboError, match="limit"):
            load_obo_file(OBO, max_mb=0.0001)

    def test_file_without_terms_is_refused(self):
        d = create_test_directory("ontology_empty")
        p = os.path.join(d, "e.obo")
        with open(p, "w") as fh:
            fh.write("format-version: 1.4\n")
        with pytest.raises(OboError, match="no \\[Term\\]"):
            load_obo_file(p)


class TestSearch:
    def names(self, onto, q, **kw):
        hits, _total = onto.search(q, **kw)
        return [t.name for t, _ in hits]

    def test_exact_label_first_then_prefix_then_words(self, onto):
        assert self.names(onto, "T cell")[:3] == ["T cell", "CD4-positive T cell", "CD8-positive T cell"]

    def test_synonym_match_names_the_synonym(self, onto):
        hits, _ = onto.search("helper")
        assert [(t.id, s) for t, s in hits] == [("SCL:0000005", "helper T cell")]

    def test_id_queries(self, onto):
        assert self.names(onto, "SCL:0000007") == ["B cell"]
        assert self.names(onto, "scl_0000007") == ["B cell"]
        assert self.names(onto, "SCL:0000099") == ["T cell"]   # alt_id

    def test_limit_and_total(self, onto):
        hits, total = onto.search("cell", limit=3)
        assert len(hits) == 3 and total == 13

    def test_allowed_set_restricts(self, onto):
        allowed = onto.descendants("SCL:0000009")
        assert set(self.names(onto, "cell", allowed=allowed)) == {"myeloid cell"}

    def test_obsolete_never_matches(self, onto):
        assert self.names(onto, "progenitor") == []


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def _scheme(**ls):
    base = {"ontology": "scl", "service": "file", "file": "scl.obo"}
    base.update(ls)
    return {"annotation_type": "radio", "name": "ct", "description": "d", "labels": [],
            "label_source": {k: v for k, v in base.items() if v is not None}}


class TestStructuralChecks:
    @pytest.mark.parametrize("ls, message", [
        ({"service": "sparql"}, "service must be one of"),
        ({"file": None}, "file is required"),
        ({"file": "https://x.org/cl.obo"}, "local path"),
        ({"max_results": 0}, "max_results"),
        ({"max_results": True}, "max_results"),
        ({"root": "not an id"}, "root must be a term id"),
        ({"ontology": "c l"}, "ontology must be"),
        ({"colour": "red"}, "unknown key"),
        ({"base_url": "https://x"}, "base_url applies to service ols4"),
        ({"service": "ols4", "file": None}, "allow_network: true"),
        ({"service": "ols4", "file": None, "allow_network": "yes"}, "allow_network: true"),
        ({"service": "ols4", "file": None, "allow_network": True, "base_url": "ftp://x"}, "base_url"),
        ({"service": "ols4", "file": None, "allow_network": True, "timeout_s": 90}, "timeout_s"),
        ({"service": "ols4", "allow_network": True}, "file applies to service file"),
    ])
    def test_refusals_name_the_key(self, ls, message):
        with pytest.raises(LabelSourceError, match=message):
            check_label_source(_scheme(**ls), "annotation_schemes[0]")

    def test_wrong_scheme_type(self):
        s = _scheme()
        s["annotation_type"] = "likert"
        with pytest.raises(LabelSourceError, match="applies to radio, multiselect, span"):
            check_label_source(s, "p")

    def test_valid_blocks_pass(self):
        check_label_source(_scheme(root="SCL:0000001", max_results=50), "p")
        check_label_source(_scheme(service="ols4", file=None, allow_network=True,
                                   base_url="https://ols.example.org/api", timeout_s=3), "p")


def _write_project(name, schemes, obo_into=("scl.obo",)):
    d = create_test_directory(name)
    for rel in obo_into:
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        shutil.copy(OBO, os.path.join(d, rel))
    with open(os.path.join(d, "data.jsonl"), "w") as fh:
        fh.write(json.dumps({"id": "1", "text": "x"}) + "\n")
    cfg = {"annotation_task_name": name, "task_dir": ".", "output_annotation_dir": "out",
           "data_files": ["data.jsonl"], "item_properties": {"id_key": "id", "text_key": "text"},
           "user_config": {"allow_all_users": True, "users": []},
           "annotation_schemes": schemes}
    path = os.path.join(d, "config.yaml")
    with open(path, "w") as fh:
        yaml.safe_dump(cfg, fh)
    return d, path


def _load(d, path):
    from potato.server_utils.config_module import load_and_validate_config
    return load_and_validate_config(path, d)


class TestLoadTimeValidation:
    def test_picker_only_schemes_load(self):
        schemes = [_scheme(),
                   {"annotation_type": "multiselect", "name": "m", "description": "d",
                    "label_source": {"ontology": "scl", "service": "file", "file": "scl.obo"}},
                   {"annotation_type": "span", "name": "s", "description": "d", "labels": [],
                    "label_source": {"ontology": "scl", "service": "file", "file": "scl.obo",
                                     "root": "SCL:0000001"}},
                   {"annotation_type": "image_annotation", "name": "i", "description": "d",
                    "tools": ["bbox"], "labels": [],
                    "label_source": {"ontology": "scl", "service": "file", "file": "scl.obo"}}]
        d, path = _write_project("ontology_cfg_ok", schemes)
        cfg = _load(d, path)
        # `labels` left out is filled in, so generators can read it.
        assert cfg["annotation_schemes"][1]["labels"] == []

    def test_empty_labels_without_label_source_still_refused(self):
        from potato.server_utils.config_module import ConfigValidationError
        d, path = _write_project("ontology_cfg_nolabels",
                                 [{"annotation_type": "radio", "name": "r", "description": "d",
                                   "labels": []}])
        with pytest.raises(ConfigValidationError, match="labels cannot be empty"):
            _load(d, path)

    def test_select_is_not_supported(self):
        from potato.server_utils.config_module import ConfigValidationError
        s = _scheme()
        s["annotation_type"] = "select"
        d, path = _write_project("ontology_cfg_select", [s])
        with pytest.raises(ConfigValidationError, match="applies to radio"):
            _load(d, path)

    def test_missing_file(self):
        from potato.server_utils.config_module import ConfigValidationError
        d, path = _write_project("ontology_cfg_missing", [_scheme(file="nope.obo")])
        with pytest.raises(ConfigValidationError, match="label_source.file not found: nope.obo"):
            _load(d, path)

    def test_file_outside_task_dir(self):
        from potato.server_utils.config_module import ConfigSecurityError
        d, path = _write_project("ontology_cfg_outside", [_scheme(file="../scl.obo")])
        shutil.copy(OBO, os.path.join(os.path.dirname(d), "scl.obo"))
        with pytest.raises(ConfigSecurityError, match="label_source.file"):
            _load(d, path)

    def test_root_not_in_file(self):
        from potato.server_utils.config_module import ConfigValidationError
        d, path = _write_project("ontology_cfg_root", [_scheme(root="SCL:7777777")])
        with pytest.raises(ConfigValidationError, match="root SCL:7777777 is not a term"):
            _load(d, path)

    def test_obsolete_root(self):
        from potato.server_utils.config_module import ConfigValidationError
        d, path = _write_project("ontology_cfg_obsroot", [_scheme(root="SCL:0000018")])
        with pytest.raises(ConfigValidationError, match="obsolete"):
            _load(d, path)

    def test_ols4_without_opt_in(self):
        from potato.server_utils.config_module import ConfigValidationError
        d, path = _write_project("ontology_cfg_ols", [_scheme(service="ols4", file=None)])
        with pytest.raises(ConfigValidationError, match="allow_network: true"):
            _load(d, path)

    def test_unknown_service(self):
        from potato.server_utils.config_module import ConfigValidationError
        d, path = _write_project("ontology_cfg_service", [_scheme(service="bioportal")])
        with pytest.raises(ConfigValidationError, match="service must be one of"):
            _load(d, path)

    def test_example_config_loads(self):
        ex = os.path.join(os.path.dirname(os.path.dirname(HERE)), "examples", "classification",
                          "ontology-labels")
        cfg = _load(ex, os.path.join(ex, "config.yaml"))
        assert [s["name"] for s in cfg["annotation_schemes"]] == [
            "main_cell_type", "other_cell_types", "immune_cell_mentions"]

    def test_registry_declares_label_source(self):
        from potato.server_utils.schemas.registry import schema_registry
        for t in ("radio", "multiselect", "span", "image_annotation"):
            assert "label_source" in schema_registry.get_accepted_fields(t)
        assert "label_source" not in schema_registry.get_accepted_fields("likert")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _file_source(d=None, **ls):
    d = d or create_test_directory("ontology_src")
    shutil.copy(OBO, os.path.join(d, "scl.obo"))
    return FileSource(_scheme(**ls), d)


class TestFileSource:
    def test_search_records(self):
        out = _file_source().search("nk")
        assert out["version"] == VERSION
        assert out["results"] == [{
            "obo_id": "SCL:0000008", "label": "natural killer cell",
            "iri": "http://purl.obolibrary.org/obo/SCL_0000008",
            "ontology_version": VERSION, "synonym": "NK cell"}]

    def test_root_limits_search_and_lookup(self):
        src = _file_source(root="SCL:0000001")
        labels = [r["label"] for r in src.search("cell")["results"]]
        assert "neuron" not in labels and "cell" not in labels and "T cell" in labels
        assert src.get_term("SCL:0000015") is None      # neuron: outside the subtree
        assert src.get_term("SCL:0000004")["label"] == "T cell"

    def test_max_results(self):
        out = _file_source(max_results=2).search("cell")
        assert len(out["results"]) == 2 and out["total"] == 13

    def test_path_outside_task_dir_refused_at_runtime(self):
        from potato.server_utils.config_module import ConfigSecurityError
        d = create_test_directory("ontology_src_out")
        with pytest.raises(ConfigSecurityError):
            FileSource(_scheme(file="/etc/hosts"), d)

    def test_file_is_parsed_once(self):
        d = create_test_directory("ontology_parse_once")
        src = _file_source(d)
        with patch.object(obo_mod, "parse_obo_text", wraps=obo_mod.parse_obo_text) as spy:
            src.search("cell")
            src.search("lymph")
            FileSource(_scheme(), d).search("b cell")
        assert spy.call_count == 1


def _ols_reply(docs, num=None):
    resp = MagicMock()
    resp.status_code = 200
    body = {"response": {"numFound": len(docs) if num is None else num, "docs": docs}}
    resp.json.return_value = body
    resp.content = json.dumps(body).encode()
    return resp


def _ols_version_reply(version="2026-09-30"):
    resp = MagicMock()
    resp.status_code = 200
    body = {"ontologyId": "cl", "config": {"version": version}}
    resp.json.return_value = body
    resp.content = json.dumps(body).encode()
    return resp


OLS_DOCS = [
    {"iri": "http://purl.obolibrary.org/obo/CL_0000236", "label": "B cell",
     "obo_id": "CL:0000236", "ontology_name": "cl", "description": ["A lymphocyte ..."]},
    {"iri": "http://purl.obolibrary.org/obo/CL_0000785", "label": "mature B cell",
     "short_form": "CL_0000785", "ontology_name": "cl"},
    {"iri": "http://purl.obolibrary.org/obo/GO_1", "label": "other ontology",
     "obo_id": "GO:1", "ontology_name": "go"},
]


def _ols_source(d=None, **ls):
    d = d or create_test_directory("ontology_ols")
    base = {"ontology": "cl", "service": "ols4", "allow_network": True}
    base.update(ls)
    scheme = {"annotation_type": "span", "name": "s", "description": "d", "labels": [],
              "label_source": base}
    return Ols4Source(scheme, d, os.path.join(d, "out", "ontology_cache"))


def _router(search_reply, version_reply=None):
    calls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append((url, dict(params or {}), timeout))
        if url.endswith("/search"):
            return search_reply
        return version_reply or _ols_version_reply()
    return fake_get, calls


class TestOls4Source:
    def test_search_goes_through_requests_with_params_and_timeout(self):
        fake, calls = _router(_ols_reply(OLS_DOCS, num=57))
        src = _ols_source(root="CL:0000000", max_results=10, timeout_s=2.5)
        with patch("requests.get", side_effect=fake):
            out = src.search("b  cell")
        search = [c for c in calls if c[0].endswith("/search")][0]
        assert search[0] == f"{DEFAULT_OLS4_BASE_URL}/search"
        assert search[1]["q"] == "b cell" and search[1]["ontology"] == "cl"
        assert search[1]["rows"] == 10 and search[1]["obsoletes"] == "false"
        assert search[1]["childrenOf"] == "http://purl.obolibrary.org/obo/CL_0000000"
        assert search[2] == 2.5
        assert [r["obo_id"] for r in out["results"]] == ["CL:0000236", "CL:0000785"]
        assert out["results"][1]["ontology_version"] == "2026-09-30"
        assert out["total"] == 57

    def test_custom_base_url(self):
        fake, calls = _router(_ols_reply(OLS_DOCS))
        src = _ols_source(base_url="https://ols.example.org/api/")
        with patch("requests.get", side_effect=fake):
            src.search("b cell")
        assert all(c[0].startswith("https://ols.example.org/api/") for c in calls)

    def test_cache_answers_a_repeat_without_http(self):
        fake, calls = _router(_ols_reply(OLS_DOCS))
        src = _ols_source()
        with patch("requests.get", side_effect=fake):
            src.search("B cell")
            n = len(calls)
            src.search("b cell")
        assert len(calls) == n

    def test_timeout_and_http_errors(self):
        import requests
        src = _ols_source()
        with patch("requests.get", side_effect=requests.Timeout()):
            with pytest.raises(OntologyServiceError, match="within"):
                src.search("x cell")
        bad = MagicMock(status_code=503, content=b"")
        fake, _ = _router(bad, _ols_version_reply())
        with patch("requests.get", side_effect=fake):
            with pytest.raises(OntologyServiceError, match="503"):
                _ols_source().search("y cell")

    def test_no_request_without_opt_in(self):
        src = _ols_source()
        src.ls["allow_network"] = False
        with patch("requests.get") as get:
            with pytest.raises(OntologyServiceError, match="not enabled"):
                src.search("z cell")
        get.assert_not_called()

    def test_ledger_keeps_returned_terms_on_disk(self):
        d = create_test_directory("ontology_ledger")
        fake, _ = _router(_ols_reply(OLS_DOCS))
        with patch("requests.get", side_effect=fake):
            _ols_source(d).search("b cell")
        # A fresh source (a restart) still resolves the id, without HTTP.
        with patch("requests.get") as get:
            rec = _ols_source(d).get_term("CL:0000236")
        get.assert_not_called()
        assert rec == {"obo_id": "CL:0000236", "label": "B cell",
                       "iri": "http://purl.obolibrary.org/obo/CL_0000236",
                       "ontology_version": "2026-09-30"}
        assert os.path.exists(os.path.join(d, "out", "ontology_cache", "cl-ols4-terms.json"))


# ---------------------------------------------------------------------------
# Records, markup and restore
# ---------------------------------------------------------------------------

class TestRecords:
    def test_normalize(self):
        assert normalize_record(_rec("SCL:1", "x"))["obo_id"] == "SCL:1"
        assert normalize_record("SCL:1") is None
        assert normalize_record("{not json") is None
        assert normalize_record({"label": "no id"}) is None


class TestMarkup:
    def test_picker_for_each_type_and_none_without_label_source(self):
        from potato.ontology.picker import picker_html
        for t in ("radio", "multiselect", "span", "image_annotation"):
            s = _scheme()
            s["annotation_type"] = t
            assert 'data-annotation-type="%s"' % t in picker_html(s)
        assert picker_html({"annotation_type": "radio", "name": "r", "labels": ["a"]}) == ""

    def test_required_sentinel_only_when_picker_only(self):
        from potato.ontology.picker import picker_html
        s = _scheme()
        s["label_requirement"] = {"required": True}
        assert "ontology-required-sentinel" in picker_html(s)
        s["labels"] = ["unclear"]
        assert "ontology-required-sentinel" not in picker_html(s)

    def test_generators_emit_the_picker(self):
        from potato.server_utils.schemas.registry import schema_registry
        for t in ("radio", "multiselect", "span"):
            s = _scheme()
            s["annotation_type"] = t
            html, _ = schema_registry.generate(s)
            assert 'data-ontology-picker="true"' in html
            assert "Error Generating" not in html

    def test_palette_matches_js(self):
        # The JS mirrors this FNV-1a hash; pin a value both sides must give.
        from potato.ontology.picker import fnv1a, term_color
        # Values computed with the JS (node) too; non-ASCII checks the UTF-8 path.
        assert fnv1a("SCL:0000011") == 0xB2067411
        assert fnv1a("\u00e9:1") == 0xD2C21230
        assert term_color("CL:0000236") == "#BAB0AC"


class TestRestoreHook:
    def _soup(self, atype, labels=()):
        from bs4 import BeautifulSoup
        from potato.server_utils.schemas.registry import schema_registry
        s = _scheme()
        s["annotation_type"] = atype
        s["name"] = "ct"
        s["labels"] = list(labels)
        s["label_requirement"] = {"required": True}
        html, _ = schema_registry.generate(s)
        return BeautifulSoup(html, "html.parser")

    def test_radio_term_gets_an_input(self):
        from potato.ontology.picker import add_stored_term_inputs
        soup = self._soup("radio")
        n = add_stored_term_inputs(soup, {"ct": {"SCL:0000007": _rec("SCL:0000007", "B cell")}})
        assert n == 1
        inp = soup.find("input", attrs={"label_name": "SCL:0000007"})
        assert inp["type"] == "radio" and inp["name"] == "ct" and inp["schema"] == "ct"
        assert json.loads(inp["value"])["label"] == "B cell"
        assert inp["validation"] == "required"
        assert soup.find(class_="ontology-required-sentinel")["value"] == "1"
        assert "B cell" in inp.find_next("label").get_text()

    def test_multiselect_and_existing_labels(self):
        from potato.ontology.picker import add_stored_term_inputs
        soup = self._soup("multiselect", labels=["None"])
        stored = {"ct": {"None": "None", "SCL:0000011": _rec("SCL:0000011", "macrophage")}}
        assert add_stored_term_inputs(soup, stored) == 1   # the fixed label already has one
        inp = soup.find("input", attrs={"label_name": "SCL:0000011"})
        assert inp["type"] == "checkbox" and inp["name"] == "ct:::SCL:0000011"

    def test_non_record_values_are_ignored(self):
        from potato.ontology.picker import add_stored_term_inputs
        soup = self._soup("radio")
        assert add_stored_term_inputs(soup, {"ct": {"SCL:1": "SCL:1", "x": "free text"}}) == 0

    def test_image_label_buttons_named_from_the_file(self):
        from bs4 import BeautifulSoup
        from potato.ontology.picker import add_stored_term_inputs
        from potato.server_utils.schemas.registry import schema_registry
        d = create_test_directory("ontology_img_restore")
        shutil.copy(OBO, os.path.join(d, "scl.obo"))
        s = _scheme()
        s.update({"annotation_type": "image_annotation", "name": "img", "tools": ["bbox"]})
        html, _ = schema_registry.generate(s)
        soup = BeautifulSoup(html, "html.parser")
        data = json.dumps([{"type": "bbox", "label": "SCL:0000011", "coordinates": {}},
                           {"type": "bbox", "label": "SCL:0000011", "coordinates": {}}])
        cfg = {"task_dir": d, "annotation_schemes": [s]}
        assert add_stored_term_inputs(soup, {"img": {"_data": data}}, cfg) == 1
        btn = soup.find("button", attrs={"data-label": "SCL:0000011"})
        assert btn.get_text().strip() == "macrophage"
        assert "label-btn" in btn["class"]


# ---------------------------------------------------------------------------
# Agreement compares obo_id
# ---------------------------------------------------------------------------

class _State:
    def __init__(self, by_item):
        from potato.item_state_management import Label
        self._d = {iid: {Label(s, n): v for (s, n), v in labels.items()}
                   for iid, labels in by_item.items()}

    def get_label_annotations(self, iid):
        return self._d.get(iid, {})


class TestAgreement:
    def test_radio_agreement_uses_obo_id_not_the_record(self):
        from potato.server_utils.iaa.dispatcher import _aggregate_nominal, _gather_labels
        # Same term, recorded against two different ontology versions.
        a = _State({"1": {("ct", "SCL:0000004"): _rec("SCL:0000004", "T cell", "v1")},
                    "2": {("ct", "SCL:0000007"): _rec("SCL:0000007", "B cell", "v1")}})
        b = _State({"1": {("ct", "SCL:0000004"): _rec("SCL:0000004", "T cell", "v2")},
                    "2": {("ct", "SCL:0000007"): _rec("SCL:0000007", "B-cell (renamed)", "v2")}})
        rows = _gather_labels(["1", "2"], {"a": a, "b": b}, "ct",
                              scheme={"annotation_type": "radio", "name": "ct"})
        assert rows["1"] == {"a": ["SCL:0000004"], "b": ["SCL:0000004"]}
        assert _aggregate_nominal(rows)["percent_agreement"] == 1.0

    def test_disagreement_is_seen(self):
        from potato.server_utils.iaa.dispatcher import _aggregate_nominal, _gather_labels
        a = _State({"1": {("ct", "SCL:0000004"): _rec("SCL:0000004", "T cell")}})
        b = _State({"1": {("ct", "SCL:0000005"): _rec("SCL:0000005", "CD4-positive T cell")}})
        rows = _gather_labels(["1"], {"a": a, "b": b}, "ct",
                              scheme={"annotation_type": "radio", "name": "ct"})
        assert _aggregate_nominal(rows)["percent_agreement"] == 0.0

    def test_span_and_image_compare_the_id(self):
        from potato.server_utils import annotation_values
        from potato.server_utils.iaa.span import _span_tuple
        assert _span_tuple({"start": 0, "end": 3, "name": "SCL:0000005"})[2] == "SCL:0000005"
        blob = {"_data": json.dumps([{"type": "bbox", "label": "SCL:0000011",
                                      "coordinates": {"left": 0, "top": 0, "width": 1, "height": 1}}])}
        val = annotation_values.comparable_value({"annotation_type": "image_annotation"}, blob)
        assert "SCL:0000011" in json.dumps(val)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def _context(d, schemes, annotations):
    from potato.export.base import ExportContext
    return ExportContext(config={"task_dir": d, "annotation_schemes": schemes,
                                 "output_annotation_dir": "out"},
                         annotations=annotations, items={"1": {"id": "1", "text": "CD4 cells"}},
                         schemas=schemes, output_dir=os.path.join(d, "out"))


class TestExports:
    def _setup(self):
        d = create_test_directory("ontology_export")
        shutil.copy(OBO, os.path.join(d, "scl.obo"))
        ls = {"ontology": "scl", "service": "file", "file": "scl.obo"}
        schemes = [
            {"annotation_type": "radio", "name": "ct", "description": "d", "labels": ["unclear"],
             "label_source": dict(ls)},
            {"annotation_type": "span", "name": "sp", "description": "d", "labels": [],
             "label_source": dict(ls)},
            {"annotation_type": "image_annotation", "name": "img", "description": "d",
             "tools": ["bbox"], "labels": [], "label_source": dict(ls)},
        ]
        ann = [{"instance_id": "1", "user_id": "u1",
                "labels": {"ct": {"SCL:0000005": _rec("SCL:0000005", "CD4-positive T cell")},
                           "img": {"_data": json.dumps([{"type": "bbox", "label": "SCL:0000011"},
                                                        {"type": "bbox", "label": "SCL:4040404"}])}},
                "spans": {"sp": [{"schema": "sp", "name": "SCL:0000005", "title": "SCL:0000005",
                                  "start": 0, "end": 3}]}},
               {"instance_id": "1", "user_id": "u2", "labels": {"ct": {"unclear": "unclear"}},
                "spans": {}}]
        return d, schemes, ann

    def test_ontology_terms_export(self):
        from potato.export.ontology_terms_exporter import OntologyTermsExporter
        d, schemes, ann = self._setup()
        ctx = _context(d, schemes, ann)
        exp = OntologyTermsExporter()
        assert exp.can_export(ctx)[0]
        out = os.path.join(d, "export")
        result = exp.export(ctx, out)
        assert result.success, result.errors
        with open(os.path.join(out, "ontology_terms.jsonl")) as fh:
            rows = [json.loads(line) for line in fh]
        by = {(r["schema"], r["obo_id"]): r for r in rows}
        assert set(by) == {("ct", "SCL:0000005"), ("sp", "SCL:0000005"),
                           ("img", "SCL:0000011"), ("img", "SCL:4040404")}
        assert by[("ct", "SCL:0000005")]["label"] == "CD4-positive T cell"
        assert by[("sp", "SCL:0000005")]["ontology_version"] == VERSION
        assert by[("sp", "SCL:0000005")]["text"] == "CD4"
        assert by[("sp", "SCL:0000005")]["start"] == 0
        assert by[("img", "SCL:0000011")]["label"] == "macrophage"
        assert by[("img", "SCL:0000011")]["shape_index"] == 0
        assert by[("img", "SCL:4040404")]["known"] is False
        assert result.warnings and "not in the current ontology" in result.warnings[0]
        # u2's fixed label is not a term row.
        assert all(r["user_id"] == "u1" for r in rows)
        with open(os.path.join(out, "ontology_terms.csv")) as fh:
            header = fh.readline().strip().split(",")
        assert header[:9] == ["user_id", "instance_id", "schema", "annotation_type", "ontology",
                              "obo_id", "label", "iri", "ontology_version"]

    def test_no_label_source_cannot_export(self):
        from potato.export.ontology_terms_exporter import OntologyTermsExporter
        d = create_test_directory("ontology_export_none")
        ctx = _context(d, [{"annotation_type": "radio", "name": "r", "labels": ["a"]}], [])
        assert OntologyTermsExporter().can_export(ctx)[0] is False

    def test_csv_export_column_holds_the_record(self):
        """What the generic csv export writes for an ontology radio (documented)."""
        from potato.export.tabular_exporter import CSVExporter
        d, schemes, ann = self._setup()
        ctx = _context(d, schemes, ann)
        out = os.path.join(d, "csv")
        result = CSVExporter().export(ctx, out)
        assert result.success, result.errors
        import csv as _csv
        path = [p for p in result.files_written if p.endswith(".csv")][0]
        with open(path, newline="") as fh:
            rows = list(_csv.DictReader(fh))
        u1 = [r for r in rows if r.get("user_id") == "u1"][0]
        assert json.loads(u1["ct.SCL:0000005"])["label"] == "CD4-positive T cell"


class TestPocket:
    def test_label_source_scheme_is_not_pocket_capable(self):
        from potato.pocket.config import pocket_capability
        ok, bad = pocket_capability({"annotation_schemes": [_scheme(),
                                     {"annotation_type": "radio", "name": "plain", "labels": ["a"]}]})
        assert not ok and bad == ["ct"]


def test_a_stored_term_restores_with_the_value_the_picker_wrote():
    """The picker stores ``JSON.stringify(record)``: compact, strings only,
    TERM_KEYS order. The server re-renders stored terms from encode_record,
    and a different spelling of the same JSON made a restored answer save a
    different string from the one it loaded."""
    from potato.ontology.source import encode_record
    rec = {"obo_id": "CL:0000084", "label": "T cell", "iri": None,
           "ontology_version": 2025, "extra": "ignored"}
    assert encode_record(rec) == (
        '{"obo_id":"CL:0000084","label":"T cell","iri":"","ontology_version":"2025"}')
