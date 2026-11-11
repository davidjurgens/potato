"""Drawing together: two members of a live session on one image.

Each member draws with real mouse drags in their own browser. Both boxes must
end up in the team's answer and on both canvases without a reload, and must
still be there after navigating away and back. A shape one member deletes is
deleted on the other's canvas too.
"""

import json
import os
import re
import shutil

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENES = os.path.join(REPO, "examples", "advanced", "annotation-telemetry", "media")
SID = "DRAW"


@pytest.fixture(scope="module")
def server():
    work = create_test_directory("collab_media")
    os.makedirs(os.path.join(work, "media"), exist_ok=True)
    os.makedirs(os.path.join(work, "data"), exist_ok=True)
    for name in ("scene_1.png", "scene_2.png"):
        shutil.copy(os.path.join(SCENES, name), os.path.join(work, "media", name))
    with open(os.path.join(work, "data", "scenes.jsonl"), "w") as f:
        for i in (1, 2):
            f.write(json.dumps({"id": f"scene_{i}", "image_url": f"/media/scene_{i}.png",
                                "image_width": 520, "image_height": 340}) + "\n")
    config = {
        "annotation_task_name": "Collab drawing",
        "task_dir": ".",
        "media_directory": "media",
        "output_annotation_dir": "annotation_output",
        "data_files": ["data/scenes.jsonl"],
        "item_properties": {"id_key": "id", "text_key": "image_url"},
        "user_config": {"allow_all_users": True, "users": []},
        "require_password": False,
        "annotation_schemes": [{
            "annotation_type": "image_annotation", "name": "objects",
            "description": "Box every coloured object.", "source_field": "image_url",
            "tools": ["bbox"], "labels": [{"name": "block", "color": "#d6604d"},
                                          {"name": "partial", "color": "#4575b4"}],
        }],
        "collab": {"enabled": True, "default_mode": "free", "teams": [
            {"id": "draw", "members": ["ana", "ben"], "leader": "ana",
             "items": ["scene_1", "scene_2"]}]},
    }
    path = os.path.join(work, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the drawing server")
    yield srv
    srv.stop()


@pytest.fixture
def pair(browser_instance, server):
    browser = browser_instance
    pages, contexts = [], []
    for name in ("ana", "ben"):
        ctx = browser.new_context(base_url=server.base_url, viewport={"width": 1280, "height": 900})
        ctx.request.post(f"{server.base_url}/auth", form={"email": name, "pass": ""})
        contexts.append(ctx)
        pages.append(ctx.new_page())
    yield pages
    for ctx in contexts:
        ctx.close()


def open_item(page, iid):
    page.goto(f"/collab/s/{SID}/i/{iid}")
    page.wait_for_function("window.potatoCollabClient && window.potatoCollabClient.state.session")
    page.wait_for_function(
        "(() => { const c = document.querySelector('.image-annotation-container');"
        " return !!(c && c.annotationManager && c.annotationManager.image); })()")
    page.wait_for_timeout(400)


def draw(page, fx, fy, label="block"):
    """Drag a box from a point given as a fraction of the image."""
    page.locator(f".image-annotation-container .label-btn[data-label='{label}']").click()
    x, y = page.evaluate("""([fx, fy]) => {
        const m = document.querySelector('.image-annotation-container').annotationManager;
        const img = m.image, vt = m.canvas.viewportTransform;
        const el = m.canvas.upperCanvasEl.getBoundingClientRect();
        const p = fabric.util.transformPoint(
            {x: img.left + img.width * img.scaleX * fx, y: img.top + img.height * img.scaleY * fy}, vt);
        return [el.left + p.x, el.top + p.y];
    }""", [fx, fy])
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 30, y + 20, steps=4)
    page.mouse.move(x + 70, y + 50, steps=4)
    page.mouse.up()
    page.wait_for_timeout(300)


def shapes(page):
    """What the canvas draws, not what the hidden input says."""
    return page.evaluate("""() => {
        const m = document.querySelector('.image-annotation-container').annotationManager;
        return m.canvas.getObjects().filter(o => o.annotationData)
            .map(o => ({id: o.annotationData.id, label: o.annotationData.label}));
    }""")


def stored(page, iid):
    answer = page.request.get(f"/collab/api/{SID}/item/{iid}").json()["answer"]
    value = answer.get("L:objects:::_data")
    return json.loads(value) if value else []


def wait_for_shapes(page, n, timeout=12000):
    page.wait_for_function(
        """(n) => { const m = document.querySelector('.image-annotation-container').annotationManager;
                   return m.canvas.getObjects().filter(o => o.annotationData).length === n; }""",
        arg=n, timeout=timeout)


class TestDrawingTogether:
    def test_two_members_drawing_at_once_both_keep_their_boxes(self, pair):
        ana, ben = pair
        open_item(ana, "scene_1")
        open_item(ben, "scene_1")
        ben.evaluate("window.__sameDocument = true")

        # Both draw before either page has heard of the other's box.
        draw(ana, 0.1, 0.1, "block")
        draw(ben, 0.6, 0.5, "partial")

        wait_for_shapes(ana, 2)
        wait_for_shapes(ben, 2)
        assert ben.evaluate("window.__sameDocument === true"), "ben's page reloaded"
        ids = {s["id"] for s in shapes(ana)}
        assert ids == {s["id"] for s in shapes(ben)}
        assert sorted(s["label"] for s in shapes(ben)) == ["block", "partial"]
        ana.wait_for_timeout(1500)
        assert {s["id"] for s in stored(ana, "scene_1")} == ids

    def test_the_boxes_survive_navigating_away_and_back(self, pair):
        _, ben = pair
        open_item(ben, "scene_1")
        ben.locator("#next-btn").click()
        ben.wait_for_url(re.compile(r"/i/scene_2$"))
        ben.locator("#prev-btn").click()
        ben.wait_for_url(re.compile(r"/i/scene_1$"))
        open_item(ben, "scene_1")
        assert sorted(s["label"] for s in shapes(ben)) == ["block", "partial"]

    def test_a_box_one_member_deletes_goes_from_the_others_canvas(self, pair):
        ana, ben = pair
        open_item(ana, "scene_1")
        open_item(ben, "scene_1")
        wait_for_shapes(ben, 2)
        # Ana deletes her block with the widget's own delete path.
        ana.evaluate("""() => {
            const m = document.querySelector('.image-annotation-container').annotationManager;
            const o = m.canvas.getObjects().find(o => o.annotationData && o.annotationData.label === 'block');
            m.canvas.setActiveObject(o);
            m.deleteSelected();
        }""")
        wait_for_shapes(ben, 1)
        assert [s["label"] for s in shapes(ben)] == ["partial"]
        ana.wait_for_timeout(1500)
        assert [s["label"] for s in stored(ana, "scene_1")] == ["partial"]
