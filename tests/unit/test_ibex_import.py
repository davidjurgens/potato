"""Ibex / PCIbex experiments as Potato projects."""

import json
import os
from collections import Counter
from pathlib import Path

import pytest
import yaml

from potato.importers import projects
from potato.server_utils.config_module import load_and_validate_config
from tests.helpers.test_utils import create_test_directory

PCIBEX_JS = """PennController.ResetPrefix(null)
Sequence("intro", rshuffle("experiment"), SendResults())
Template("practice.csv", row => newTrial("practice", newController("DashedSentence", {s: row.Sentence}).print().wait()))
Template("items.csv", row =>
    newTrial("experiment",
        newController("DashedSentence", {s: row.Sentence}).print().log().wait()
    )
)
"""
ITEMS_CSV = "Item,Group,Condition,Sentence\n1,A,amb,The horse raced past the barn fell.\n1,B,unamb,The horse that was raced past the barn fell.\n2,A,unamb,While Anna dressed the baby played.\n2,B,amb,While Anna dressed the baby played!\n3,,filler,The chef tasted the soup.\n"

CLASSIC_JS = """var shuffleSequence = seq("setcounter", rshuffle(startsWith("exp")));
var items = [
  ["setcounter", "__SetCounter__", { }],
  ["intro", "Form", {html: {include: "intro.html"}}],
  ["prac", "DashedSentence", {s: "This is practice."}],
  [["exp-a", 1], "DashedSentence", {s: ["The horse", "raced", "fell."]}, "Question", {q: "Did it fall?", as: ["Yes", "No"]}],
  [["exp-b", 1], "DashedSentence", {s: ["The horse", "that was raced", "fell."]}, "Question", {q: "Did it fall?", as: ["Yes", "No"]}],
  [["exp-a", 2], "DashedSentence", {s: "While Anna dressed the baby played."}],
  [["exp-b", 2], "DashedSentence", {s: "While Anna dressed, the baby played."}],
  ["filler", "DashedSentence", {s: "The chef tasted the soup."}]
];
"""


def _project(name, files):
    d = Path(create_test_directory(name))
    for rel, text in files.items():
        p = d / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return d


def _boot(out):
    load_and_validate_config(str(out / "config.yaml"), str(out))


def test_pcibex_template_with_group_column():
    d = _project("ibex_pcibex", {"data_includes/main.js": PCIBEX_JS,
                                 "chunk_includes/items.csv": ITEMS_CSV,
                                 "chunk_includes/practice.csv": "Sentence\nA practice.\n"})
    assert projects.detect(str(d / "src")) == "ibex"
    imp = projects.IMPORTERS["ibex"]
    res = imp.parse_path(d / "src")
    assert res.kind == "spr" and res.lists == 2
    assert any("practice" in r for r in res.report)
    imp.write_project(res, str(d / "out"), source=str(d / "src"))
    cfg = yaml.safe_load((d / "out" / "config.yaml").read_text())
    assert cfg["conditions"]["factors"]["list"] == ["A", "B"]
    assert cfg["batch_assignment"]["group_by_condition"] == "list"
    assert cfg["trial_timing"]["presentation"]["mode"] == "moving_window"
    rows_a = [json.loads(l) for l in (d / "out" / "data" / "A.jsonl").read_text().splitlines()]
    assert [r["Condition"] for r in rows_a] == ["amb", "unamb", "filler"]
    ids = [r["id"] for f in ("A", "B") for r in
           map(json.loads, (d / "out" / "data" / f"{f}.jsonl").read_text().splitlines())]
    assert len(ids) == len(set(ids)), "item IDs must be unique across lists"
    _boot(d / "out")


def test_classic_latin_square_rotation_and_questions():
    d = _project("ibex_classic", {"data_includes/main.js": CLASSIC_JS})
    imp = projects.IMPORTERS["ibex"]
    res = imp.parse_path(d / "src")
    assert res.kind == "spr" and res.lists == 2 and res.has_question
    imp.write_project(res, str(d / "out"), source=str(d / "src"))
    lists = {}
    for f in ("L1", "L2"):
        lists[f] = [json.loads(l) for l in (d / "out" / "data" / f"{f}.jsonl").read_text().splitlines()]
    for rows in lists.values():
        assert Counter(r.get("item_group") for r in rows if "item_group" in r) == {1: 1, 2: 1}
    assert {r["condition"] for r in lists["L1"] if r.get("item_group") == 1} != \
           {r["condition"] for r in lists["L2"] if r.get("item_group") == 1}
    first = next(r for r in lists["L1"] if r.get("item_group") == 1)
    assert first["text"].count("|") == 2
    assert any(r["condition"] == "filler" for r in lists["L1"])
    cfg = yaml.safe_load((d / "out" / "config.yaml").read_text())
    assert cfg["trial_timing"]["response"]["keys"] == {"f": "Yes", "j": "No"}
    assert any("shuffleSequence" in r for r in res.report)
    _boot(d / "out")


def test_unsupported_trial_is_refused_clearly():
    js = 'Template("t.csv", row => newTrial("x", newImage(row.File).print(), newButton("ok").wait()))'
    d = _project("ibex_unsupported", {"data_includes/main.js": js, "chunk_includes/t.csv": "File\na.png\n"})
    with pytest.raises(ValueError, match="nothing to import"):
        projects.IMPORTERS["ibex"].parse_path(d / "src")


# Audit 97 T7: three ways an Ibex import lost items without saying so.

DUP_JS = """var items = [
  [["exp-a", 1], "DashedSentence", {s: "First a."}],
  [["exp-a", 1], "DashedSentence", {s: "Second a."}],
  [["exp-b", 1], "DashedSentence", {s: "Only b."}]
];
"""


def test_classic_duplicate_labels_keep_both_items_and_warn():
    d = _project("ibex_dup_labels", {"data_includes/main.js": DUP_JS})
    imp = projects.IMPORTERS["ibex"]
    res = imp.parse_path(d / "src")
    assert res.lists == 3
    texts = {i["text"] for i in res.items}
    assert texts == {"First a.", "Second a.", "Only b."}, texts
    assert len({i["id"] for i in res.items}) == 3
    assert any("two items labelled exp-a" in w for w in res.warnings), res.warnings
    imp.write_project(res, str(d / "out"), source=str(d / "src"))
    report = (d / "out" / "IMPORT_REPORT.md").read_text()
    assert "## Warnings" in report and "exp-a" in report
    _boot(d / "out")


def test_pcibex_missing_columns():
    js = PCIBEX_JS.replace("row.Sentence}).print().log()", "row.Sentence}).print().log(row.Region)")
    d = _project("ibex_missing_col", {"data_includes/main.js": js,
                                      "chunk_includes/items.csv": ITEMS_CSV})
    res = projects.IMPORTERS["ibex"].parse_path(d / "src")
    assert any("row.Region" in w and "items.csv" in w for w in res.warnings), res.warnings
    # The stimulus column itself missing would give every item empty text.
    d2 = _project("ibex_missing_text_col", {"data_includes/main.js": PCIBEX_JS,
                                            "chunk_includes/items.csv": "Item,Text\n1,Hello there.\n"})
    with pytest.raises(ValueError, match="no Sentence column"):
        projects.IMPORTERS["ibex"].parse_path(d2 / "src")


def test_no_items_is_an_error_and_the_cli_exits_non_zero(capsys):
    from potato.importers.cli import main
    d = _project("ibex_empty", {"data_includes/main.js": PCIBEX_JS,
                                "chunk_includes/items.csv": "Item,Group,Condition,Sentence\n"})
    with pytest.raises(ValueError, match="nothing to import.*no rows"):
        projects.IMPORTERS["ibex"].parse_path(d / "src")
    rc = main(["-f", "ibex", "-i", str(d / "src"), "-o", str(d / "out")])
    assert rc != 0 and "nothing to import" in capsys.readouterr().err
    assert not (d / "out" / "config.yaml").exists()


# Pre-release: Group values that start with "L" but are not L1..Ln (List1,
# List2) matched no list and their rows were written to no data file.

def test_pcibex_list_values_other_than_l1_ln_keep_every_row():
    csv_text = ITEMS_CSV.replace(",A,", ",List1,").replace(",B,", ",List2,")
    d = _project("ibex_list_names", {"data_includes/main.js": PCIBEX_JS,
                                     "chunk_includes/items.csv": csv_text})
    imp = projects.IMPORTERS["ibex"]
    res = imp.parse_path(d / "src")
    assert res.lists == 2
    imp.write_project(res, str(d / "out"), source=str(d / "src"))
    cfg = yaml.safe_load((d / "out" / "config.yaml").read_text())
    assert cfg["conditions"]["factors"]["list"] == ["List1", "List2"]
    rows = {f: [json.loads(l) for l in (d / "out" / "data" / f"{f}.jsonl").read_text().splitlines()]
            for f in ("List1", "List2")}
    assert [r["Condition"] for r in rows["List1"]] == ["amb", "unamb", "filler"]
    assert [r["Condition"] for r in rows["List2"]] == ["unamb", "amb", "filler"]
    _boot(d / "out")


def test_pcibex_list_names_sort_naturally():
    csv_text = "Group,Sentence\n" + "".join(f"L{k},Sentence {k}.\n" for k in range(1, 12))
    d = _project("ibex_list_sort", {"data_includes/main.js": PCIBEX_JS,
                                    "chunk_includes/items.csv": csv_text})
    imp = projects.IMPORTERS["ibex"]
    res = imp.parse_path(d / "src")
    imp.write_project(res, str(d / "out"), source=str(d / "src"))
    cfg = yaml.safe_load((d / "out" / "config.yaml").read_text())
    assert cfg["conditions"]["factors"]["list"] == [f"L{k}" for k in range(1, 12)]


def test_message_form_and_html_screens_are_reported():
    js = CLASSIC_JS.replace(
        '["setcounter", "__SetCounter__", { }],',
        '["setcounter", "__SetCounter__", { }],\n  ["welcome", "Message", {html: "Hi"}],\n'
        '  ["consent", "Html", {html: {include: "consent.html"}}],')
    d = _project("ibex_screens", {"data_includes/main.js": js})
    imp = projects.IMPORTERS["ibex"]
    res = imp.parse_path(d / "src")
    report = " ".join(res.report)
    for controller in ("Message", "Form", "Html"):
        assert f"1 {controller} screen(s)" in report, res.report
    assert "__SetCounter__" not in report
    imp.write_project(res, str(d / "out"), source=str(d / "src"))
    assert "1 Form screen(s)" in (d / "out" / "IMPORT_REPORT.md").read_text()

    pc = PCIBEX_JS.replace('Sequence("intro"', 'newTrial("intro", newHtml("consent", "consent.html").print())\n'
                           'newTrial("bye", newController("Message", {html: "Thanks"}).print())\n'
                           'Sequence("intro"')
    d2 = _project("ibex_pc_screens", {"data_includes/main.js": pc,
                                      "chunk_includes/items.csv": ITEMS_CSV})
    report = " ".join(imp.parse_path(d2 / "src").report)
    assert "Html screens" in report and "Message and Form" in report, report
