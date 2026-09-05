"""Regressions for the findings in POTATO-BUGS-audit-22.

1  A span drawn on the last paragraph of a `document` field was silently not
   recorded. The display wrote a whitespace-collapsed `data-original-text`
   while the DOM kept the raw newlines (the field carries
   `white-space: pre-wrap`), so span offsets counted characters the bounds
   check did not have. Every span reaching into the tail was refused with no
   error, and every span that WAS accepted came back with text sliced one
   character early per collapsed run.
2  `data_directory` skipped files it could not read and said so only as
   `Loaded 0 instances` at INFO, so a wrong extension or a typo'd directory
   produced a clean boot and an empty study.
"""

import json
import logging
import re
import shutil
import subprocess

import pytest


# ---------------------------------------------------------------------------
# 1. The document span basis.
# ---------------------------------------------------------------------------
class TestDocumentDomText:
    """`document_dom_text()` is the contract: what the browser will hold."""

    def test_newlines_survive_when_the_display_preserves_them(self):
        from potato.server_utils.displays.base import document_dom_text
        assert document_dom_text("a\n\nb") == "a\n\nb"

    def test_whitespace_collapses_when_preserve_structure_is_off(self):
        from potato.server_utils.displays.base import document_dom_text
        assert document_dom_text(
            "a\n\nb", {"preserve_structure": False}) == "a b"

    def test_block_markup_collapses_because_the_class_is_not_applied(self):
        """Applying pre-wrap to converted HTML would double every gap between
        tags, so the display does not -- and the basis must follow."""
        from potato.server_utils.displays.base import document_dom_text
        assert "\n" not in document_dom_text("<p>a</p>\n<p>b</p>")

    def test_entities_are_decoded(self):
        """`&amp;` is five characters in the markup and one in the DOM. An
        offset basis that counts the markup form is wrong by four per
        ampersand."""
        from potato.server_utils.displays.base import document_dom_text
        assert document_dom_text("Tom &amp; Jerry") == "Tom & Jerry"
        assert document_dom_text("Tom & Jerry") == "Tom & Jerry"

    def test_tags_are_stripped(self):
        from potato.server_utils.displays.base import document_dom_text
        assert document_dom_text("<em>a</em> b") == "a b"


class TestDisplayAndContractAgree:
    """Two implementations of one basis is how this drifted in the first
    place. They must produce the same string character for character."""

    @pytest.mark.parametrize("raw", [
        "a\n\nb",
        "Tenancy\n\nThe landlord & co.\n\nEnd.",
        "plain text with no breaks",
        "<p>Alpha</p><p>Beta</p>",
        "trailing break\n\n",
        "  leading space",
    ])
    def test_data_original_text_matches_the_contract(self, raw):
        import html as html_module
        from potato.server_utils.displays.base import document_dom_text
        from potato.server_utils.displays.document_display import DocumentDisplay

        rendered = DocumentDisplay().render(
            {"key": "document", "type": "document", "span_target": True}, raw)
        match = re.search(r'data-original-text="([^"]*)"', rendered)
        assert match, "span_target fields must publish an offset basis"
        assert html_module.unescape(match.group(1)) == document_dom_text(raw)


class TestSpansReachTheEndOfADocument:
    """The reported symptom, stated against offsets rather than the DOM."""

    RAW = ("Tenancy Agreement Review\n\n"
           "The landlord shall maintain the premises.\n\n"
           "This clause takes effect once the deposit is verified.")

    def test_the_basis_is_as_long_as_the_raw_text(self):
        """It was three characters shorter -- one per collapsed break -- and
        those three characters are the tail of the last paragraph."""
        from potato.server_utils.displays.base import document_dom_text
        assert len(document_dom_text(self.RAW)) == len(self.RAW)

    def test_an_offset_reaching_the_final_character_is_in_bounds(self):
        from potato.server_utils.displays.base import document_dom_text
        basis = document_dom_text(self.RAW)
        start = self.RAW.index("This clause")
        assert basis[start:len(self.RAW)] == self.RAW[start:]

    def test_offsets_anchor_to_the_raw_value_with_newlines_counted(self):
        from potato.server_utils.displays.base import document_dom_text
        basis = document_dom_text(self.RAW)
        start = self.RAW.index("The landlord")
        assert basis[start:start + 12] == "The landlord"


class TestExporterAnchorsDocumentSpans:
    """`covered_text` returned the raw field value, which is right only for a
    document that happens to be plain text with no markup and no entities."""

    def _context(self, item, field_config=None):
        from potato.export.base import ExportContext
        field_config = field_config or {
            "key": "document", "type": "document", "span_target": True}
        return ExportContext(
            config={"instance_display": {"fields": [field_config]},
                    "item_properties": {"id_key": "id", "text_key": "document"}},
            annotations=[], items={"d": item}, schemas=[], output_dir=".")

    def test_a_span_at_the_end_of_a_document_exports_its_words(self):
        raw = "Alpha beta\n\nGamma delta"
        ctx = self._context({"id": "d", "document": raw})
        got = ctx.covered_text(
            "d", {"start": raw.index("Gamma"), "end": len(raw),
                  "target_field": "document"})
        assert got == "Gamma delta"

    def test_a_span_after_a_break_is_not_shifted(self):
        raw = "Alpha beta\n\nGamma delta"
        ctx = self._context({"id": "d", "document": raw})
        got = ctx.covered_text(
            "d", {"start": raw.index("Gamma"), "end": raw.index("Gamma") + 5,
                  "target_field": "document"})
        assert got == "Gamma"

    def test_markup_is_anchored_to_what_the_browser_holds(self):
        from potato.server_utils.displays.base import document_dom_text
        raw = "<p>Alpha beta</p><p>Gamma delta</p>"
        ctx = self._context({"id": "d", "document": raw})
        basis = document_dom_text(raw)
        got = ctx.covered_text(
            "d", {"start": 0, "end": 5, "target_field": "document"})
        assert got == basis[0:5] == "Alpha"

    def test_entities_do_not_shift_later_spans(self):
        raw = "Tom &amp; Jerry and more"
        ctx = self._context({"id": "d", "document": raw})
        got = ctx.covered_text(
            "d", {"start": 12, "end": 15, "target_field": "document"})
        assert got == "and", f"got {got!r}"

    def test_a_dict_payload_uses_its_rendered_html(self):
        ctx = self._context(
            {"id": "d", "document": {"rendered_html": "Alpha\n\nBeta"}})
        got = ctx.covered_text(
            "d", {"start": 7, "end": 11, "target_field": "document"})
        assert got == "Beta"

    def test_a_non_document_field_is_untouched(self):
        """The str fast path still applies to everything else."""
        ctx = self._context({"id": "d", "document": "a\n\nb"},
                            field_config={"key": "document", "type": "text"})
        assert ctx.covered_text(
            "d", {"start": 0, "end": 4, "target_field": "document"}) == "a\n\nb"


# ---------------------------------------------------------------------------
# 2. A study that loads nothing.
# ---------------------------------------------------------------------------
class TestEmptyStudyIsNotSilent:

    @pytest.fixture
    def project(self, tmp_path):
        (tmp_path / "incoming").mkdir()
        return tmp_path

    def _watcher(self, directory):
        from potato.directory_watcher import DirectoryWatcher
        from potato.item_state_management import (
            clear_item_state_manager, get_item_state_manager,
            init_item_state_manager)
        clear_item_state_manager()
        config = {"data_directory": str(directory),
                  "item_properties": {"id_key": "id", "text_key": "text"}}
        init_item_state_manager(config)
        return DirectoryWatcher(config, get_item_state_manager())

    def test_zero_instances_warns_rather_than_informs(self, project, caplog):
        (project / "incoming" / "a.md").write_text("# doc")
        watcher = self._watcher(project / "incoming")
        with caplog.at_level(logging.WARNING,
                             logger="potato.directory_watcher"):
            assert watcher.load_directory() == 0
        assert "0 instances" in caplog.text
        assert "empty study" in caplog.text

    def test_the_skipped_files_are_named(self, project, caplog):
        (project / "incoming" / "a.md").write_text("# doc")
        (project / "incoming" / "b.md").write_text("# doc")
        watcher = self._watcher(project / "incoming")
        with caplog.at_level(logging.WARNING,
                             logger="potato.directory_watcher"):
            watcher.load_directory()
        assert "a.md" in caplog.text and "b.md" in caplog.text
        assert ".json" in caplog.text

    def test_an_empty_directory_still_warns(self, project, caplog):
        """Every cause lands on zero instances, which is why the count is the
        thing worth warning about rather than the extension."""
        watcher = self._watcher(project / "incoming")
        with caplog.at_level(logging.WARNING,
                             logger="potato.directory_watcher"):
            watcher.load_directory()
        assert "0 instances" in caplog.text

    def test_a_directory_that_loads_stays_quiet(self, project, caplog):
        (project / "incoming" / "real.json").write_text(
            json.dumps([{"id": "1", "text": "hi"}]))
        watcher = self._watcher(project / "incoming")
        with caplog.at_level(logging.WARNING,
                             logger="potato.directory_watcher"):
            assert watcher.load_directory() == 1
        assert caplog.text == ""

    def test_dotfiles_are_not_reported_as_skipped(self, project, caplog):
        (project / "incoming" / ".DS_Store").write_text("x")
        watcher = self._watcher(project / "incoming")
        with caplog.at_level(logging.WARNING,
                             logger="potato.directory_watcher"):
            watcher.load_directory()
        assert ".DS_Store" not in caplog.text


class TestValidateCatchesTheEmptyStudy:
    """`potato validate` reported "OK -- no issues found" for a directory
    holding nothing it reads."""

    def _validate(self, tmp_path, config_extra=""):
        from potato.validate_cli import validate_config_file
        config = tmp_path / "config.yaml"
        config.write_text(
            "port: 8000\n"
            "annotation_task_name: probe\n"
            "data_directory: incoming\n"
            "item_properties: {id_key: id, text_key: text}\n"
            "user_config: {allow_all_users: true}\n"
            "task_dir: .\n"
            "output_annotation_dir: out\n"
            + config_extra +
            "annotation_schemes:\n"
            "  - annotation_type: radio\n"
            "    name: q\n"
            "    description: Q\n"
            '    labels: ["Yes", "No"]\n')
        return validate_config_file(str(config))

    def test_unreadable_extensions_are_reported(self, tmp_path):
        (tmp_path / "incoming").mkdir()
        (tmp_path / "incoming" / "a.md").write_text("# doc")
        report = self._validate(tmp_path)
        assert any("data_directory" in w and "a.md" in w
                   for w in report.other_warnings), report.other_warnings

    def test_an_empty_unwatched_directory_is_reported(self, tmp_path):
        (tmp_path / "incoming").mkdir()
        report = self._validate(tmp_path)
        assert any("empty" in w for w in report.other_warnings), \
            report.other_warnings

    def test_an_empty_watched_directory_is_allowed(self, tmp_path):
        """A watched directory is legitimately empty at boot."""
        (tmp_path / "incoming").mkdir()
        report = self._validate(tmp_path, "watch_data_directory: true\n")
        assert not any("empty" in w for w in report.other_warnings), \
            report.other_warnings

    def test_a_readable_directory_is_silent(self, tmp_path):
        (tmp_path / "incoming").mkdir()
        (tmp_path / "incoming" / "d.json").write_text(
            json.dumps([{"id": "1", "text": "hi"}]))
        report = self._validate(tmp_path)
        assert not report.errors, report.errors
        assert not any("data_directory" in w for w in report.other_warnings), \
            report.other_warnings


# ---------------------------------------------------------------------------
# The client half, executed rather than grepped.
# ---------------------------------------------------------------------------
NODE_PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

// Lift the two methods out of the class body and give them a `this` with the
// container stub each case needs. Executing them is the point: asserting the
// source mentions getComputedStyle would pass on a broken implementation.
const grab = (name) => {
  const at = src.indexOf('\n    ' + name + '(');
  if (at < 0) throw new Error('method not found: ' + name);
  let i = src.indexOf('{', at), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
  }
  return src.slice(src.indexOf('(', at), end);
};

const body = `({ ${'preservedWhitespace' + grab('preservedWhitespace')}, ${'normalizeText' + grab('normalizeText')} })`;
const methods = eval(body);

function stub(whiteSpace, opts = {}) {
  global.window = { getComputedStyle: () => ({ whiteSpace }) };
  // Both methods on one `this`: normalizeText calls preservedWhitespace.
  return Object.assign(Object.create(methods), { container: {
    closest: (sel) => (opts.codeDisplay ? {} : null),
    querySelector: (sel) => (opts.hasPre ? {} : null),
  } });
}

const cases = [];
const check = (name, got, want) => cases.push({ name, got, want, ok: got === want });

for (const ws of ['pre', 'pre-wrap', 'break-spaces']) {
  check('preserved:' + ws, methods.preservedWhitespace.call(stub(ws)), 'all');
  check('normalize:' + ws,
        methods.normalizeText.call(stub(ws), 'a\n\nb  c '), 'a\n\nb  c ');
}
check('preserved:pre-line', methods.preservedWhitespace.call(stub('pre-line')), 'newlines');
check('normalize:pre-line',
      methods.normalizeText.call(stub('pre-line'), 'a\n\nb  c'), 'a\n\nb c');
check('preserved:normal', methods.preservedWhitespace.call(stub('normal')), 'none');
check('normalize:normal',
      methods.normalizeText.call(stub('normal'), 'a\n\nb  c'), 'a b c');
check('preserved:code-display-without-style',
      methods.preservedWhitespace.call(stub('normal', { codeDisplay: true })), 'newlines');
check('preserved:pre-element',
      methods.preservedWhitespace.call(stub('normal', { hasPre: true })), 'newlines');

console.log(JSON.stringify(cases));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
class TestSpanCorePreservesWhitespaceByComputedStyle:
    """The offset walk sums raw `node.textContent.length`, so the basis must
    keep every character the DOM keeps. `normalizeText` decided that from a
    list of class names that named the code displays and nothing else, so a
    `document` field -- pre-wrap through a different class -- had its newlines
    collapsed out from under its own offsets."""

    @pytest.fixture(scope="class")
    def results(self, tmp_path_factory):
        probe = tmp_path_factory.mktemp("node") / "probe.js"
        probe.write_text(NODE_PROBE)
        out = subprocess.run(
            ["node", str(probe), "potato/static/span-core.js"],
            capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return {row["name"]: row for row in json.loads(out.stdout)}

    @pytest.mark.parametrize("case", [
        "preserved:pre", "preserved:pre-wrap", "preserved:break-spaces",
        "preserved:pre-line", "preserved:normal",
        "preserved:code-display-without-style", "preserved:pre-element",
    ])
    def test_the_container_style_decides_how_much_is_kept(self, results, case):
        row = results[case]
        assert row["ok"], f"{case}: got {row['got']!r}, want {row['want']!r}"

    @pytest.mark.parametrize("case", [
        "normalize:pre", "normalize:pre-wrap", "normalize:break-spaces",
        "normalize:pre-line", "normalize:normal",
    ])
    def test_the_basis_keeps_exactly_that_much(self, results, case):
        row = results[case]
        assert row["ok"], f"{case}: got {row['got']!r}, want {row['want']!r}"

    def test_a_preserving_container_is_not_trimmed(self, results):
        """Trimming shifts every offset after the removed character."""
        row = results["normalize:pre-wrap"]
        assert row["got"].endswith(" "), "leading/trailing space must survive"
