"""Math rendering: the `math` config block, the browser-side delimiter scanner,
the vendored KaTeX files, and the JSON data elements the page carries."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from potato.math_rendering import (
    DEFAULT_DELIMITERS,
    MathConfigError,
    get_math_client_config,
    math_span_conflicts,
    validate_math_config,
)
from potato.server_utils.config_module import ConfigValidationError, validate_yaml_structure

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "potato" / "static"
KATEX_DIR = STATIC / "vendor" / "katex-0.18.11"


def config(**extra):
    base = {
        "item_properties": {"id_key": "id", "text_key": "text"},
        "task_dir": ".", "output_annotation_dir": "out", "annotation_task_name": "t",
        "data_files": ["data.jsonl"],
        "annotation_schemes": [{"annotation_type": "radio", "name": "r",
                                "description": "d", "labels": ["a", "b"]}],
    }
    base.update(extra)
    return base


DISPLAY = {"fields": [
    {"key": "problem", "type": "text"},
    {"key": "proof", "type": "text", "span_target": True},
]}
SPAN = {"annotation_type": "span", "name": "s", "description": "d", "labels": ["x"]}


# --------------------------------------------------------------------------- config

class TestValidation:
    @pytest.mark.parametrize("block, message", [
        ("yes", "must be a mapping"),
        ({"enabled": "true"}, "math.enabled must be true or false"),
        ({"enabled": True, "delimiters": []}, "non-empty list"),
        ({"enabled": True, "delimiters": "$"}, "non-empty list"),
        ({"enabled": True, "delimiters": ["$", "%"]}, r"unsupported value\(s\) \['%'\]"),
        ({"enabled": True, "delimiters": ["$", "$"]}, "twice"),
        ({"enabled": True, "fields": "problem"}, "list of instance_display field keys"),
        ({"enabled": True, "fields": ["problem"]}, "no instance_display.fields"),
        ({"enabled": True, "macros": ["\\R"]}, "must be a mapping"),
        ({"enabled": True, "macros": {"R": "\\mathbb{R}"}}, "backslash followed by letters"),
        ({"enabled": True, "macros": {"\\R": 3}}, "must be a string"),
        ({"enabled": True, "renderer": "mathjax"}, "unknown key"),
    ])
    def test_bad_values_are_refused_by_the_loader(self, block, message):
        with pytest.raises(ConfigValidationError, match=message):
            validate_yaml_structure(config(math=block))

    def test_fields_must_name_display_fields(self):
        with pytest.raises(MathConfigError, match=r"\['nope'\].*problem, proof"):
            validate_math_config(config(instance_display=DISPLAY,
                                        math={"enabled": True, "fields": ["nope"]}))

    def test_a_good_block_validates(self):
        cfg = config(instance_display=DISPLAY,
                     math={"enabled": True, "delimiters": ["$$", "\\("],
                           "fields": ["problem"], "macros": {"\\R": "\\mathbb{R}"}})
        validate_yaml_structure(cfg)
        assert validate_math_config(cfg) == []

    def test_span_target_field_is_named_in_a_warning(self, caplog):
        cfg = config(instance_display=DISPLAY, math={"enabled": True})
        warnings = validate_math_config(cfg)
        assert len(warnings) == 1 and "'proof' is a span target" in warnings[0]
        assert "'proof' is a span target" in caplog.text

    def test_legacy_text_with_a_span_scheme_is_named_in_a_warning(self):
        cfg = config(annotation_schemes=[SPAN], math={"enabled": True})
        (warning,) = math_span_conflicts(cfg)
        assert "text-selection scheme (span)" in warning

    def test_no_warning_when_math_is_off(self):
        cfg = config(annotation_schemes=[SPAN], math={"enabled": False})
        assert validate_math_config(cfg) == []


class TestClientConfig:
    def test_off_unless_enabled_is_true(self):
        assert get_math_client_config(config()) is None
        assert get_math_client_config(config(math={})) is None
        assert get_math_client_config(config(math={"enabled": False})) is None

    def test_defaults_and_longest_first_order(self):
        out = get_math_client_config(config(math={"enabled": True}))
        assert [d["left"] for d in out["delimiters"]] == ["$$", "\\[", "\\(", "$"]
        assert [d["display"] for d in out["delimiters"]] == [True, True, False, False]
        assert sorted(DEFAULT_DELIMITERS) == sorted(d["left"] for d in out["delimiters"])
        assert out["instance_text"] is True and out["fields"] is None and out["macros"] == {}

    def test_subset_of_delimiters(self):
        out = get_math_client_config(config(math={"enabled": True, "delimiters": ["$", "\\["]}))
        assert [(d["left"], d["right"]) for d in out["delimiters"]] == [("\\[", "\\]"), ("$", "$")]

    def test_item_text_is_left_alone_for_text_selection_schemes(self):
        for atype in ("span", "span_link", "coreference", "error_span",
                      "event_annotation", "extractive_qa", "text_edit"):
            scheme = dict(SPAN, annotation_type=atype)
            out = get_math_client_config(config(annotation_schemes=[scheme], math={"enabled": True}))
            assert out["instance_text"] is False, atype

    def test_item_text_is_not_a_target_under_instance_display(self):
        out = get_math_client_config(config(instance_display=DISPLAY, math={"enabled": True}))
        assert out["instance_text"] is False


# --------------------------------------------------------------------------- scanner

NODE = shutil.which("node")

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {console, document: {readyState: 'loading', addEventListener() {}}, window: {}};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const delims = JSON.parse(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(t => ctx.window.PotatoMath.scan(t, delims))));
"""


def scan_all(texts, delimiters=None):
    if NODE is None:
        pytest.skip("node is not installed")
    delims = delimiters or get_math_client_config(config(math={"enabled": True}))["delimiters"]
    out = subprocess.run(
        [NODE, "-e", _HARNESS, str(STATIC / "potato-math.js"), json.dumps(delims)],
        input=json.dumps(texts), capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def summary(segments):
    """('t', text) / ('$', '$') / ('m', tex) / ('M', tex) for display math."""
    out = []
    for s in segments:
        if s["type"] == "text":
            out.append(("t", s["value"]))
        elif s["type"] == "literal":
            out.append(("$", s["value"]))
        else:
            out.append(("M" if s["display"] else "m", s["tex"]))
    return out


class TestScanner:
    CASES = {
        "Let $x^2$ be": [("t", "Let "), ("m", "x^2"), ("t", " be")],
        "$$\\int_0^1 f$$": [("M", "\\int_0^1 f")],
        "a \\(b\\) c \\[d\\]": [("t", "a "), ("m", "b"), ("t", " c "), ("M", "d")],
        # Prices: the closing $ follows a space, so neither opener closes.
        "$5 and $10": [("t", "$5 and $10")],
        # The first unescaped $ after "$5" cannot close, so "$5" is a price
        # and "$x$" is still math.
        "costs $5 and $x$ here": [("t", "costs $5 and "), ("m", "x"), ("t", " here")],
        "\\$5 and \\$10": [("$", "$"), ("t", "5 and "), ("$", "$"), ("t", "10")],
        "$ x$": [("t", "$ x$")],
        "$x $": [("t", "$x $")],
        "$x$5": [("t", "$x$5")],
        "$a\\$b$": [("m", "a\\$b")],
        "$\\{1\\}$": [("m", "\\{1\\}")],
        "$$ $$": [("t", "$$ $$")],
        "no math": [("t", "no math")],
        "$a\n\nb$": [("t", "$a\n\nb$")],
    }

    def test_cases(self):
        texts = list(self.CASES)
        for text, got in zip(texts, scan_all(texts)):
            assert summary(got) == self.CASES[text], text

    def test_source_is_kept_for_the_error_fallback(self):
        (segs,) = scan_all(["see \\[x\\] now"])
        assert segs[1]["source"] == "\\[x\\]"

    def test_dollar_off_leaves_dollars_alone(self):
        delims = get_math_client_config(config(math={"enabled": True,
                                                     "delimiters": ["\\(", "\\["]}))["delimiters"]
        (segs,) = scan_all(["$x$ and \\$5 and \\(y\\)"], delims)
        assert summary(segs) == [("t", "$x$ and \\$5 and "), ("m", "y")]


# --------------------------------------------------------------------------- assets

def test_katex_fonts_referenced_as_woff2_are_vendored():
    css = (KATEX_DIR / "katex.min.css").read_text()
    woff2 = set(re.findall(r"url\((fonts/[^)]+\.woff2)\)", css))
    assert len(woff2) == 20
    missing = [f for f in woff2 if not (KATEX_DIR / f).exists()]
    assert not missing
    # Every @font-face lists woff2 first, so a browser never asks for the
    # woff/ttf files that are not vendored.
    for face in re.findall(r"@font-face\{[^}]*\}", css):
        first = re.search(r"src:url\(([^)]+)\)", face).group(1)
        assert first.endswith(".woff2"), face


def test_katex_files_are_in_the_vendor_manifest():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vendor_assets", REPO / "scripts" / "vendor_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    katex = [a for a in mod.ASSETS if "katex-0.18.11" in str(a.path)]
    on_disk = {p for p in KATEX_DIR.rglob("*") if p.is_file()}
    assert {a.path for a in katex} == on_disk
    assert all(mod.check(a) for a in katex)


def test_template_gates_katex_on_the_math_config():
    text = (REPO / "potato" / "templates" / "base_template_v2.html").read_text()
    for needle in ("vendor/katex-0.18.11/katex.min.js", "vendor/katex-0.18.11/katex.min.css",
                   "potato-math.js", 'id="potato-math-config"'):
        i = text.index(needle)
        gate = text.rfind("{% if", 0, i)
        assert "math_client_config" in text[gate:i], needle


# --------------------------------------------------------------------------- JSON data elements

class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self._in = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append([dict(attrs), ""])
            self._in = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.scripts[-1][1] += data


def test_item_data_cannot_close_its_json_script_element():
    from potato.flask_server import _json_script_elements
    values = {
        "instance": {"text": "a </script><script>window.x=1</script> & <b>"},
        "suggestions": ["</SCRIPT >", "<!--", "&amp;"],
    }
    html = _json_script_elements(values)
    parser = _Scripts()
    parser.feed(html)
    assert [s[0].get("id") for s in parser.scripts] == ["instance", "suggestions"]
    assert all(s[0].get("type") == "application/json" for s in parser.scripts)
    # Two elements, not more: nothing in the data started a script of its own.
    assert [json.loads(s[1]) for s in parser.scripts] == list(values.values())
