"""interlinear_gloss: Leipzig alignment checks, abbreviations, the scheme and
its config validation, FLExText and Toolbox import/export round trips, and the
plain-text and gb4e renderings."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from potato import igt
from potato.export.base import ExportContext
from potato.export.interlinear_exporter import (FlexTextExporter, IGTExporter, ToolboxExporter,
                                                gb4e_example, latex_escape, latex_gloss)
from potato.importers import projects
from potato.importers.projects.writer import write_project
from potato.server_utils.config_module import ConfigValidationError, _validate_interlinear_gloss
from potato.server_utils.schemas.registry import schema_registry
from tests.helpers.test_utils import create_test_directory

REPO = Path(__file__).resolve().parents[2]
JS = REPO / "potato" / "static" / "interlinear-gloss.js"

# ---------------------------------------------------------------------------
# Alignment (Leipzig rule 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("morphemes, gloss, status", [
    ("ev-ler-de", "house-PL-LOC", "ok"),
    ("vir-um=que", "man-ACC.SG=and", "ok"),           # "." inside one gloss is not a boundary
    ("senatus", "senate.NOM.SG", "ok"),
    ("s<um>ulat", "write<AV>", "ok"),                 # rule 9: infix position differs
    ("vir-um=que", "man-ACC.SG-and", "misaligned"),   # clitic glossed as an affix
    ("ev-ler-de", "house-PL", "misaligned"),           # one gloss short
    ("ros-am", "rose-ACC-SG", "misaligned"),           # "-" where rule 4 wants "."
    ("ev--ler", "house--PL", "misaligned"),            # empty morpheme
    ("ev-ler", "house-", "misaligned"),                # morpheme with no gloss
    ("ev ler", "house PL", "misaligned"),              # spaces inside a cell
    ("s<um>ulat", "write", "misaligned"),
    ("", "", "empty"),
    ("ev-ler", "", "incomplete"),
    ("", "house", "incomplete"),
])
def test_check_word(morphemes, gloss, status):
    assert igt.check_word(morphemes, gloss)["status"] == status


def test_clitic_affix_message_names_both_lines():
    result = igt.check_word("vir-um=que", "man-ACC.SG-and")
    assert result["messages"] == ["segmentation has 2 boundaries (- =), gloss has 2 boundaries (- -)"]


def test_count_mismatch_message():
    result = igt.check_word("ros-am", "rose-ACC-SG")
    assert result["messages"] == ["segmentation has 1 boundary (-), gloss has 2 boundaries (- -)"]


# ---------------------------------------------------------------------------
# Category labels
# ---------------------------------------------------------------------------

LEIPZIG = igt.resolve_abbreviations("leipzig")


@pytest.mark.parametrize("gloss, unknown", [
    ("house-PL-LOC", []),
    ("go-PST-3SG", []),          # person + number run together
    ("be-NPST", []),             # Leipzig's N- (non-)
    ("say-PST.EVID", ["EVID"]),
    ("love-3-XSG=Q.PL", ["XSG"]),  # labels after "-" and "=" are checked too
    ("John-ACC", []),            # proper names are lexical
    ("Ø-3SG", []),
])
def test_unknown_labels_against_leipzig(gloss, unknown):
    assert igt.unknown_labels(gloss, LEIPZIG) == unknown


def test_no_abbreviations_means_no_check():
    assert igt.resolve_abbreviations(None) is None
    assert igt.unknown_labels("say-PST.EVID", None) == []


def test_own_list_can_extend_leipzig():
    known = igt.resolve_abbreviations(["leipzig", "EVID", "AOR"])
    assert igt.unknown_labels("say-AOR.EVID-PL", known) == []
    only_own = igt.resolve_abbreviations({"EVID": "evidential"})
    assert igt.unknown_labels("say-PST.EVID", only_own) == ["PST"]


def test_leipzig_list_has_the_core_labels():
    for label in ("1", "2", "3", "ACC", "ERG", "ABS", "PL", "SG", "DU", "PST", "FUT",
                  "NEG", "Q", "NMLZ", "PTCP", "CVB", "SBJV"):
        assert label in igt.LEIPZIG_ABBREVIATIONS


# ---------------------------------------------------------------------------
# The page script follows the same rules
# ---------------------------------------------------------------------------

PARITY_CASES = [
    ("ev-ler-de", "house-PL-LOC"), ("vir-um=que", "man-ACC.SG-and"), ("ros-am", "rose-ACC-SG"),
    ("s<um>ulat", "write<AV>"), ("s<um>ulat", "write"), ("ev--ler", "house--PL"),
    ("ev ler", "house PL"), ("", ""), ("ev", ""), ("", "x"), ("ev-ler", "house-"),
    ("a=b-c", "x=y-z.EVID"), ("Ø-x", "Ø-3SG.NPST"),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_script_matches_python():
    script = (
        "const c = require(process.argv[1]);"
        "const cases = JSON.parse(process.argv[2]); const known = JSON.parse(process.argv[3]);"
        "const item = JSON.parse(process.argv[4]); const cfg = JSON.parse(process.argv[5]);"
        "console.log(JSON.stringify({"
        "  checks: cases.map(([m, g]) => c.checkWord(m, g)),"
        "  unknown: cases.map(([m, g]) => c.unknownLabels(g, known)),"
        "  tokens: c.tokenizeSentence('«Veni,  vidi, vici!» -- ok'),"
        "  initial: c.initialAnswer(item, cfg)}));")
    item = {"text": "Puella rosam amat.", "m": ["puell-a", "ros-am"], "g": "girl-NOM.SG rose-ACC.SG",
            "t": "The girl loves the rose.", "pos": ["n", "n", "v"]}
    scheme = {"source_field": "text", "morphemes_field": "m", "gloss_field": "g",
              "translation_field": "t", "tiers": ["pos", "notes"]}
    cfg = {"sourceField": "text", "morphemesField": "m", "glossField": "g",
           "translationField": "t", "tiers": ["pos", "notes"]}
    out = subprocess.run(["node", "-e", script, str(JS), json.dumps(PARITY_CASES), json.dumps(LEIPZIG),
                          json.dumps(item), json.dumps(cfg)],
                         capture_output=True, text=True, check=True)
    js = json.loads(out.stdout)
    assert js["checks"] == [igt.check_word(m, g) for m, g in PARITY_CASES]
    assert js["unknown"] == [igt.unknown_labels(g, LEIPZIG) for _, g in PARITY_CASES]
    assert js["tokens"] == igt.tokenize_sentence("«Veni,  vidi, vici!» -- ok") == ["Veni", "vidi", "vici", "ok"]
    assert js["initial"] == igt.initial_answer(item, scheme)
    # Unglossed words start with the word as their segmentation.
    assert js["initial"]["words"][2] == {"word": "amat", "morphemes": "amat", "gloss": "",
                                         "pos": "v", "notes": ""}


# ---------------------------------------------------------------------------
# Scheme and config
# ---------------------------------------------------------------------------

def _scheme(**extra):
    scheme = {"annotation_type": "interlinear_gloss", "name": "igt", "description": "Gloss it"}
    scheme.update(extra)
    return scheme


def test_generator_renders_one_hidden_answer_and_the_resolved_list():
    html, keys = schema_registry.generate(_scheme(tiers=["pos"], abbreviations=["leipzig", "EVID"],
                                                  source_field="sentence"))
    assert keys == []
    assert 'data-annotation-type="interlinear_gloss"' in html
    assert html.count('type="hidden"') == 1 and 'name="igt:::igt"' in html
    raw = re.search(r"data-igt-config='([^']*)'", html).group(1)
    import html as _html
    cfg = json.loads(_html.unescape(raw))
    assert cfg["sourceField"] == "sentence" and cfg["tiers"] == ["pos"]
    assert "EVID" in cfg["abbreviations"] and "ERG" in cfg["abbreviations"]


@pytest.mark.parametrize("bad", [
    {"tiers": "pos"}, {"tiers": ["gloss"]}, {"tiers": ["pos", "pos"]}, {"tiers": ["has space"]},
    {"abbreviations": "standard"}, {"abbreviations": 3}, {"source_field": ""},
    {"show_translation": "yes"},
])
def test_config_validation_refuses(bad):
    with pytest.raises(ConfigValidationError):
        _validate_interlinear_gloss(_scheme(**bad), "annotation_schemes[0]")


def test_config_validation_accepts_the_example():
    config = yaml.safe_load((REPO / "examples/span/interlinear-gloss/config.yaml").read_text())
    for scheme in config["annotation_schemes"]:
        _validate_interlinear_gloss(scheme, "annotation_schemes[0]")


# ---------------------------------------------------------------------------
# FLExText
# ---------------------------------------------------------------------------

FLEXTEXT = """<?xml version="1.0" encoding="utf-8"?>
<document version="2">
  <interlinear-text guid="t1">
    <item type="title" lang="en">Illustrative Latin</item>
    <paragraphs>
      <paragraph guid="p1">
        <phrases>
          <phrase guid="ph1">
            <item type="segnum" lang="en">1</item>
            <words>
              <word guid="w1">
                <item type="txt" lang="la">Arma</item>
                <morphemes>
                  <morph type="stem"><item type="txt" lang="la">arm</item><item type="gls" lang="en">weapon</item><item type="msa" lang="en">n</item></morph>
                  <morph type="suffix"><item type="txt" lang="la">-a</item><item type="gls" lang="en">ACC.PL</item></morph>
                </morphemes>
                <item type="pos" lang="en">n</item>
              </word>
              <word guid="w2">
                <item type="txt" lang="la">virumque</item>
                <morphemes>
                  <morph type="stem"><item type="txt" lang="la">vir</item><item type="gls" lang="en">man</item></morph>
                  <morph type="suffix"><item type="txt" lang="la">-um</item><item type="gls" lang="en">ACC.SG</item></morph>
                  <morph type="enclitic"><item type="txt" lang="la">que</item><item type="gls" lang="en">and</item></morph>
                </morphemes>
                <item type="pos" lang="en">n</item>
              </word>
              <word guid="w3">
                <item type="txt" lang="la">cano</item>
                <morphemes>
                  <morph type="stem"><item type="txt" lang="la">can</item><item type="gls" lang="en">sing</item></morph>
                  <morph type="suffix"><item type="txt" lang="la">o</item><item type="gls" lang="en">1SG</item></morph>
                </morphemes>
              </word>
              <word><item type="punct" lang="la">.</item></word>
            </words>
            <item type="gls" lang="en">I sing of arms and the man.</item>
          </phrase>
          <phrase guid="ph2">
            <item type="segnum" lang="en">2</item>
            <words>
              <word>
                <item type="txt" lang="la">unpacked</item>
                <morphemes>
                  <morph type="prefix"><item type="txt" lang="la">un-</item><item type="gls" lang="en">REV</item></morph>
                  <morph type="stem"><item type="txt" lang="la">pack</item><item type="gls" lang="en">put in bag</item></morph>
                  <morph type="suffix"><item type="txt" lang="la">-ed</item><item type="gls" lang="en">PST</item></morph>
                </morphemes>
              </word>
            </words>
            <item type="gls" lang="en">(a made-up phrase)</item>
          </phrase>
        </phrases>
      </paragraph>
    </paragraphs>
    <languages>
      <language lang="la" vernacular="true"/>
      <language lang="en"/>
    </languages>
  </interlinear-text>
</document>
"""


def _write(name, filename, text):
    d = Path(create_test_directory(name))
    src = d / filename
    src.write_text(text, encoding="utf-8")
    return d, src


def _context(result, user="ann", answers=None):
    scheme = result.schemes[0]
    items = {it.instance_id: dict(it.fields, id=it.instance_id) for it in result.items}
    anns = []
    for it in result.items:
        answer = (answers or {}).get(it.instance_id) or igt.initial_answer(it.fields, scheme)
        anns.append({"user_id": user, "instance_id": it.instance_id,
                     "labels": {scheme["name"]: {scheme["name"]: json.dumps(answer)}}})
    return ExportContext(config={"annotation_task_name": "IGT test"}, annotations=anns,
                         items=items, schemas=result.schemes, output_dir="")


def _analysis(result):
    return [(it.fields["words"], it.fields["morphemes"], it.fields["glosses"],
             it.fields.get("translation"), it.fields.get("pos")) for it in result.items]


def test_flextext_import():
    d, src = _write("igt_flex_import", "aeneid.flextext", FLEXTEXT)
    assert projects.detect(str(src)) == "flextext"
    result = projects.IMPORTERS["flextext"].parse_path(src)
    scheme = result.schemes[0]
    assert scheme["annotation_type"] == "interlinear_gloss" and scheme["tiers"] == ["pos"]
    assert scheme["language"] == "la" and scheme["metalanguage"] == "en"
    first = result.items[0].fields
    assert first["text"] == "Arma virumque cano."           # punctuation kept in the sentence
    assert first["words"] == ["Arma", "virumque", "cano"]    # and left out of the words
    # Unmarked morph forms take their boundary from the morph type.
    assert first["morphemes"] == ["arm-a", "vir-um=que", "can-o"]
    assert first["glosses"] == ["weapon-ACC.PL", "man-ACC.SG=and", "sing-1SG"]
    assert first["pos"] == ["n", "n", ""]
    second = result.items[1].fields
    assert second["morphemes"] == ["un-pack-ed"]
    assert second["glosses"] == ["REV-put.in.bag-PST"]       # rule 4: spaces become "."
    assert all(igt.check_word(m, g)["status"] == "ok"
               for it in result.items for m, g in zip(it.fields["morphemes"], it.fields["glosses"]))


def test_flextext_round_trip_keeps_corrections():
    d, src = _write("igt_flex_round", "aeneid.flextext", FLEXTEXT)
    result = projects.IMPORTERS["flextext"].parse_path(src)
    scheme = result.schemes[0]
    corrected = igt.initial_answer(result.items[0].fields, scheme)
    corrected["words"][2]["gloss"] = "sing-1SG.PRS"
    ctx = _context(result, answers={result.items[0].instance_id: corrected})
    res = FlexTextExporter().export(ctx, str(d / "out"))
    assert res.success and res.files_written == [str(d / "out" / "ann.flextext")]
    xml = Path(res.files_written[0]).read_text(encoding="utf-8")
    assert '<morph type="enclitic">' in xml and '<morph type="prefix">' in xml
    again = projects.IMPORTERS["flextext"].parse_path(Path(res.files_written[0]))
    before = _analysis(result)
    before[0][2][2] = "sing-1SG.PRS"
    after = _analysis(again)
    assert [a[:4] for a in after] == [b[:4] for b in before]
    assert after[0][4] == ["n", "n", ""]
    assert again.items[0].fields["text_title"] == "Illustrative Latin"


# Audit 97 T8: every unreadable file used to end in "no phrases with words".

BOMB = ('<?xml version="1.0"?>\n<!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
        + "".join(f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(7))
        + ']>\n<document><interlinear-text><item type="title">&h;</item>'
          '</interlinear-text></document>\n')


@pytest.mark.parametrize("payload,match", [
    (bytes(range(256)) * 8, "is binary, not text"),
    ("<document><interlinear-text>caf\xe9</interlinear-text></document>".encode("latin-1")
     + b"\x81\x82" * 4, "is not UTF-8 text"),
    (FLEXTEXT[:FLEXTEXT.index("</words>")].encode("utf-8"), r"not well-formed XML \(.*line \d+"),
    (BOMB.encode("utf-8"), "entit"),
], ids=["binary", "latin-1", "truncated", "entity-bomb"])
def test_flextext_unreadable_files_say_why(payload, match):
    d = Path(create_test_directory("igt_flex_unreadable"))
    src = d / "bad.flextext"
    src.write_bytes(payload)
    with pytest.raises(ValueError, match=f"bad.flextext.*{match}"):
        projects.IMPORTERS["flextext"].parse_path(src)


def test_entity_bomb_is_refused_without_defusedxml(monkeypatch):
    """Plain expat (no defusedxml) must not expand it either."""
    import xml.etree.ElementTree as ET
    from potato.importers.projects import interlinear
    monkeypatch.setattr(interlinear, "_xml_fromstring", ET.fromstring)
    d, src = _write("igt_flex_bomb_expat", "bomb.flextext",
                    BOMB.replace("&h;", "&h;&h;&h;&h;&h;&h;&h;&h;&h;&h;"))
    with pytest.raises(ValueError, match="bomb.flextext.*entit"):
        projects.IMPORTERS["flextext"].parse_path(src)


def test_cli_names_a_non_utf8_single_file(capsys):
    from potato.importers.cli import main
    d = Path(create_test_directory("igt_cli_binary"))
    src = d / "bad.flextext"
    src.write_bytes(b"\x00\xef\xfe" + bytes(range(128, 256)) * 4)
    assert main(["-i", str(src), "-o", str(d / "out")]) == 2
    assert "is not UTF-8 text" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------

TOOLBOX = r"""\_sh v3.0  400  Text
\id illustrative

\ref lat.001
\tx Arma           virumque          cano.
\mb arm    -a      vir -um     =que  can  -o
\ge weapon -ACC.PL man -ACC.SG =and  sing -1SG
\ps n      -case   n   -case   =conj v    -pers
\ft I sing of arms and the man.
\nt Aeneid 1.1

\ref lat.002
\tx Puella rosam amat
\mb puell -a ros -am ama -t
\ge girl -NOM.SG rose -ACC.SG love -3SG
\ft The girl loves
the rose.
"""


def test_toolbox_import_reads_aligned_and_unaligned_records():
    d, src = _write("igt_tb_import", "latin.txt", TOOLBOX)
    assert projects.detect(str(src)) == "toolbox"
    result = projects.IMPORTERS["toolbox"].parse_path(src)
    assert [it.instance_id for it in result.items] == ["lat.001", "lat.002"]
    a, b = (it.fields for it in result.items)
    assert a["morphemes"] == ["arm-a", "vir-um=que", "can-o"]
    assert a["glosses"] == ["weapon-ACC.PL", "man-ACC.SG=and", "sing-1SG"]
    assert a["pos"] == ["n-case", "n-case=conj", "v-pers"]
    assert a["sfm_extra"] == {"nt": "Aeneid 1.1"}
    # Not column-aligned: read by the - and = marks and in order instead.
    assert b["morphemes"] == ["puell-a", "ros-am", "ama-t"]
    assert b["glosses"] == ["girl-NOM.SG", "rose-ACC.SG", "love-3SG"]
    assert b["translation"] == "The girl loves the rose."     # continuation line joined


def test_toolbox_markers_are_configurable():
    renamed = (TOOLBOX.replace("\\tx ", "\\t  ").replace("\\mb ", "\\m  ")
               .replace("\\ge ", "\\gl ").replace("\\ft ", "\\fe "))
    d, src = _write("igt_tb_markers", "latin.sfm", renamed)
    result = projects.IMPORTERS["toolbox"].parse_path(
        src, {"markers": {"gloss": "gl", "translation": ["fe"]}})
    assert result.items[0].fields["glosses"][1] == "man-ACC.SG=and"
    assert result.items[0].fields["translation"] == "I sing of arms and the man."
    # Without the option, \gl is not a gloss line.
    plain = projects.IMPORTERS["toolbox"].parse_path(src)
    assert plain.items[0].fields["glosses"] == ["", "", ""]
    with pytest.raises(ValueError):
        projects.IMPORTERS["toolbox"].parse_path(src, {"markers": {"lemma": "lx"}})


def test_toolbox_round_trip():
    d, src = _write("igt_tb_round", "latin.txt", TOOLBOX)
    result = projects.IMPORTERS["toolbox"].parse_path(src)
    res = ToolboxExporter().export(_context(result), str(d / "out"))
    assert res.success and not res.warnings
    text = Path(res.files_written[0]).read_text(encoding="utf-8")
    lines = text.splitlines()
    tx = next(l for l in lines if l.startswith("\\tx"))
    mb = next(l for l in lines if l.startswith("\\mb"))
    # Columns: each word starts where its first morpheme starts.
    assert [m.start() for m in re.finditer(r"\S+", tx)][1:] == [mb.index("arm"), mb.index("vir"), mb.index("can")]
    assert "\\nt Aeneid 1.1" in lines
    again = projects.IMPORTERS["toolbox"].parse_path(Path(res.files_written[0]))
    assert _analysis(again) == _analysis(result)
    assert again.items[0].fields["sfm_extra"] == {"nt": "Aeneid 1.1"}


SPECIAL = r"50% of <cases> & $x_y \ {a}"


def test_toolbox_keeps_tier_text_as_written():
    """Audit 97 T9: tier text came out as 50%_of_<cases>_&_$x_y_\\_{a}."""
    d, src = _write("igt_tb_special", "latin.txt", TOOLBOX)
    result = projects.IMPORTERS["toolbox"].parse_path(src)
    scheme = dict(result.schemes[0], tiers=["pos", "notes", "lit"])
    result.schemes = [scheme]
    answer = igt.initial_answer(result.items[0].fields, scheme)
    answer["words"][0]["notes"] = SPECIAL       # spaces: cannot be an aligned cell
    answer["words"][0]["lit"] = "x_y"           # one token per word: stays aligned
    answer["words"][1]["lit"] = "$5\\"
    answer["translation"] = SPECIAL + "\n\\ft injected"
    res = ToolboxExporter().export(_context(result, answers={result.items[0].instance_id: answer}),
                                   str(d / "out"))
    lines = Path(res.files_written[0]).read_text(encoding="utf-8").splitlines()
    assert f"\\notes Arma: {SPECIAL}" in lines
    lit = next(l for l in lines if l.startswith("\\lit"))
    assert lit.split()[1:3] == ["x_y", "$5\\"]
    assert not any(l.startswith("\\ft injected") for l in lines)
    again = projects.IMPORTERS["toolbox"].parse_path(Path(res.files_written[0]))
    first = again.items[0].fields
    assert first["translation"] == SPECIAL + " \\ft injected"
    assert first["sfm_extra"]["notes"] == f"Arma: {SPECIAL}"
    assert first["sfm_extra"]["nt"] == "Aeneid 1.1"
    assert [a[:3] for a in _analysis(again)] == [a[:3] for a in _analysis(result)]
    # Toolbox -> Potato -> Toolbox leaves the extra fields as they were.
    res2 = ToolboxExporter().export(_context(again), str(d / "out2"))
    lines2 = Path(res2.files_written[0]).read_text(encoding="utf-8").splitlines()
    assert f"\\notes Arma: {SPECIAL}" in lines2


def test_misaligned_word_is_written_whole_and_counted():
    d, src = _write("igt_tb_bad", "latin.txt", TOOLBOX)
    result = projects.IMPORTERS["toolbox"].parse_path(src)
    bad = igt.initial_answer(result.items[0].fields, result.schemes[0])
    bad["words"][1]["gloss"] = "man-ACC.SG-and"
    res = ToolboxExporter().export(_context(result, answers={"lat.001": bad}), str(d / "out"))
    assert res.stats["num_misaligned_words"] == 1 and res.warnings
    assert "man-ACC.SG-and" in Path(res.files_written[0]).read_text(encoding="utf-8")


def test_imported_project_is_a_valid_config():
    d, src = _write("igt_tb_project", "latin.txt", TOOLBOX)
    result = projects.IMPORTERS["toolbox"].parse_path(src)
    write_project(result, str(d / "project"), source=str(src))
    config = yaml.safe_load((d / "project" / "config.yaml").read_text())
    scheme = config["annotation_schemes"][0]
    assert scheme["annotation_type"] == "interlinear_gloss"
    _validate_interlinear_gloss(scheme, "annotation_schemes[0]")
    row = json.loads((d / "project" / "data" / "latin.jsonl").read_text().splitlines()[0])
    assert row["glosses"][1] == "man-ACC.SG=and"
    # The analysis is read from the item, not stored as anybody's answer.
    assert "pre_annotation" not in config


# ---------------------------------------------------------------------------
# igt.txt and igt.tex
# ---------------------------------------------------------------------------

def test_plain_text_columns_line_up_with_combining_marks():
    d, src = _write("igt_txt", "latin.txt", TOOLBOX)
    result = projects.IMPORTERS["toolbox"].parse_path(src)
    answer = igt.initial_answer(result.items[0].fields, result.schemes[0])
    answer["words"][0]["word"] = "Armá"           # a combining accent takes no column
    res = IGTExporter().export(_context(result, answers={"lat.001": answer}), str(d / "out"))
    txt = Path(d / "out" / "igt.txt").read_text(encoding="utf-8").splitlines()
    block = txt[1:4]
    starts = [[igt.display_width(line[:m.start()]) for m in re.finditer(r"\S+", line)] for line in block]
    # The first line also carries the example number "(1)".
    assert starts[0][1:] == starts[1] == starts[2]
    assert txt[4].strip() == "'I sing of arms and the man.'"
    assert (d / "out" / "igt.tex").exists()


def test_latex_special_characters_are_escaped():
    assert latex_escape(r"a_b%c&d#e$f{g}h~i^j\k<l>") == (
        r"a\_b\%c\&d\#e\$f\{g\}h\textasciitilde{}i\textasciicircum{}j\textbackslash{}k"
        r"\textless{}l\textgreater{}")
    assert latex_gloss("house-PL=and") == r"house-\textsc{pl}=and"
    assert latex_gloss("go_out-3SG.PST") == r"go\_out-\textsc{3sg}.\textsc{pst}"
    lines = gb4e_example({"words": [{"word": "x", "morphemes": "50%", "gloss": "[A]"},
                                    {"word": "y", "morphemes": "y", "gloss": ""}],
                          "translation": "R&D costs $5"}, comment="x_1")
    assert lines[0] == r"\ex % x_1"
    assert lines[1] == r"\gll 50\% y\\"
    # A cell starting with "[" is braced (gb4e reads it as an option); an empty one is {}.
    assert lines[2].split() == [r"{[\textsc{a}]}", r"{}\\"]
    assert lines[3] == r"\glt `R\&D costs \$5'"


def test_exporters_refuse_a_project_without_the_scheme():
    ctx = ExportContext(config={}, annotations=[], items={}, schemas=[{"annotation_type": "radio",
                                                                         "name": "x"}], output_dir="")
    for exporter in (FlexTextExporter(), ToolboxExporter(), IGTExporter()):
        ok, why = exporter.can_export(ctx)
        assert not ok and "interlinear_gloss" in why
