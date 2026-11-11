"""Every scheme the live-session docs say updates at once, on a real page.

For each type, on its own example (or a two-item project for a type without
one), member ben saves a test answer (``collab_sweep_answers.json``) and
member ana's open page must come to look exactly like a fresh load of the
item: the same visible text, control state, selections, SVG geometry, span
overlays and what canvas widgets have drawn. Then ben clears the answer and
ana's page must look like a fresh load of the cleared item, except for the
schemes the docs say show a clear only after a reload. ana's page must never
save, and literals from the answer must appear on it.

One server per type, so this module is slow (~15 minutes) and carries its own
timeout: under the 120 s browser-test default, pytest-timeout fired near the
23rd example and wedged against Playwright's sync loop instead of failing.
Problems are collected across all types and reported together.
"""

import json
import os
import re
import shutil

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.teardown_watchdog import TEST_TEARDOWN_TIMEOUT_SECONDS, bounded_teardown  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# annotation_type -> an example that uses it
EXAMPLES = {
    "image_annotation": "examples/advanced/annotation-telemetry",
    "audio_annotation": "examples/audio/audio-annotation",
    "video_annotation": "examples/video/mask-propagation",
    "tiered_annotation": "examples/audio/tiered-annotation",
    "spectrogram_annotation": "examples/audio/bioacoustics-boxes",
    "interval_label": "examples/advanced/time-series-intervals",
    "spatial_annotation": "examples/spatial/kitti-cuboids",
    "volume_annotation": "examples/image/ct-volume",
    "microscopy": "examples/image/multichannel-microscopy",
    "geo_annotation": "examples/advanced/dialect-map",
    "episode_annotation": "examples/embodied/lerobot-episode",
    "rollout_evaluation": "examples/agent-traces/world-model-rollouts",
    "grounding_eval": "examples/ai-assisted/grounding-eval",
    "region_caption": "examples/image/region-captioning",
    "agent_interaction_graph": "examples/agent-traces/interaction-graph",
    "agent_scorecard": "examples/agent-traces/agent-scorecard",
    "consensus_tracking": "examples/agent-traces/debate-judging",
    "emergent_behavior": "examples/agent-traces/emergent-behavior",
    "failure_attribution": "examples/agent-traces/failure-attribution",
    "gui_trajectory": "examples/agent-traces/gui-trajectory",
    "handoff_review": "examples/agent-traces/handoff-review",
    "multimodal_reasoning": "examples/agent-traces/multimodal-reasoning",
    "speech_transcript": "examples/agent-traces/speech-transcript",
    "table_grid": "examples/agent-traces/table-grid",
    "temporal_grounding": "examples/agent-traces/temporal-grounding",
    "tool_call_review": "examples/agent-traces/tool-call-review",
    "tool_contention": "examples/agent-traces/tool-contention",
    "voice_interaction": "examples/agent-traces/voice-interaction",
    "process_reward": "examples/agent-traces/coding-agent-prm",
    "code_review": "examples/agent-traces/coding-agent-review",
    "belief_elicitation": "examples/advanced/incentivized-elicitation",
    "chemical_structure": "examples/advanced/chemical-structure-correction",
    "multi_document_event": "examples/advanced/multi-document-events",
    "ego_network": "examples/advanced/ego-network",
    "triad_test": "examples/advanced/cultural-domain",
    "listening_test": "examples/audio/listening-test-mushra",
    "interlinear_gloss": "examples/span/interlinear-gloss",
    "peak_picking": "examples/advanced/spectrum-peak-picking",
    "tree_annotation": "examples/span/conversation-tree",
    "triage": "examples/advanced/triage",
    # Shown by annotation.js's restore pass from the scheme's own inputs.
    "radio": "examples/classification/single-choice",
    "multiselect": "examples/classification/check-box",
    "likert": "examples/classification/likert",
    "slider": "examples/classification/slider",
    "text": "examples/advanced/all-annotation-types",
    "select": "examples/advanced/all-annotation-types",
    "number": "examples/advanced/all-annotation-types",
    "ranking": "examples/classification/ranking",
    "hierarchical_multiselect": "examples/classification/hierarchical-multiselect",
    "pairwise": "examples/classification/pairwise-comparison",
    "bws": "examples/classification/best-worst-scaling",
    "text_edit": "examples/classification/text-edit",
    "extractive_qa": "examples/classification/extractive-qa",
    "error_span": "examples/classification/error-span",
    "trajectory_eval": "examples/agent-traces/trajectory-evaluation",
    "trajectory_edit": "examples/agent-traces/trajectory-correction",
    # Drawn by the span, link and event layers, reloaded from their routes.
    "span": "examples/span/span-labeling",
    "span_link": "examples/span/span-linking",
    "coreference": "examples/span/coreference",
    "event_annotation": "examples/span/event-annotation",
    # Display-made forms and widgets with no example of their own.
    "pdf_bounding_box": "examples/image/pdf-bbox",
    "document_bounding_box": "examples/image/document-bbox",
    "turn_level": "examples/agent-traces/per-turn-binding",
    "viewer_selection": "examples/advanced/protein-binding-site",
    "price_list": {"annotation_type": "price_list", "name": "risk_pref",
                   "description": "Choose for each row.", "preset": "holt_laury"},
    "bdm": {"annotation_type": "bdm", "name": "wtp", "description": "Your bid.", "max": 10},
    "free_list": {"annotation_type": "free_list", "name": "fruits",
                  "description": "List fruits you know."},
}

# Types collab.js shows through annotation.js's restore pass or the span, link
# and event layers, not through a registered widget applier.
SHOWN_BY_PAGE = {"radio", "multiselect", "likert", "slider", "text", "select", "number",
                 "ranking", "hierarchical_multiselect", "pairwise", "bws", "text_edit",
                 "extractive_qa", "error_span", "trajectory_eval", "trajectory_edit",
                 "span", "span_link", "coreference", "event_annotation"}

# annotation_type -> {"schema:::label": value} a teammate saves; blob values are JSON strings.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "collab_sweep_answers.json")) as _f:
    ANSWERS = json.load(_f)

# Documented: a teammate clearing these shows after a reload (collaborative_sessions.md).
CLEARED_ON_RELOAD_ONLY = {"ranking", "hierarchical_multiselect", "pairwise", "bws",
                          "text_edit", "extractive_qa", "error_span", "trajectory_eval",
                          "trajectory_edit"}

# Network noise from examples whose media live elsewhere, not script errors.
NOISE = re.compile(r"Failed to load resource|net::ERR_|favicon|ERR_NAME_NOT_RESOLVED|"
                   r"the server responded with a status of 404")

# A type's schemes on the page. Box drawing on a PDF or document display has
# no scheme form: its answer is kept under the display's field key.
SCHEMES_JS = """(type) => {
    const BOXES = {pdf_bounding_box: '.pdf-display', document_bounding_box: '.document-display'};
    const els = BOXES[type]
        ? [...document.querySelectorAll(`${BOXES[type]}[data-annotation-mode="bounding_box"]`)]
            .map((el) => el.getAttribute('data-field-key'))
        : [...document.querySelectorAll(`[data-annotation-type="${type}"][data-schema-name]`)]
            .map((f) => f.getAttribute('data-schema-name'));
    return [...new Set(els.filter(Boolean))].sort();
}"""

REMOTE_AUDIO = re.compile(r"https?://[^\"\s]+\.(?:mp3|wav|ogg)")


def _local_media(work, config):
    """Point remote audio at a local clip: a 9 MB mp3 streamed from another
    site does not finish loading inside the check, and the widgets draw their
    segments only once it has."""
    replaced = False
    for root, _dirs, files in os.walk(os.path.join(work, "data")):
        for name in files:
            if not name.endswith((".json", ".jsonl")):
                continue
            path = os.path.join(root, name)
            with open(path) as f:
                text = f.read()
            new = REMOTE_AUDIO.sub("/media/sweep_audio.wav", text)
            if new != text:
                replaced = True
                with open(path, "w") as f:
                    f.write(new)
    if replaced:
        media = os.path.join(work, config.setdefault("media_directory", "media"))
        os.makedirs(media, exist_ok=True)
        shutil.copy(os.path.join(REPO, "tests", "data", "test_audio_10s.wav"),
                    os.path.join(media, "sweep_audio.wav"))


def _inline_project(work, scheme):
    """A two-item project around one scheme, for a type with no example."""
    os.makedirs(os.path.join(work, "data"))
    with open(os.path.join(work, "data", "items.json"), "w") as f:
        for n in (1, 2):
            f.write(json.dumps({"id": f"item_{n}", "text": f"Item {n} of the sweep."}) + "\n")
    return {"annotation_task_name": f"Sweep {scheme['annotation_type']}", "task_dir": ".",
            "output_annotation_dir": "annotation_output/", "data_files": ["data/items.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [scheme], "site_dir": "potato/templates/"}


def _session_copy(example, name):
    work = os.path.join(create_test_directory(f"collab_sweep_{name}"), "example")
    path = os.path.join(work, "config.yaml")
    if isinstance(example, dict):
        config = _inline_project(work, example)
    else:
        shutil.copytree(os.path.join(REPO, example), work, ignore=shutil.ignore_patterns(
            "annotation_output", "project.sqlite*", "layouts", "test_config_port_*"))
        with open(path) as f:
            config = yaml.safe_load(f)
    for key in ("phases", "surveyflow", "training", "prestudy", "poststudy", "consent",
                "instructions", "rooms", "crowdsourcing", "login",
                # Some examples point at a hosted model; the sweep must never
                # make paid calls on a machine with a key set.
                "ai_support"):
        config.pop(key, None)
    # Rules about schemes on the phase pages just dropped would fail validation.
    names = {s.get("name") for s in config.get("annotation_schemes") or []}
    incentives = config.get("incentives")
    if isinstance(incentives, dict) and incentives.get("rules"):
        incentives["rules"] = [r for r in incentives["rules"] if r.get("scheme") in names]
    _local_media(work, config)
    config["user_config"] = {"allow_all_users": True, "users": []}
    config["require_password"] = False
    config["collab"] = {"enabled": True, "default_mode": "free", "teams": [
        {"id": "sweep", "members": ["ana", "ben"], "leader": "ana", "items": {"count": 2}}]}
    with open(path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return path


# What a member sees of a scheme: visible text, control state, selection
# classes, SVG geometry, canvas sizes and what a canvas widget has drawn
# (3D meshes, painted voxels) inside the scheme's containers and any viewer on
# the page. Session furniture (badges, avatars) is left out.
FINGERPRINT_JS = r"""(schemas) => {
    const roots = new Set();
    for (const s of schemas) {
        document.querySelectorAll(`[data-schema-name="${CSS.escape(s)}"]`).forEach((el) => {
            if (!el.parentElement || !el.parentElement.closest(`[data-schema-name="${CSS.escape(s)}"]`)) roots.add(el);
        });
    }
    document.querySelectorAll('.potato-viewer, .span-link-arcs-container, .event-annotation-arcs-container, '
                              + '.pdf-display[data-annotation-mode="bounding_box"], '
                              + '.document-display[data-annotation-mode="bounding_box"]')
        .forEach((el) => roots.add(el));
    // What collab.js puts inside a scheme; its state classes on the form
    // itself (collab-remote-change, collab-has-badge) are not content.
    // Progress counters are left out too: every page refreshes them on
    // navigation, after the member's own saves as well as a teammate's.
    // .pc-announce is the point cloud's screen-reader line: hidden, said once,
    // and what it says depends on how far loading had got at that moment.
    const FURNITURE = '.collab-editing-badge, .collab-avatar, [id^="collab-"], .triage-progress, .pc-announce';
    const skip = (el) => !!el.closest(FURNITURE);
    // The item the member last clicked in a list: a teammate's change leaves
    // it alone on purpose (the doc: "the shape you had selected stays
    // selected"), where a reload picks the first.
    const FOCUS_ONLY = '.segment-item.active';
    const hash = (str) => { let h = 0; for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0; return h; };
    const r = (v) => (v == null || v === '' ? '' : String(Math.round(parseFloat(v) * 10) / 10));
    const out = {text: [], controls: [], selected: [], svg: [], canvas: [], scene: [], spans: []};
    for (const root of roots) {
        let text = root.innerText || '';
        root.querySelectorAll(FURNITURE).forEach((el) => {
            if (el.innerText) text = text.split(el.innerText).join('');
        });
        out.text.push(text.replace(/\s+/g, ' ').trim());
        root.querySelectorAll('input, select, textarea').forEach((el) => {
            if (skip(el) || el.type === 'hidden') return;
            // By name, not id: some widgets give each render a fresh random id.
            if (el.type === 'checkbox' || el.type === 'radio') out.controls.push(`${el.name}=${el.value}:${el.checked}`);
            else out.controls.push(`${el.name}=${el.value}`);
        });
        root.querySelectorAll('[class]').forEach((el) => {
            if (skip(el) || el.matches(FOCUS_ONLY)) return;
            const c = typeof el.className === 'string' ? el.className : (el.className.baseVal || '');
            if (/\b(selected|active|checked|is-selected|chosen|picked)\b/.test(c)) out.selected.push(`${el.tagName}.${c.trim()}|${(el.textContent || '').trim().slice(0, 40)}`);
        });
        root.querySelectorAll('svg rect, svg circle, svg ellipse, svg line, svg path, svg polygon, svg polyline, svg text').forEach((el) => {
            if (skip(el) || getComputedStyle(el).display === 'none') return;
            const a = (n) => el.getAttribute(n);
            out.svg.push([el.tagName, r(a('x')), r(a('y')), r(a('width')), r(a('height')), r(a('cx')), r(a('cy')), r(a('r')),
                          a('d') ? hash(a('d')) : '', a('points') ? hash(a('points')) : '', el.tagName === 'text' ? el.textContent : ''].join(','));
        });
        // Canvases by size only: pixels differ between two loads of the same
        // answer (point-cloud slabs fill in the order octree nodes arrive, map
        // labels anti-alias differently). What a canvas widget holds is read
        // from the lists, readouts and SVG around it.
        root.querySelectorAll('canvas').forEach((el) => {
            if (!skip(el) && el.width && el.height) out.canvas.push(`${el.width}x${el.height}`);
        });
        // Widgets that draw only on a canvas are read from what they put on
        // it: the meshes a 3D viewer added to its scene, and the voxels a
        // volume painter holds per label.
        [root, ...root.querySelectorAll('[data-schema]')].forEach((el) => {
            const m = el.annotationManager;
            if (!m) return;
            if (m.scene && Array.isArray(m.meshes)) {
                m.meshes.forEach((mesh) => {
                    if (!mesh || mesh.parent !== m.scene || !mesh.visible) return;
                    // World-space bounds: a box's corners are baked into
                    // its geometry, so its position alone is the origin.
                    const b = new THREE.Box3().setFromObject(mesh);
                    const c = mesh.material && mesh.material.color ? mesh.material.color.getHexString() : '';
                    out.scene.push(`${mesh.type}[${r(b.min.x)},${r(b.min.y)},${r(b.min.z)} ${r(b.max.x)},${r(b.max.y)},${r(b.max.z)}]#${c}`);
                });
            }
            if (m.masks && typeof m.masks === 'object') {
                for (const [label, slices] of Object.entries(m.masks)) {
                    let voxels = 0;
                    for (const slice of (slices instanceof Map ? slices.values() : Object.values(slices))) {
                        for (let i = 0; i < slice.length; i++) if (slice[i]) voxels++;
                    }
                    if (voxels) out.scene.push(`${label}:${voxels} voxels`);
                }
            }
        });
    }
    out.scene.sort();
    // Span overlays by what they mark, not where they sit: two loads lay the
    // text out alike, but a live page may still be settling its fonts.
    document.querySelectorAll('.span-overlay-pure, .span-overlay-ai').forEach((el) => {
        const d = el.dataset;
        out.spans.push(`${d.schema || ''}:${d.label || ''}@${d.start ?? d.partStart}-${d.end ?? d.partEnd}`);
    });
    out.spans.sort();
    // Per-turn answers sit in the trace beside each turn, outside the
    // scheme's anchor form (which holds only the counters).
    document.querySelectorAll('.ta-chip.ta-selected').forEach((el) => {
        out.selected.push(`turn ${el.dataset.turnId}=${el.dataset.value}`);
    });
    document.querySelectorAll('.ta-range, .ta-select, .ta-text, .ta-number').forEach((el) => {
        out.controls.push(`turn ${el.dataset.turnId}=${el.value}`);
    });
    // Boxes on a PDF or document page exist only as strokes on a 2D canvas:
    // its painted pixels, counted per horizontal band. Unlike WebGL slabs and
    // map tiles, these draw the same on every load of the same answer.
    document.querySelectorAll('.pdf-bbox-canvas, .document-bbox-canvas').forEach((el) => {
        if (!el.width || !el.height) return;
        const data = el.getContext('2d').getImageData(0, 0, el.width, el.height).data;
        const bands = new Array(8).fill(0);
        for (let i = 3; i < data.length; i += 4) {
            if (data[i]) bands[Math.min(7, Math.floor(((i - 3) / 4 / el.width) / el.height * 8))]++;
        }
        out.scene.push(`${el.className} painted ${bands.join('/')}`);
    });
    return out;
}"""


def _diff(a, b):
    return sorted(k for k in a if a[k] != b.get(k))


def _wait_built(page):
    page.wait_for_function("window.potatoCollabClient && window.potatoCollabClient.state.session",
                           timeout=15000)
    page.wait_for_timeout(2500)          # widgets that build after their data arrives


def _setup_as(request, server, steps):
    """Calls ben's page would make before saving (e.g. creating a shared
    event); each response is available to later values as ``$<n>.<field>``."""
    results = []
    for step in steps or []:
        r = request.fetch(f"{server.base_url}{step['path']}", method=step.get("method", "POST"),
                          data=step.get("json"), headers={"Origin": server.base_url})
        results.append(r.json() if r.ok else {})
    return results


def _fill(value, results):
    for n, body in enumerate(results):
        for field, v in (body or {}).items():
            if isinstance(v, (str, int)):
                value = value.replace(f"${n}.{field}", str(v))
    return value


LAYERS = {"__spans": "span_annotations", "__links": "link_annotations",
          "__events": "event_annotations"}


def _save_as(request, server, iid, annotations, layers=None):
    rev = request.get(f"{server.base_url}/collab/api/SWEEP/item/{iid}").json()["rev"]
    body = {"instance_id": iid, "annotations": annotations,
            "collab": {"sid": "SWEEP", "base_rev": rev}}
    for key, field in LAYERS.items():
        if (layers or {}).get(key):
            body[field] = layers[key]
    r = request.post(f"{server.base_url}/updateinstance", data=body,
                     headers={"Origin": server.base_url})
    return r.status


def _clear_layers(request, server, iid, layers):
    """Take a teammate's spans, links and events off the item the way their
    page does, through the routes the session client names itself on."""
    headers = {"Origin": server.base_url, "X-Potato-Collab": "SWEEP"}
    for key, route in (("__events", "events"), ("__links", "links")):
        for element in layers.get(key) or []:
            request.delete(f"{server.base_url}/api/{route}/{iid}/{element['id']}", headers=headers)
    if layers.get("__spans"):
        request.post(f"{server.base_url}/api/spans/{iid}/clear", headers=headers)


def _fresh(context, url, schemas):
    """The fingerprint of a fresh load of the item: the stored answer drawn
    the ordinary way."""
    fresh_page = context.new_page()
    try:
        fresh_page.goto(url)
        _wait_built(fresh_page)
        return fresh_page.evaluate(FINGERPRINT_JS, schemas)
    finally:
        fresh_page.close()


def _settle(page, schemas, target, seconds=8):
    """The page's fingerprint once it matches ``target`` (or the last one seen)."""
    fp = page.evaluate(FINGERPRINT_JS, schemas)
    for _ in range(int(seconds * 4)):
        if fp == target:
            break
        page.wait_for_timeout(250)
        fp = page.evaluate(FINGERPRINT_JS, schemas)
    return fp


#: annotation_type -> the fingerprint fields that tell its answered item from
#: an empty one, filled in by _check (the report reads it).
EVIDENCE = {}


def _visible(fp):
    return " ".join(fp["text"] + fp["controls"])


def _check(browser, annotation_type, example, answer=None):
    """Problems with showing a teammate's answer live, judged against a reload.

    A fresh load of the item draws the stored answer through the ordinary
    page path; the live page must end up looking the same, without saving.
    """
    answer = answer if answer is not None else ANSWERS.get(annotation_type)
    server = FlaskTestServer(config_file=_session_copy(example, annotation_type))
    if not server.start():
        return [f"{annotation_type}: the example server did not start"]
    problems = []
    ana_ctx = browser.new_context(base_url=server.base_url, viewport={"width": 1280, "height": 900})
    ben_ctx = browser.new_context(base_url=server.base_url, viewport={"width": 1280, "height": 900})
    try:
        ana_ctx.request.post(f"{server.base_url}/auth", form={"email": "ana", "pass": ""})
        ben_ctx.request.post(f"{server.base_url}/auth", form={"email": "ben", "pass": ""})
        page = ana_ctx.new_page()
        errors, saves = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and not NOISE.search(m.text)
                and errors.append(m.text))
        page.on("request", lambda r: "/updateinstance" in r.url and saves.append(r.url))
        page.goto("/collab/s/SWEEP")
        try:
            _wait_built(page)
        except Exception:
            return [f"{annotation_type}: no live session page at {page.url}"]
        schemas = page.evaluate(SCHEMES_JS, annotation_type)
        if not schemas:
            return problems + [f"{annotation_type}: no scheme of this type on the page"]
        for schema in schemas if annotation_type not in SHOWN_BY_PAGE else ():
            if not page.evaluate("(s) => window.potatoCollabClient.hasWidget(s)", schema):
                problems.append(f"{annotation_type}: collab.js finds no live applier for '{schema}'")
        if not answer:
            return problems + [f"{annotation_type}: no test answer in collab_sweep_answers.json"]
        iid = page.evaluate("() => document.getElementById('instance_id').value")
        empty = page.evaluate(FINGERPRINT_JS, schemas)
        before = len(saves)

        expect = answer.get("__expect") or []
        layers = {k: answer[k] for k in LAYERS if answer.get(k)}
        results = _setup_as(ben_ctx.request, server, answer.get("__requests"))
        answer = {k: _fill(v, results) for k, v in answer.items() if not k.startswith("__")}
        status = _save_as(ben_ctx.request, server, iid, answer, layers)
        if status != 200:
            return problems + [f"{annotation_type}: ben's save of the test answer got {status}"]
        fresh = _fresh(ana_ctx, page.url, schemas)
        shown_by = _diff(empty, fresh) if fresh != empty else []
        EVIDENCE[annotation_type] = shown_by
        if fresh == empty:
            problems.append(f"{annotation_type}: the test answer does not show even on a fresh load")
        elif set(shown_by) <= {"canvas"}:
            problems.append(f"{annotation_type}: only a canvas size tells the answer apart; "
                            "nothing in the page reflects its content")
        live = _settle(page, schemas, fresh)
        if live != fresh:
            problems.append(f"{annotation_type}: the teammate's answer looks different live than "
                            f"after a reload ({', '.join(_diff(fresh, live))})")
        if len(saves) > before:
            problems.append(f"{annotation_type}: showing a teammate's answer sent a save")
        # The reload can be wrong the same way as the live page (code_review
        # lost its verdict on both), so a few literals of the answer itself
        # must appear live that the empty page did not have.
        for literal in expect:
            if literal in _visible(empty):
                problems.append(f"{annotation_type}: expected literal {literal!r} is on the empty page too")
            elif literal not in _visible(live):
                problems.append(f"{annotation_type}: {literal!r} from the answer is not on the live page")

        if annotation_type not in CLEARED_ON_RELOAD_ONLY:
            before = len(saves)
            if answer:
                _save_as(ben_ctx.request, server, iid, {k: "" for k in answer})
            _clear_layers(ben_ctx.request, server, iid, layers)
            # Judged against a reload of the cleared item, not the page as it
            # first was: a cleared answer shows what an unanswered item shows
            # (its prefill), and shared state (a corpus event) outlives it.
            cleared = _fresh(ana_ctx, page.url, schemas)
            live = _settle(page, schemas, cleared)
            if live != cleared:
                problems.append(f"{annotation_type}: a cleared answer looks different live than "
                                f"after a reload ({', '.join(_diff(cleared, live))})")
            if len(saves) > before:
                problems.append(f"{annotation_type}: showing a cleared answer sent a save")
        problems.extend(f"{annotation_type}: {e}" for e in errors)
    finally:
        with bounded_teardown(f"sweep contexts ({annotation_type})",
                              seconds=TEST_TEARDOWN_TIMEOUT_SECONDS):
            ana_ctx.close()
            ben_ctx.close()
        server.stop()
    return problems


@pytest.mark.timeout(2400)
def test_every_widget_is_live_in_its_own_example(browser_instance):
    problems = []
    for annotation_type, example in EXAMPLES.items():
        problems.extend(_check(browser_instance, annotation_type, example))
    assert not problems, "\n".join(problems)
