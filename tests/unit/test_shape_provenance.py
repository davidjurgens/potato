"""Where a shape came from, on the server side of the round trip.

The client stamps `source` on every shape it makes (tests/jest/shape-provenance.test.js).
This covers the three places that fact can be lost afterwards: the two
conversions in cv_utils, the import path, and the COCO exporter.

The import case is the one worth stating plainly. A project seeded from an
existing dataset has shapes nobody in the study ever drew, and once stored they
are byte-identical to hand-drawn ones -- so the export reports every imported
box as annotation effort, which is the number a paper would then cite.
"""

import json
import os

from potato.export.cv_utils import (
    carry_provenance,
    normalize_annotation_object,
    to_client_object,
)
from potato.importers.base import ImportedImage, ImportResult
from tests.helpers.test_utils import create_test_directory


IMG_W, IMG_H = 640, 480


class TestCarryProvenance:
    def test_copies_only_what_the_source_declares(self):
        target = {"type": "bbox"}
        carry_provenance(target, {"source": "ai", "ai_model": "yolov8n",
                                  "label": "cell"})
        assert target == {"type": "bbox", "source": "ai", "ai_model": "yolov8n"}

    def test_absent_stays_absent(self):
        # 'human' is the tempting default and it is wrong for every dataset
        # seeded from a detector before this field existed.
        target = {"type": "bbox"}
        carry_provenance(target, {"label": "cell"})
        assert "source" not in target

    def test_a_confidence_of_zero_is_a_real_score(self):
        target = {}
        carry_provenance(target, {"source": "ai", "confidence": 0})
        assert target["confidence"] == 0

    def test_an_empty_string_carries_nothing(self):
        target = {}
        carry_provenance(target, {"source": "ai", "ai_model": ""})
        assert "ai_model" not in target


class TestConversionsPreserveIt:
    def test_normalize_keeps_provenance(self):
        canon = normalize_annotation_object({
            "type": "bbox", "label": "cell", "color": "#0f0",
            "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
            "source": "ai", "ai_model": "yolov8n", "confidence": 0.82,
        }, IMG_W, IMG_H)

        assert canon["source"] == "ai"
        assert canon["ai_model"] == "yolov8n"
        assert canon["confidence"] == 0.82

    def test_to_client_object_carries_provenance(self):
        obj = to_client_object(
            "bbox", "cell", "#0f0", img_w=IMG_W, img_h=IMG_H,
            bbox=[64, 96, 192, 120],
            provenance={"source": "import", "import_format": "coco"})

        assert obj["source"] == "import"
        assert obj["import_format"] == "coco"

    def test_a_full_round_trip_keeps_it(self):
        client = to_client_object(
            "bbox", "cell", "#0f0", img_w=IMG_W, img_h=IMG_H,
            bbox=[64, 96, 192, 120],
            provenance={"source": "ai", "ai_model": "yolov8n"})
        canon = normalize_annotation_object(client, IMG_W, IMG_H)
        assert canon["source"] == "ai"
        assert canon["ai_model"] == "yolov8n"


class TestImportStamping:
    def _result(self, objects):
        return ImportResult(images=[ImportedImage(
            instance_id="img1", file_name="img1.jpg",
            width=IMG_W, height=IMG_H, objects=objects)])

    def test_unmarked_objects_become_imports(self):
        result = self._result([{"type": "bbox", "label": "cell"}])
        assert result.stamp_import_provenance("coco") == 1
        obj = result.images[0].objects[0]
        assert obj["source"] == "import"
        assert obj["import_format"] == "coco"

    def test_an_existing_source_is_never_overwritten(self):
        # A COCO file Potato itself wrote says who drew each shape. Restamping
        # it as 'import' would erase the person/model split on every round trip
        # -- the one thing the field exists to survive.
        result = self._result([
            {"type": "bbox", "label": "cell", "source": "human"},
            {"type": "bbox", "label": "cell", "source": "ai",
             "ai_model": "yolov8n"},
        ])
        assert result.stamp_import_provenance("coco") == 0
        assert [o["source"] for o in result.images[0].objects] == ["human", "ai"]

    def test_format_is_optional(self):
        result = self._result([{"type": "bbox", "label": "cell"}])
        result.stamp_import_provenance()
        assert result.images[0].objects[0]["source"] == "import"
        assert "import_format" not in result.images[0].objects[0]


class TestASeededProjectBoots:
    """`potato import --seed-user NAME` wrote a two-key user_state.json, and
    `InMemoryUserState.load` indexed `max_assignments` and five more keys
    directly. So the importer printed "Run it: ..." and the server it named
    died at boot with `KeyError: 'max_assignments'`.

    Both halves are fixed and both are tested: the loader defaults what is
    absent (which also covers state files written by older Potatoes), and the
    seeder writes the keys a real state carries, because a seeded annotator
    owning no assignments is not the annotator the flag claims to fabricate.
    """

    def test_the_loader_survives_a_minimal_state_file(self, tmp_path):
        import json

        from potato.user_state_management import InMemoryUserState

        user_dir = tmp_path / "seeded"
        user_dir.mkdir()
        (user_dir / "user_state.json").write_text(json.dumps({
            "user_id": "seeded",
            "instance_id_to_label_to_value": {},
        }))

        state = InMemoryUserState.load(str(user_dir))
        assert state.get_user_id() == "seeded"
        assert state.get_max_assignments() == -1
        assert state.instance_id_ordering == []

    def test_the_seeder_writes_the_keys_the_loader_reads(self, tmp_path):
        from potato.importers.base import ImportedImage, ImportResult
        from potato.importers.cli import _write_seed_user
        from potato.user_state_management import InMemoryUserState

        result = ImportResult(images=[ImportedImage(
            instance_id="img1", file_name="img1.jpg",
            width=IMG_W, height=IMG_H,
            objects=[{"type": "bbox", "label": "cell", "source": "import"}])])
        _write_seed_user(str(tmp_path), "seeded", "regions", result)

        import json

        user_dir = tmp_path / "annotation_output" / "seeded"

        # Two claims, measured on the two things they are about.
        #
        # That the server can READ it: driven through the real loader, which is
        # the code that used to raise KeyError at boot.
        state = InMemoryUserState.load(str(user_dir))
        assert state.get_user_id() == "seeded"

        # That the seeded annotator OWNS the items: read off the file, because
        # `load` prunes assignments against the live item manager and there is
        # no item manager in a unit test -- the ordering it returns here is
        # legitimately empty. Without this, a fully annotated project reads as
        # zero progress.
        with open(user_dir / "user_state.json") as fh:
            written = json.load(fh)
        assert written["instance_id_ordering"] == ["img1"]
        assert written["max_assignments"] == -1


class TestImportCliWiring:
    """The stamp has to be CALLED, not merely defined.

    Every assertion above passes with the call site in `_write_project`
    deleted, because they drive the method directly. This drives the CLI.
    """

    def _coco_file(self, test_dir):
        path = os.path.join(test_dir, "instances.json")
        with open(path, "w") as fh:
            json.dump({
                "images": [{"id": 1, "file_name": "img1.jpg",
                            "width": IMG_W, "height": IMG_H}],
                "categories": [{"id": 1, "name": "cell"}],
                "annotations": [{"id": 1, "image_id": 1, "category_id": 1,
                                 "bbox": [64, 96, 192, 120], "area": 23040,
                                 "iscrowd": 0, "segmentation": []}],
            }, fh)
        return path

    def test_an_imported_project_says_its_boxes_were_imported(self):
        from potato.importers.cli import main

        test_dir = create_test_directory("import_provenance")
        source = self._coco_file(test_dir)
        out_dir = os.path.join(test_dir, "project")

        assert main(["--input", source, "--output-dir", out_dir,
                     "--schema-name", "regions"]) == 0

        data_path = os.path.join(out_dir, "data", "instances.json")
        with open(data_path) as fh:
            row = json.loads(fh.readline())

        obj = row["predictions"]["regions"][0]
        assert obj["source"] == "import"
        assert obj["import_format"] == "coco"

    def test_the_seeded_annotator_carries_it_too(self):
        from potato.importers.cli import main

        test_dir = create_test_directory("import_provenance_seed")
        source = self._coco_file(test_dir)
        out_dir = os.path.join(test_dir, "project")

        assert main(["--input", source, "--output-dir", out_dir,
                     "--schema-name", "regions",
                     "--seed-user", "seeded"]) == 0

        state_path = os.path.join(out_dir, "annotation_output", "seeded",
                                  "user_state.json")
        with open(state_path) as fh:
            state = json.load(fh)
        stored = state["instance_id_to_label_to_value"]["1"]
        objects = json.loads(stored[0][1])
        assert objects[0]["source"] == "import"


class TestConfidenceHasOneHome:
    """A detector's score means the same thing whatever format it arrived in.

    `confidence` was in PROVENANCE_KEYS and no import path wrote it, while
    `mot` and `openimages` wrote the same quantity into `attributes`. Two homes
    and the new one empty is how a field goes stale before anyone uses it.
    """

    def test_coco_score_becomes_confidence(self):
        from potato.importers.coco_importer import COCOImporter

        result = COCOImporter().parse({
            "images": [{"id": 1, "file_name": "a.jpg",
                        "width": IMG_W, "height": IMG_H}],
            "categories": [{"id": 1, "name": "cell"}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1,
                             "bbox": [10, 10, 50, 50], "area": 2500,
                             "iscrowd": 0, "segmentation": [], "score": 0.4}],
        }, {})
        obj = result.images[0].objects[0]
        assert obj["confidence"] == 0.4, (
            "a COCO results file that knows the detector was 40% sure "
            "imported as a shape that says only that it was imported")

    def test_a_score_of_zero_survives(self):
        # The value most likely to be eaten by a truthiness test, and a real
        # answer: the detector was not confident at all.
        from potato.importers.coco_importer import COCOImporter

        result = COCOImporter().parse({
            "images": [{"id": 1, "file_name": "a.jpg",
                        "width": IMG_W, "height": IMG_H}],
            "categories": [{"id": 1, "name": "cell"}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1,
                             "bbox": [10, 10, 50, 50], "area": 2500,
                             "iscrowd": 0, "segmentation": [], "score": 0.0}],
        }, {})
        assert result.images[0].objects[0]["confidence"] == 0.0

    #: Every spelling a source format uses for a detector's own score. COCO
    #: says `score`, KITTI's 16th column is a score, Open Images says
    #: `Confidence`, MOT says `conf`. They are one quantity and they get one
    #: column; `confidence`, at the top level.
    SCORE_SPELLINGS = ("confidence", "score", "conf", "Confidence")

    def test_no_importer_writes_a_score_into_attributes(self, tmp_path):
        """The second home, closed for every spelling rather than for the one
        word I first searched for.

        My original version of this grepped for `attributes["confidence"]`,
        which is exactly as wide as the claim I had already made and no wider.
        KITTI writes the same quantity as `attributes["score"]` and the guard
        could not see it — a narrower instrument agreeing with the sentence
        that produced it.
        """
        import glob
        import os
        import re

        root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "potato", "importers")
        paths = glob.glob(os.path.join(root, "*.py"))
        assert len(paths) > 10, (
            f"only {len(paths)} importer files found under {root}; the sweep "
            f"is looking in the wrong place and would report clean")

        pattern = re.compile(
            r"""attributes\[["'](""" + "|".join(self.SCORE_SPELLINGS) + r""")["']\]""")
        offenders = []
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if pattern.search(line):
                        offenders.append(f"{os.path.basename(path)}:{lineno}")
        assert not offenders, (
            "a detector's score belongs at the top level as `confidence`, "
            "where the client round-trips it and the COCO exporter writes it. "
            f"Second home found at: {offenders}")

    def test_the_sweep_can_actually_fail(self, tmp_path):
        # The counter-guard. A regex that matches nothing anywhere reports the
        # same clean result as a codebase with no second home.
        import re

        pattern = re.compile(
            r"""attributes\[["'](""" + "|".join(self.SCORE_SPELLINGS) + r""")["']\]""")
        for spelling in self.SCORE_SPELLINGS:
            assert pattern.search(f'    attributes["{spelling}"] = value'), spelling
        assert not pattern.search('    obj["confidence"] = value')


class TestEveryWrittenObjectHasAnOrigin:
    def test_the_writer_refuses_an_unstamped_object(self, tmp_path):
        """`stamp_import_provenance` living in the writer made the invariant a
        convention: a future writer that forgot would ship shapes with no
        origin and nothing would fail."""
        import pytest

        from potato.importers import cli

        class Parsed:
            output_dir = str(tmp_path / "proj")
            schema_name = "regions"
            config_only = False
            seed_user = None
            image_url_prefix = ""

        result = ImportResult(images=[ImportedImage(
            instance_id="img1", file_name="img1.jpg",
            width=IMG_W, height=IMG_H,
            objects=[{"type": "bbox", "label": "cell"}])])
        # A stamper that reaches nothing, standing in for a future path that
        # builds objects the stamper does not know about.
        result.stamp_import_provenance = lambda fmt="": 0

        with pytest.raises(AssertionError, match="no `source`"):
            cli._write_project(Parsed(), result, source="x.json")


class TestCocoExport:
    def test_the_exported_annotation_names_its_origin(self):
        from potato.export.coco_exporter import COCOExporter
        from potato.export.base import ExportContext

        annotations = [{
            "instance_id": "img1",
            "user_id": "annotator_a",
            "labels": {},
            "image_annotations": {"regions": [{
                "type": "bbox", "label": "cell", "color": "#0f0",
                "coordinates": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
                "source": "ai", "ai_model": "yolov8n", "confidence": 0.82,
            }]},
        }]
        items = {"img1": {"id": "img1", "file_name": "img1.jpg",
                          "image_width": IMG_W, "image_height": IMG_H}}
        test_dir = create_test_directory("coco_provenance")
        out = os.path.join(test_dir, "coco")
        os.makedirs(out, exist_ok=True)
        context = ExportContext(
            annotations=annotations,
            schemas=[{"annotation_type": "image_annotation", "name": "regions",
                      "labels": ["cell"]}],
            config={},
            items=items,
            output_dir=out,
        )
        COCOExporter().export(context, out)

        with open(os.path.join(out, "annotations.json")) as fh:
            coco = json.load(fh)
        ann = coco["annotations"][0]
        assert ann["source"] == "ai"
        assert ann["ai_model"] == "yolov8n"
        assert ann["confidence"] == 0.82
