"""taxonomy_file: a codebook CSV (code, label, parent, description) as a
hierarchical_multiselect taxonomy."""

import os

import pytest

from potato.server_utils.config_module import ConfigValidationError
from potato.server_utils.taxonomy_files import (
    TaxonomyFileError, apply_taxonomy_files, load_taxonomy_file)
from tests.helpers.test_utils import create_test_directory

CSV = """code,label,parent,description
1,Macroeconomics,,Economic policy in general
100,General,1,
101,Inflation,1,Prices and inflation
2,Civil Rights,,
201,Minority Discrimination,2,
2011,Ethnic,201,
"""


def _write(name, text):
    d = create_test_directory(name)
    p = os.path.join(d, "codes.csv")
    with open(p, "w") as f:
        f.write(text)
    return d, p


def test_tree_order_and_tooltips():
    _d, p = _write("taxonomy_tree", CSV)
    tax, tips = load_taxonomy_file(p)
    assert list(tax) == ["Macroeconomics", "Civil Rights"]
    assert tax["Macroeconomics"] == ["General", "Inflation"]
    assert tax["Civil Rights"] == {"Minority Discrimination": ["Ethnic"]}
    assert tips == {"Macroeconomics": "Economic policy in general", "Inflation": "Prices and inflation"}
    coded, _ = load_taxonomy_file(p, show_codes=True)
    assert coded["1 Macroeconomics"] == ["100 General", "101 Inflation"]


@pytest.mark.parametrize("text,match", [
    ("code,label,parent\n1,A,9\n", "not a code"),
    ("code,label,parent\n1,A,2\n2,B,1\n", "loop"),
    ("code,label,parent\n1,A,\n1,B,\n", "appears twice"),
    ("name,parent\nA,\n", "needs columns"),
])
def test_bad_files(text, match):
    _d, p = _write("taxonomy_bad", text)
    with pytest.raises(TaxonomyFileError, match=match):
        load_taxonomy_file(p)


def test_config_resolution_and_conflict():
    d, _p = _write("taxonomy_config", CSV)
    cfg = {"task_dir": d, "annotation_schemes": [
        {"annotation_type": "hierarchical_multiselect", "name": "topic", "description": "Topic",
         "taxonomy_file": "codes.csv", "tooltips": {"General": "Override"}}]}
    apply_taxonomy_files(cfg, d)
    scheme = cfg["annotation_schemes"][0]
    assert "Inflation" in scheme["taxonomy"]["Macroeconomics"]
    assert scheme["tooltips"]["General"] == "Override"
    both = {"task_dir": d, "annotation_schemes": [{"taxonomy_file": "codes.csv", "taxonomy": {"a": []}}]}
    with pytest.raises(ConfigValidationError, match="not both"):
        apply_taxonomy_files(both, d)


DUPES = """code,label,parent,description
1,Economy,,
101,Other,1,Other economic topics
102,Other,1,
2,Health,,
201,Other,2,Other health topics
"""


def test_repeated_labels_are_refused_and_name_the_codes():
    """Audit 97 T5: the scheme stores the label, so three "Other" entries were
    one answer, and restoring one ticked all three."""
    _d, p = _write("taxonomy_dupes", DUPES)
    with pytest.raises(TaxonomyFileError, match=r"'Other' \(codes 101, 102, 201\).*show_codes"):
        load_taxonomy_file(p)


def test_show_codes_makes_repeated_labels_distinct():
    _d, p = _write("taxonomy_dupes_coded", DUPES)
    tax, tips = load_taxonomy_file(p, show_codes=True)
    assert tax == {"1 Economy": ["101 Other", "102 Other"], "2 Health": ["201 Other"]}
    assert tips == {"101 Other": "Other economic topics", "201 Other": "Other health topics"}


def test_repeated_entries_in_a_yaml_taxonomy_are_refused():
    d = create_test_directory("taxonomy_dupes_yaml")
    p = os.path.join(d, "codes.yaml")
    with open(p, "w") as f:
        f.write("Economy: [Other, Tax]\nHealth: [Other]\n")
    with pytest.raises(TaxonomyFileError, match="more than once.*Other"):
        load_taxonomy_file(p)


def test_repeated_labels_fail_the_config():
    d, _p = _write("taxonomy_dupes_config", DUPES)
    cfg = {"task_dir": d, "annotation_schemes": [
        {"annotation_type": "hierarchical_multiselect", "name": "topic", "description": "Topic",
         "taxonomy_file": "codes.csv"}]}
    with pytest.raises(ConfigValidationError, match="taxonomy_file.*codes 101, 102, 201"):
        apply_taxonomy_files(cfg, d)


# Pre-release: a JSON or YAML file whose top level is a list of nodes passed
# load_taxonomy_file and then failed validation with "taxonomy must be a
# non-empty dictionary", which names neither the file nor the shape it needs.
# The documented shape is a mapping at the top level.

LIST_ROOTS = {
    "codes.json": '[{"Sciences": ["Physics", "Biology"]}, {"Humanities": ["History"]}]',
    "codes.yaml": "- Sciences: [Physics, Biology]\n- Humanities: [History]\n",
    "flat.yaml": "- Physics\n- Biology\n",
    "wrapped.yaml": "taxonomy:\n  - Physics\n  - Biology\n",
}


@pytest.mark.parametrize("name", sorted(LIST_ROOTS))
def test_list_root_is_refused_by_the_loader(name):
    d = create_test_directory("taxonomy_list_root")
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(LIST_ROOTS[name])
    with pytest.raises(TaxonomyFileError, match=r"top level.*mapping.*not a list"):
        load_taxonomy_file(p)


@pytest.mark.parametrize("name", ["codes.json", "codes.yaml"])
def test_list_root_fails_the_config_naming_the_file(name):
    import yaml
    from potato.server_utils.config_module import load_and_validate_config
    d = create_test_directory("taxonomy_list_root_config")
    with open(os.path.join(d, name), "w") as f:
        f.write(LIST_ROOTS[name])
    with open(os.path.join(d, "data.jsonl"), "w") as f:
        f.write('{"id": "1", "text": "hello"}\n')
    cfg = {"annotation_task_name": "t", "task_dir": ".", "output_annotation_dir": "out/",
           "data_files": ["data.jsonl"], "item_properties": {"id_key": "id", "text_key": "text"},
           "user_config": {"allow_all_users": True, "users": []},
           "annotation_schemes": [{"annotation_type": "hierarchical_multiselect", "name": "topic",
                                   "description": "Topic", "taxonomy_file": name}]}
    path = os.path.join(d, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f)
    with pytest.raises(ConfigValidationError, match=rf"taxonomy_file.*{name}.*not a list"):
        load_and_validate_config(path, d)
