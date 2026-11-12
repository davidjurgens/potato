"""`source_field` alone points a media widget at the right field.

`source_field` is documented as the way to tell an audio, image or video widget
which field carries the media when it is not `text_key`. It did nothing on its
own. Every step in the three lookup chains that consulted it needed markup that
only an `instance_display` block emits -- `[data-field-key=...]` and
`.instance-display-container[data-instance-fields]` -- so a config that set
`source_field` and no `instance_display` fell through to a text heuristic,
found nothing, and told the annotator the item had no media.

The item's fields were on the page the whole time. The server emits
`<script id="instance_data" type="application/json">` with the item's field
dict on every annotation page, `instance_display` or not. Nothing read it.

Driven the way the browser runs it: the real generated bootstrap, executed
under node against a DOM that has the `instance_data` block and nothing else,
asserting the URL the manager is asked to load. A DOM stub that answered
`querySelector` with anything would be measuring the harness, so it answers
only the container lookup -- the same shape of page a config without
`instance_display` produces.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HELPER = Path("potato/static/instance-fields.js")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to run the widget JS")


def _bootstrap(html):
    """The largest <script> in a generated layout is its bootstrap."""
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert scripts, "the generator emitted no script at all"
    return max(scripts, key=len)


def _run(script, fields, container_selector, manager_name, load_method,
         extra_globals=""):
    """Run a bootstrap against a page carrying only `instance_data`.

    Returns whatever URL the widget asked its manager to load, or "NOTHING"
    when it asked for nothing.
    """
    harness = """
global.window = global;
var loaded = null;
var instanceScript = { textContent: %(fields)s };
var recordEl = { getAttribute: function () { return %(fields)s; } };
function stubEl() {
  return {
    style: {}, dataset: {},
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    appendChild: function () {}, insertBefore: function () {},
    setAttribute: function () {}, getAttribute: function () { return null; },
    addEventListener: function () {}, firstChild: null,
    classList: { add: function () {}, remove: function () {}, contains: function () { return false; } },
    getBoundingClientRect: function () { return { top: 0, left: 0, width: 800, height: 200, right: 800, bottom: 200 }; },
    offsetWidth: 800, offsetHeight: 200, clientWidth: 800, clientHeight: 200,
    getContext: function () { return null; }, innerHTML: '', textContent: ''
  };
}
global.document = {
  getElementById: function (id) {
    return id === 'instance_data' ? instanceScript : stubEl();
  },
  querySelector: function (sel) {
    if (sel === '[data-instance-json]') { return recordEl; }
    return sel.indexOf(%(container)s) === 0 ? stubEl() : null;
  },
  querySelectorAll: function () { return []; },
  addEventListener: function () {},
  createElement: function () { return stubEl(); },
  readyState: 'complete'
};
global.%(manager)s = function () {
  this.%(load)s = function (url) { loaded = url; };
  this.init = function () {}; this.restore = function () {};
};
global.console = { log: function () {}, warn: function () {}, error: function () {} };
%(extra)s
%(helper)s
%(script)s
setTimeout(function () {
  process.stdout.write('LOADED=' + (loaded === null ? 'NOTHING' : loaded) + '\\n');
}, 400);
""" % {
        "fields": json.dumps(json.dumps(fields)),
        "container": json.dumps(container_selector),
        "manager": manager_name,
        "load": load_method,
        "extra": extra_globals,
        "helper": HELPER.read_text(encoding="utf-8"),
        "script": script,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(harness)
        path = fh.name
    result = subprocess.run(["node", path], capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, (
        f"the generated bootstrap threw:\n{result.stderr[:2000]}")
    match = re.search(r"LOADED=(.*)", result.stdout)
    assert match, f"harness produced no verdict:\n{result.stdout}"
    return match.group(1).strip()


def _audio(**overrides):
    from potato.server_utils.schemas.audio_annotation import (
        generate_audio_annotation_layout)

    scheme = {"annotation_type": "audio_annotation", "name": "clip",
              "description": "Mark segments", "labels": ["speech"]}
    scheme.update(overrides)
    return _bootstrap(generate_audio_annotation_layout(scheme)[0])


def _image(**overrides):
    from potato.server_utils.schemas.image_annotation import (
        generate_image_annotation_layout)

    scheme = {"annotation_type": "image_annotation", "name": "photo",
              "description": "Box it", "tools": ["bbox"], "labels": ["cat"]}
    scheme.update(overrides)
    return _bootstrap(generate_image_annotation_layout(scheme)[0])


def _video(**overrides):
    from potato.server_utils.schemas.video_annotation import (
        generate_video_annotation_layout)

    scheme = {"annotation_type": "video_annotation", "name": "vid",
              "description": "Mark it", "labels": ["shot"]}
    scheme.update(overrides)
    return _bootstrap(generate_video_annotation_layout(scheme)[0])


class TestTheWidgetLoadsTheConfiguredField:
    """No `instance_display` anywhere on the page -- the case that failed."""

    def test_audio(self):
        loaded = _run(_audio(source_field="audio_url"),
                      {"id": "a1", "text": "hi", "audio_url": "/media/clip.wav"},
                      ".audio-annotation-container", "AudioAnnotationManager",
                      "loadAudio", extra_globals="global.Peaks = {};")
        assert loaded == "/media/clip.wav", (
            "source_field named the field, the field was on the page, and the "
            "widget still reported no audio")

    def test_image(self):
        loaded = _run(_image(source_field="image_url"),
                      {"id": "i1", "text": "hi", "image_url": "/media/cat.png"},
                      ".image-annotation-container", "ImageAnnotationManager",
                      "loadImage")
        assert loaded == "/media/cat.png"

    def test_video(self):
        loaded = _run(_video(source_field="video_url"),
                      {"id": "v1", "text": "hi", "video_url": "/media/reel.mp4"},
                      ".video-annotation-container", "VideoAnnotationManager",
                      "loadVideo")
        assert loaded == "/media/reel.mp4"


class TestItDoesNotLoadTheWrongThing:

    def test_a_field_that_is_not_there_loads_nothing(self):
        loaded = _run(_audio(source_field="audio_url"),
                      {"id": "a1", "text": "not a url"},
                      ".audio-annotation-container", "AudioAnnotationManager",
                      "loadAudio", extra_globals="global.Peaks = {};")
        assert loaded == "NOTHING", (
            "a missing field must fall through, not load something else")

    def test_a_number_under_the_key_is_not_a_url(self):
        loaded = _run(_audio(source_field="audio_url"),
                      {"id": "a1", "text": "hi", "audio_url": 3},
                      ".audio-annotation-container", "AudioAnnotationManager",
                      "loadAudio", extra_globals="global.Peaks = {};")
        assert loaded == "NOTHING", (
            "the widget would have gone off to load \"3\"")

    def test_no_source_field_does_not_start_guessing_fields(self):
        """Without `source_field` there is no named field, and the widget must
        not pick one out of the item on its own."""
        loaded = _run(_audio(),
                      {"id": "a1", "text": "hi", "audio_url": "/media/clip.wav"},
                      ".audio-annotation-container", "AudioAnnotationManager",
                      "loadAudio", extra_globals="global.Peaks = {};")
        assert loaded == "NOTHING"


class TestTheHelperItself:
    """`instance_fields.js` in isolation, since three widgets depend on it."""

    def _eval(self, body, fields="{}", record="{}"):
        harness = ("global.window = global;\n"
                   "var block = { textContent: %s };\n"
                   "var record = { value: %s,\n"
                   "  getAttribute: function () { return this.value; } };\n"
                   "global.document = {\n"
                   "  getElementById: function (id) {\n"
                   "    return id === 'instance_data' ? block : null; },\n"
                   "  querySelector: function (sel) {\n"
                   "    return sel === '[data-instance-json]' ? record : null; } };\n"
                   "global.console = { warn: function () {} };\n"
                   "%s\nprocess.stdout.write(String(%s));\n"
                   % (json.dumps(fields), json.dumps(record),
                      HELPER.read_text(encoding="utf-8"), body))
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(harness)
            path = fh.name
        result = subprocess.run(["node", path], capture_output=True, text=True,
                                timeout=30)
        assert result.returncode == 0, result.stderr[:1000]
        return result.stdout.strip()

    def test_it_reads_the_full_record_first(self):
        """`[data-instance-json]` is the richer of the two blocks and the one
        the structured schemas and pc-viewer.js already read."""
        assert self._eval("window.potatoInstanceField('u')", fields="{}",
                          record='{"u": "/media/record.wav"}') == "/media/record.wav"

    def test_the_full_record_wins_over_the_scalar_copy(self):
        assert self._eval("window.potatoInstanceField('u')",
                          fields='{"u": "/media/scalar.wav"}',
                          record='{"u": "/media/record.wav"}') == "/media/record.wav"

    def test_it_falls_back_when_the_record_is_absent(self):
        """An empty record must not shadow a populated scalar block, or the
        fallback exists only on paper."""
        assert self._eval("window.potatoInstanceField('u')",
                          fields='{"u": "/media/scalar.wav"}',
                          record="{}") == "/media/scalar.wav"

    def test_a_broken_record_falls_back_rather_than_throwing(self):
        assert self._eval("window.potatoInstanceField('u')",
                          fields='{"u": "/media/scalar.wav"}',
                          record='{"u": ') == "/media/scalar.wav"

    def test_it_returns_the_value(self):
        assert self._eval("window.potatoInstanceField('u')",
                          '{"u": "/media/a.wav"}') == "/media/a.wav"

    def test_whitespace_is_trimmed(self):
        assert self._eval("window.potatoInstanceField('u')",
                          '{"u": "  /media/a.wav  "}') == "/media/a.wav"

    def test_an_empty_string_is_not_a_url(self):
        assert self._eval("window.potatoInstanceField('u')",
                          '{"u": "   "}') == "null"

    def test_a_missing_key_is_null(self):
        assert self._eval("window.potatoInstanceField('nope')",
                          '{"u": "/media/a.wav"}') == "null"

    def test_malformed_json_does_not_throw(self):
        """A widget must degrade to its next lookup step, not die on the page."""
        assert self._eval("window.potatoInstanceField('u')", '{"u": ') == "null"

    def test_it_is_read_fresh_rather_than_cached(self):
        """Navigating to the next instance replaces the block. A cached copy
        would load the previous item's media, which is worse than none."""
        body = ("(function () {\n"
                "  var first = window.potatoInstanceField('u');\n"
                "  document.getElementById('instance_data').textContent ="
                " '{\"u\": \"/media/second.wav\"}';\n"
                "  return first + '|' + window.potatoInstanceField('u');\n"
                "})()")
        assert self._eval(body, '{"u": "/media/first.wav"}') == (
            "/media/first.wav|/media/second.wav")
