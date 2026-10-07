"""
Offsets and stored values read back by different code than wrote them: the
exporter against the browser's text, the server-rendered highlights against
sanitized markup, and the page's own restore code run in jsdom against the
markup the generators emit.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Offsets span-core produced against the DOM for "TARGET" in each text.
SPAN_CASES = {
    "ent": ("R&amp;D team TARGET here", 9, 15),
    "lt": ("if x < y and y > z then TARGET wins", 24, 30),
    "ws": ("two  spaces\nnewline TARGET end", 19, 25),
    "tag": ("<b>bold</b> then TARGET", 10, 16),
    "emoji": ("fire 🔥🔥 then TARGET ok", 13, 19),
}


class TestExportedSpanText:
    def test_the_export_reads_the_words_the_annotator_marked(self):
        from potato.export.base import ExportContext
        ctx = ExportContext(config={"item_properties": {"text_key": "text"}}, annotations=[],
                            items={k: {"text": v[0]} for k, v in SPAN_CASES.items()},
                            schemas=[], output_dir=".")
        got = {k: ctx.covered_text(k, {"start": s, "end": e})
               for k, (_, s, e) in SPAN_CASES.items()}
        assert got == {k: "TARGET" for k in SPAN_CASES}


class TestMarkupOffsets:
    def test_each_offset_lands_on_its_character(self):
        from potato.server_utils.html_sanitizer import sanitize_html
        from potato.server_utils.span_text import dom_to_markup_offsets, markup_text
        markup = str(sanitize_html("a&amp;<b>bc</b> x &lt; y"))
        text = markup_text(markup)
        starts, ends = dom_to_markup_offsets(markup)
        assert len(starts) == len(ends) == len(text) + 1
        for i in range(len(text)):
            # The markup between a character's start and its end is that character.
            assert markup_text(markup[starts[i]:ends[i + 1]]) == text[i]

    def test_crossing_spans_cover_exactly_their_characters(self):
        import potato.server_utils.schemas.span as span_mod
        from html.parser import HTMLParser
        span_mod.get_span_color = lambda schema, name: "(1, 2, 3)"
        html = span_mod.render_span_annotations("alpha beta gamma delta", [
            {"id": "P", "schema": "s", "name": "PER", "start": 0, "end": 10},
            {"id": "O", "schema": "s", "name": "ORG", "start": 6, "end": 16}])

        class Walk(HTMLParser):
            def __init__(self):
                super().__init__()
                self.open, self.cover = [], []

            def handle_starttag(self, tag, attrs):
                self.open.append(dict(attrs)["data-label"])

            def handle_endtag(self, tag):
                self.open.pop()

            def handle_data(self, data):
                self.cover += [set(self.open)] * len(data)
        walk = Walk()
        walk.feed(html)
        assert walk.cover == [{"PER"}] * 6 + [{"PER", "ORG"}] * 4 + [{"ORG"}] * 6 + [set()] * 6


# ---------------------------------------------------------------------------
# The page's own code, run against generated markup
# ---------------------------------------------------------------------------

NODE = r"""
const fs = require('fs'), path = require('path');
const {JSDOM} = require(path.resolve('node_modules/jsdom'));
const src = fs.readFileSync('potato/static/annotation.js', 'utf8');
const spanCore = fs.readFileSync('potato/static/span-core.js', 'utf8');
function fn(source, name) {
  const at = source.indexOf('function ' + name + '(');
  let i = source.indexOf('{', at), depth = 0;
  for (let j = i; j < source.length; j++) {
    if (source[j] === '{') depth++;
    else if (source[j] === '}' && --depth === 0) return source.slice(at, j + 1);
  }
}
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};

// Ranking: the generator's own inline script restores the stored order.
{
  const dom = new JSDOM(`<body>${cases.ranking}</body>`, {runScripts: 'dangerously'});
  out.ranking = [...dom.window.document.querySelectorAll('.ranking-item')]
    .map(i => i.getAttribute('data-value'));
}
// Hierarchical multiselect: annotation.js's restore pass.
{
  const dom = new JSDOM(`<body>${cases.hier}</body>`, {runScripts: 'dangerously'});
  dom.window.eval('var currentAnnotations = ' + JSON.stringify(cases.hierStored) +
                  '; function debugLog(){}\n' + fn(src, 'splitKnownValues') + '\n' +
                  fn(src, 'restoreHierarchicalAnnotations') + '\nrestoreHierarchicalAnnotations();');
  out.hier = [...dom.window.document.querySelectorAll('.hier-checkbox')]
    .filter(c => c.checked).map(c => c.value);
}
// Save payload: keyword overlays are not spans, and an empty multiselect is named.
{
  const dom = new JSDOM(`<body>
    <form data-annotation-type="multiselect" data-schema-name="tags"></form>
    <form data-annotation-type="multiselect" data-schema-name="topics"></form>
    <div class="span-overlay ai-keyword-overlay"></div>
    <div class="span-overlay" data-schema="ent" data-label="X" data-start="0" data-end="3"></div>
  </body>`, {runScripts: 'dangerously'});
  dom.window.eval('function debugLog(){}\n' + fn(src, 'extractSpanAnnotationsFromDOM') + '\n' +
                  fn(src, 'clearedMultiselectSchemas'));
  out.spans = dom.window.extractSpanAnnotationsFromDOM().map(s => s.schema);
  out.cleared = dom.window.clearedMultiselectSchemas({'topics:a': 'a'});
}
// span-core: a marked basis is used exactly as written.
{
  const at = spanCore.indexOf('getCanonicalText() {');
  let i = spanCore.indexOf('{', at), depth = 0, end = -1;
  for (let j = i; j < spanCore.length; j++) {
    if (spanCore[j] === '{') depth++;
    else if (spanCore[j] === '}' && --depth === 0) { end = j + 1; break; }
  }
  const dom = new JSDOM(`<body><div id="t" data-offset-basis="dom"></div></body>`);
  const el = dom.window.document.getElementById('t');
  el.setAttribute('data-original-text', 'a <b>  x\n y');
  const method = eval('(function ' + spanCore.slice(at, end) + ')');
  out.canonical = method.call({container: el, normalizeText: t => t.replace(/\s+/g, ' ').trim()});
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not shutil.which("node") or not os.path.isdir(os.path.join(REPO, "node_modules", "jsdom")),
                    reason="needs node and jsdom")
class TestPageRestoreCode:
    @pytest.fixture(scope="class")
    def results(self):
        from potato.server_utils.schemas.hierarchical_multiselect import (
            generate_hierarchical_multiselect_layout)
        from potato.server_utils.schemas.ranking import generate_ranking_layout
        ranking, _ = generate_ranking_layout({
            "name": "city", "annotation_type": "ranking", "description": "d",
            "labels": ["Oslo", "Paris, France", "Rome"]})
        # What the server's restore writes into the hidden input.
        ranking = re.sub(r'(id="city_rank_order_hidden"[^>]*?)value=""',
                         r'\1value="Rome,Oslo,Paris, France"', ranking, flags=re.S)
        hier, _ = generate_hierarchical_multiselect_layout({
            "name": "hm", "annotation_type": "hierarchical_multiselect", "description": "d",
            "taxonomy": {"Zero-shot, few-shot": [], "Other": []}})
        work = create_test_directory("tg2_page_restore")
        cases = os.path.join(work, "cases.json")
        script = os.path.join(work, "probe.js")
        with open(cases, "w") as f:
            json.dump({"ranking": ranking, "hier": hier,
                       "hierStored": {"hm": {"selected_labels": "Zero-shot, few-shot"}}}, f)
        with open(script, "w") as f:
            f.write(NODE)
        out = subprocess.run(["node", script, cases], cwd=REPO, capture_output=True,
                             text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_a_ranking_option_with_a_comma_keeps_its_place(self, results):
        assert results["ranking"] == ["Rome", "Oslo", "Paris, France"]

    def test_a_hierarchical_label_with_a_comma_is_ticked_again(self, results):
        assert results["hier"] == ["Zero-shot, few-shot"]

    def test_keyword_overlays_are_not_posted_as_spans(self, results):
        assert results["spans"] == ["ent"]

    def test_an_empty_multiselect_is_named_in_the_save(self, results):
        assert results["cleared"] == ["tags"]

    def test_a_marked_offset_basis_is_used_as_written(self, results):
        assert results["canonical"] == "a <b>  x\n y"
