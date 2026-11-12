"""``--seed-user --as-machine-annotator`` writes a declared rater.

``--seed-user`` fabricates an annotator. Its own warning says so, and says the
rows must be kept out of agreement and adjudication analysis -- which made
imported predictions unusable for the one thing someone importing several
tools' output wants to do with them.

The flag does not remove the fabrication. It declares it: the seeded state
carries an origin, so the rows are a named machine rater's rather than an
anonymous person's, and the measurement code can separate them. The importer
guard was never against machines being raters, only against machines being
raters in disguise.
"""

from __future__ import annotations

import json
import os

import pytest

from potato.annotator_origin import is_human, is_machine, origin_of
from potato.importers.cli import _write_seed_user, parse_args


class FakeImage:
    def __init__(self, instance_id, objects):
        self.instance_id = instance_id
        self.objects = objects


class FakeResult:
    def __init__(self, images):
        self.images = images


def _result():
    return FakeResult([
        FakeImage("img_1", [{"label": "cat"}]),
        FakeImage("img_2", []),          # a confirmed negative, not a skip
    ])


def _state(user_dir):
    with open(os.path.join(user_dir, "user_state.json")) as handle:
        return json.load(handle)


def _origin(state):
    """The rater's origin, extracted the way the export path extracts it.

    ``origin_of`` interprets a mapping as an origin, so handing it a whole user
    state makes it look for ``kind`` at the top level, fail to find one, and
    read the state as a malformed machine. ``export.cli._annotator_origin``
    pulls the nested key out first; so does this.
    """
    return origin_of(state.get("origin"))


class TestFlagParsing:
    BASE = ["--input-format", "coco", "--input", "x.json",
            "--output-dir", "out", "--seed-user", "prokka"]

    def _parse(self, extra, monkeypatch):
        monkeypatch.setattr("sys.argv", ["potato-import"] + self.BASE + extra)
        return parse_args()

    def test_absent_is_none(self, monkeypatch):
        assert self._parse([], monkeypatch).as_machine_annotator is None

    def test_bare_flag_defaults_to_tool(self, monkeypatch):
        args = self._parse(["--as-machine-annotator"], monkeypatch)
        assert args.as_machine_annotator == "tool"

    def test_explicit_kind_is_kept(self, monkeypatch):
        args = self._parse(["--as-machine-annotator", "llm"], monkeypatch)
        assert args.as_machine_annotator == "llm"

    def test_an_unknown_kind_is_refused(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._parse(["--as-machine-annotator", "wetware"], monkeypatch)


class TestSeededStateWithoutTheFlag:
    """Unchanged: still a fabricated person, because that is what it is."""

    def test_no_origin_is_written(self, tmp_path):
        out = str(tmp_path)
        _write_seed_user(out, "seeded", "objects", _result())
        state = _state(os.path.join(out, "annotation_output", "seeded"))
        assert "origin" not in state

    def test_it_reads_as_human(self, tmp_path):
        out = str(tmp_path)
        _write_seed_user(out, "seeded", "objects", _result())
        state = _state(os.path.join(out, "annotation_output", "seeded"))
        assert is_human(_origin(state))


class TestSeededStateWithTheFlag:
    def test_origin_is_written(self, tmp_path):
        out = str(tmp_path)
        _write_seed_user(out, "prokka", "objects", _result(),
                         machine_kind="tool", source_format="coco")
        state = _state(os.path.join(out, "annotation_output", "prokka"))
        assert is_machine(_origin(state))
        assert _origin(state)["kind"] == "tool"
        assert _origin(state)["id"] == "prokka"

    def test_the_source_format_is_recorded_as_the_tool(self, tmp_path):
        out = str(tmp_path)
        _write_seed_user(out, "prokka", "objects", _result(),
                         machine_kind="tool", source_format="coco")
        state = _state(os.path.join(out, "annotation_output", "prokka"))
        assert state["origin"]["tool"] == "coco"

    def test_it_says_the_declaration_came_from_the_import(self, tmp_path):
        # Distinguishable from a roster declaration, which says "config".
        out = str(tmp_path)
        _write_seed_user(out, "prokka", "objects", _result(),
                         machine_kind="llm")
        state = _state(os.path.join(out, "annotation_output", "prokka"))
        assert state["origin"]["declared_in"] == "import"
        assert state["origin"]["kind"] == "llm"

    def test_it_carries_a_timestamp(self, tmp_path):
        out = str(tmp_path)
        _write_seed_user(out, "prokka", "objects", _result(),
                         machine_kind="tool")
        state = _state(os.path.join(out, "annotation_output", "prokka"))
        assert state["origin"]["recorded_at"].startswith("20")

    def test_the_annotations_are_still_written(self, tmp_path):
        """Declaring the rater must not change what it annotated."""
        out = str(tmp_path)
        _write_seed_user(out, "prokka", "objects", _result(),
                         machine_kind="tool")
        state = _state(os.path.join(out, "annotation_output", "prokka"))
        labels = state["instance_id_to_label_to_value"]
        assert set(labels) == {"img_1", "img_2"}
        # The empty image is a recorded negative, not an omission.
        assert json.loads(labels["img_2"][0][1]) == []
