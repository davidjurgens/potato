"""Codebook: per-coder review flags, one seeding path, `--dry-run`, exports.

- A restamp flags the coder whose coding changed, not every coder of the
  instance (links are keyed per coder; touch_instances takes the annotator).
- `potato codebook` and the server seed codes the same way: deterministic id,
  the label's colour, its description as the definition. The CLI used to
  create bare names, and the server then skipped seeding because the codebook
  was no longer empty.
- `potato codebook --dry-run` through the real entry point writes nothing.
- codebook.csv and .qdpx read a `codebook: true` scheme's tree and colours
  from the codebook rather than the bare label list the bridge leaves behind.
"""

import csv
import os
import sys
import textwrap
import xml.etree.ElementTree as ET
import zipfile

import pytest

from potato.codebook import (
    blocks,
    clear_change_listeners,
    content_service,
    create_code,
    record_annotation,
    stale_instances,
    touch_instances,
)
from potato.codebook import service, store
from potato.codebook.codebook import Codebook
from potato.codebook.schema_bridge import (
    apply_codebook_to_schemes,
    deterministic_code_id,
)
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import clear_db_cache, clear_migrations, register_migration


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


# ---- per-coder review flags ---------------------------------------------


class TestRestampIsPerCoder:
    def test_touch_with_a_username_flags_only_that_coder(self, td):
        create_code(td, project="P", name="a", created_by="u")
        record_annotation(td, "P", "i1", "alice")
        record_annotation(td, "P", "i1", "bob")
        touch_instances(td, "P", ["i1"], username="alice")
        assert [s["instance_id"] for s in stale_instances(td, "P", "alice")] == ["i1"]
        assert stale_instances(td, "P", "bob") == []

    def test_a_definition_edit_flags_the_coder_who_used_the_code(self, td):
        x = create_code(td, project="P", name="x", created_by="u")
        y = create_code(td, project="P", name="y", created_by="u")
        # Same instance, different codes.
        service.sync_annotation_links(td, project="P", instance_id="i1",
                                      username="alice", code_ids={x["id"]})
        service.sync_annotation_links(td, project="P", instance_id="i1",
                                      username="bob", code_ids={y["id"]})
        record_annotation(td, "P", "i1", "alice")
        record_annotation(td, "P", "i1", "bob")

        content_service.save_scope(
            td, project="P", scope_kind="code", scope_id=x["id"],
            blocks_in=[{"block_type": "definition", "body_md": "new"}],
            base_version=0, actor="u")

        assert [s["instance_id"] for s in stale_instances(td, "P", "alice")] == ["i1"]
        assert stale_instances(td, "P", "bob") == []

    def test_a_legacy_bare_key_still_flags_the_instance(self, td):
        x = create_code(td, project="P", name="x", created_by="u")
        store.link_annotation(td, project="P", annotation_id="i1",
                              code_id=x["id"], created_by="old")
        record_annotation(td, "P", "i1", "alice")
        service._restamp(td, "P", [x["id"]])
        assert [s["instance_id"] for s in stale_instances(td, "P", "alice")] == ["i1"]


# ---- seeding --------------------------------------------------------------


def _write_config(tmp_path, labels_yaml):
    proj = tmp_path / "seedproj"
    proj.mkdir()
    (proj / "data").mkdir()
    (proj / "data" / "d.json").write_text('[{"id":"1","text":"x"}]')
    cfg = proj / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        annotation_task_name: P
        task_dir: .
        data_files: [data/d.json]
        annotation_schemes:
        - annotation_type: radio
          name: s
          description: d
          codebook: true
          labels:
    """) + textwrap.indent(labels_yaml, "    "))
    return str(cfg), str(proj)


def _server_config(proj, labels):
    return {"annotation_task_name": "P", "task_dir": proj,
            "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                    "description": "d", "codebook": True,
                                    "labels": labels}]}


_LABELS_YAML = textwrap.dedent("""\
    - name: A
      description: def A
      color: "#f00"
""")


class TestOneSeedingPath:
    def test_cli_seed_keeps_colour_and_description(self, tmp_path):
        from potato.codebook_cli import init_codebook
        cfg, proj = _write_config(tmp_path, _LABELS_YAML)
        assert init_codebook(cfg)["created"] == 1

        # Then the server starts on the now non-empty codebook.
        apply_codebook_to_schemes(_server_config(proj, [
            {"name": "A", "description": "def A", "color": "#f00"}]),
            task_dir=proj)

        code = next(c for c in Codebook.load(proj, "P")._codes if c["name"] == "A")
        assert code["color"] == "#f00"
        assert blocks.gloss_by_code(proj, "P").get(code["id"]) == "def A"

    def test_server_seed_uses_the_deterministic_id(self, td):
        apply_codebook_to_schemes(_server_config(td, ["alpha", "beta"]), task_dir=td)
        ids = {c["name"]: c["id"] for c in Codebook.load(td, "P")._codes}
        assert ids == {"alpha": deterministic_code_id("P", "", "alpha"),
                       "beta": deterministic_code_id("P", "", "beta")}

    def test_reseeding_after_a_rename_is_a_no_op(self, tmp_path):
        from potato.codebook_cli import init_codebook
        cfg, proj = _write_config(tmp_path, _LABELS_YAML)
        init_codebook(cfg)
        cid = deterministic_code_id("P", "", "A")
        service.rename_code(proj, cid, new_name="A renamed", project="P")
        # The renamed code still holds A's id; seeding A again must not
        # collide on it.
        init_codebook(cfg)
        assert [c["name"] for c in Codebook.load(proj, "P")._codes] == ["A renamed"]


class TestDryRunThroughTheEntryPoint:
    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch, capsys):
        from potato import flask_server
        cfg, proj = _write_config(tmp_path, _LABELS_YAML)
        monkeypatch.setattr(sys, "argv", ["potato", "codebook", cfg, "--dry-run"])
        with pytest.raises(SystemExit) as exc:
            flask_server.main()
        assert exc.value.code == 0
        assert "Would create 1 code(s)" in capsys.readouterr().out
        assert Codebook.load(proj, "P").is_empty()


# ---- exports ----------------------------------------------------------------


def _export_context(td):
    from potato.export.base import ExportContext
    config = _server_config(td, ["P", "C"])
    apply_codebook_to_schemes(config, task_dir=td, seed=False)
    return ExportContext(config=config, annotations=[], items={},
                         schemas=config["annotation_schemes"], output_dir="")


@pytest.fixture
def nested_codebook(td):
    p = create_code(td, project="P", name="P", created_by="u", color="#f00")
    c = create_code(td, project="P", name="C", created_by="u", color="#0f0",
                    parent_id=p["id"])
    content_service.save_scope(
        td, project="P", scope_kind="code", scope_id=c["id"],
        blocks_in=[{"block_type": "short_def", "body_md": "child code"}],
        base_version=0, actor="u")
    assert os.path.exists(os.path.join(td, "project.sqlite"))
    return td


class TestExportsReadTheCodebook:
    def test_csv_has_parent_and_colour(self, nested_codebook, tmp_path):
        from potato.export.codebook_exporter import CodebookExporter
        out = tmp_path / "out"
        result = CodebookExporter().export(_export_context(nested_codebook), str(out))
        assert result.success
        with open(out / "codebook.csv", newline="") as f:
            rows = {r["code"]: r for r in csv.DictReader(f)}
        assert rows["C"]["parent"] == "P" and rows["C"]["color"] == "#0f0"
        assert rows["C"]["description"] == "child code"
        assert rows["P"]["parent"] == "" and rows["P"]["color"] == "#f00"

    def test_qdpx_nests_the_child(self, nested_codebook, tmp_path):
        from potato.export.qdpx_exporter import QDPXExporter
        out = tmp_path / "out"
        result = QDPXExporter().export(_export_context(nested_codebook), str(out))
        assert result.success
        with zipfile.ZipFile(result.files_written[0]) as z:
            root = ET.fromstring(z.read("project.qde"))
        codes = [e for e in root.iter() if e.tag.endswith("}Code")]
        parent = next(c for c in codes if c.get("name") == "P")
        kids = [k.get("name") for k in parent if k.tag.endswith("}Code")]
        assert kids == ["C"]
        child = next(c for c in codes if c.get("name") == "C")
        assert child.get("color") == "#0f0"
        desc = [d.text for d in child if d.tag.endswith("}Description")]
        assert desc == ["child code"]


def test_paper_metrics_take_the_codes_from_the_live_codebook(td):
    """Audit 105 A2: the snapshot's agreement read the YAML labels. A code
    merged away still counted (everyone agreeing on "not"), and a code added
    mid-study was missing."""
    import yaml
    from potato.paper.collect import collect_project
    create_code(td, project="P", name="added", created_by="u")
    config = {"annotation_task_name": "P", "task_dir": ".",
              "data_files": [], "output_annotation_dir": "out",
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [{"name": "themes", "annotation_type": "multiselect",
                                      "codebook": True, "description": "T",
                                      "labels": ["yaml-only"]}]}
    path = os.path.join(td, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    project = collect_project(path)
    labels = [l if isinstance(l, str) else l.get("name")
              for l in project.config["annotation_schemes"][0]["labels"]]
    assert "added" in labels and "yaml-only" not in labels


def test_a_split_with_nothing_to_move_changes_nothing(td):
    """Audit 105 A3: it created the empty target code and bumped the
    revision, which marks every earlier-stamped instance for review."""
    from potato.codebook import revision
    src = create_code(td, project="P", name="src", created_by="u")
    before = revision.current_revision(td, "P")
    result = service.split_code(td, project="P", src_id=src["id"], annotator="nobody",
                                new_name="would-be")
    assert result["moved"] == 0 and result["target_id"] is None
    assert "would-be" not in Codebook.load(td, "P").label_to_id()
    assert revision.current_revision(td, "P") == before
