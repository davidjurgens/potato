"""
Region captioning, driven through the real interface.

The fragile part is the caption-to-region binding by list position. Adding
regions is easy; **deleting** one is where a parallel list silently leaves a
caption attached to the wrong shape, which looks exactly like a correct caption
of a different object. That is what
`test_deleting_a_region_takes_its_caption_with_it` exists for, and it is the
only test here that could not be written any other way.
"""

import json
import os

import pytest
import yaml

from tests.playwright.test_base import BasePlaywrightTest

CAPTIONS = "descriptions"
IMAGE = "region"


@pytest.fixture(scope="module")
def caption_server():
    pytest.importorskip("PIL", reason="the fixture image needs Pillow")

    from PIL import Image, ImageDraw

    from tests.helpers.flask_test_setup import FlaskTestServer
    from tests.helpers.port_manager import find_free_port
    from tests.helpers.test_utils import create_test_directory

    test_dir = create_test_directory("playwright_region_caption")
    media = os.path.join(test_dir, "media")
    os.makedirs(media, exist_ok=True)
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([60, 60, 300, 300], fill="#c0392b")
    draw.rectangle([450, 250, 720, 520], fill="#2980b9")
    image.save(os.path.join(media, "scene.png"))

    items = [{"id": f"scene_{index}", "image": "/media/scene.png"}
             for index in range(3)]
    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(items, handle)

    config = {
        "port": 0,
        "annotation_task_name": "Region captioning",
        "task_dir": test_dir,
        "media_directory": media,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "output_annotation_format": "json",
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "image"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [
            {
                "annotation_type": "image_annotation",
                "name": IMAGE,
                "description": "Draw the regions",
                "source_field": "image",
                "tools": ["bbox"],
                "labels": [{"name": "object", "color": "#6e56cf"}],
            },
            {
                "annotation_type": "region_caption",
                "name": CAPTIONS,
                "description": "Describe each region",
            },
        ],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)

    srv = FlaskTestServer(port=find_free_port(), debug=False,
                          config_file=config_path)
    if not srv.start():
        raise RuntimeError("Failed to start the region-caption server")
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestRegionCaption(BasePlaywrightTest):

    def _open(self, page, server):
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.region-caption-container[data-schema="${schema}"]`);
                const m = c && c.regionCaptionManager;
                return !!(m && m.imageManager);
            }""", arg=CAPTIONS, timeout=20_000)
        self.image_manager_ready(page, IMAGE)
        return page

    def _state(self, page):
        return page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.region-caption-container[data-schema="${schema}"]`)
                    .regionCaptionManager;
                return {entries: m.entries.map((e) => e.caption),
                        stored: m.serialize()};
            }""", arg=CAPTIONS)

    def _type_caption(self, page, index, text):
        """
        Type a caption and wait for it to be committed.

        Two waits, both load-bearing. Before: the caption box is created when
        the canvas reports its region, so typing immediately after a drag can
        land before the box exists. After: the image manager's save cycle
        clears the canvas and re-adds every object, so for a moment the region
        list is empty and the caption lives in the orphan pool — asserting
        during that window sees nothing.
        """
        page.wait_for_function(
            """({schema, index}) => {
                const container = document.querySelector(
                    `.region-caption-container[data-schema="${schema}"]`);
                const m = container && container.regionCaptionManager;
                return !!(m && m.entries.length > index
                    && document.querySelector(`[data-caption-index="${index}"]`));
            }""", arg={"schema": CAPTIONS, "index": index}, timeout=10_000)

        # A settle tick before typing. The image manager's save cycle removes
        # and re-adds every canvas object shortly after a drag; a click that
        # lands mid-cycle focuses a node that is about to be replaced, and the
        # keystrokes go nowhere. A person never types this fast.
        page.wait_for_timeout(250)
        selector = f'[data-caption-index="{index}"]'
        page.click(selector)
        page.type(selector, text, delay=10)

        page.wait_for_function(
            """({schema, index, text}) => {
                const container = document.querySelector(
                    `.region-caption-container[data-schema="${schema}"]`);
                const m = container && container.regionCaptionManager;
                return !!(m && m.entries[index]
                    && m.entries[index].caption === text);
            }""",
            arg={"schema": CAPTIONS, "index": index, "text": text},
            timeout=10_000)

    # -- the list follows the canvas -----------------------------------------

    def test_no_regions_means_an_empty_list_with_an_explanation(self, page,
                                                                caption_server):
        self._open(page, caption_server)
        assert page.locator(".region-caption-item").count() == 0
        assert "Draw one" in page.inner_text(
            f"#region-caption-progress-{CAPTIONS}")

    def test_drawing_a_region_adds_a_caption_box(self, page, caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5,
                                label="object")
        assert page.locator(".region-caption-item").count() == 1

    def test_two_regions_get_two_boxes(self, page, caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self.draw_bbox_on_image(page, IMAGE, 0.55, 0.4, 0.9, 0.9, label="object")
        assert page.locator(".region-caption-item").count() == 2

    # -- captions ------------------------------------------------------------

    def test_a_caption_is_stored_against_its_region(self, page, caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self._type_caption(page, 0, "the red square")
        stored = self._state(page)["stored"]
        assert stored["captions"][0]["caption"] == "the red square"
        assert stored["captions"][0]["region"]["type"] == "bbox"

    def test_each_region_keeps_its_own_caption(self, page, caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self._type_caption(page, 0, "the red square")
        self.draw_bbox_on_image(page, IMAGE, 0.55, 0.4, 0.9, 0.9, label="object")
        self._type_caption(page, 1, "the blue square")

        captions = [c["caption"] for c in self._state(page)["stored"]["captions"]]
        assert captions == ["the red square", "the blue square"]

    def test_typing_a_second_caption_does_not_disturb_the_first(self, page,
                                                                caption_server):
        """
        The list is rebuilt on every canvas change, so a naive rebuild would
        clear the box being typed into.
        """
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self._type_caption(page, 0, "first")
        self.draw_bbox_on_image(page, IMAGE, 0.55, 0.4, 0.9, 0.9, label="object")
        assert self._state(page)["entries"][0] == "first"

    def test_deleting_a_region_takes_its_caption_with_it(self, page,
                                                         caption_server):
        """
        The reason this schema rebuilds from the canvas and matches by region
        rather than by index. Deleting the FIRST of two regions must leave the
        second one's caption on the second region — a parallel list would slide
        it onto the wrong shape and look entirely correct.
        """
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self._type_caption(page, 0, "the red square")
        self.draw_bbox_on_image(page, IMAGE, 0.55, 0.4, 0.9, 0.9, label="object")
        self._type_caption(page, 1, "the blue square")

        # Delete the first region through the manager's own path.
        page.evaluate(
            """(schema) => {
                const m = document.querySelector(
                    `.image-annotation-container[data-schema="${schema}"]`)
                    .annotationManager;
                const shapes = m.canvas.getObjects()
                    .filter((o) => o.annotationData);
                m.canvas.setActiveObject(shapes[0]);
                m.deleteSelected();
            }""", arg=IMAGE)
        page.wait_for_timeout(300)

        remaining = [c["caption"]
                     for c in self._state(page)["stored"]["captions"]]
        assert remaining == ["the blue square"], remaining

    def test_the_progress_line_counts_described_regions(self, page,
                                                        caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self.draw_bbox_on_image(page, IMAGE, 0.55, 0.4, 0.9, 0.9, label="object")
        self._type_caption(page, 0, "the red square")
        assert "1 of 2" in page.inner_text(
            f"#region-caption-progress-{CAPTIONS}")

    # -- accessibility -------------------------------------------------------

    def test_every_caption_box_has_a_label(self, page, caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        label_for = page.get_attribute(".region-caption-label", "for")
        assert label_for, "the caption box has no associated label"
        # The id is unique per row rather than positional: rows persist across
        # reconciliation and two rows must never share an id.
        assert page.locator(f'[id="{label_for}"]').count() == 1

    # -- persistence ---------------------------------------------------------

    def test_captions_survive_navigating_away_and_back(self, page,
                                                       caption_server):
        self._open(page, caption_server)
        self.draw_bbox_on_image(page, IMAGE, 0.05, 0.05, 0.4, 0.5, label="object")
        self._type_caption(page, 0, "the red square")
        self.wait_for_debounce(page)

        self.click_next(page)
        page.wait_for_timeout(500)
        self.click_prev(page)
        page.wait_for_function(
            """(schema) => {
                const c = document.querySelector(
                    `.region-caption-container[data-schema="${schema}"]`);
                return !!(c && c.regionCaptionManager
                          && c.regionCaptionManager.imageManager);
            }""", arg=CAPTIONS, timeout=20_000)
        page.wait_for_timeout(800)

        captions = [c["caption"]
                    for c in self._state(page)["stored"]["captions"]]
        assert captions == ["the red square"], captions
