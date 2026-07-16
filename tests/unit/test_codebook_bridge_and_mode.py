"""Schema-loader codebook bridge + codebook_mode config resolution."""

import pytest

from potato.codebook import create_code
from potato.codebook.codebook import Codebook
from potato.codebook.schema_bridge import apply_codebook_to_schemes
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.persistence import (
    clear_db_cache,
    clear_migrations,
    register_migration,
)
from potato.server_utils.config_module import (
    ConfigValidationError,
    get_codebook_mode,
    validate_codebook_config,
)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    register_migration(_CODEBOOK_MIGRATION)
    yield
    clear_db_cache()
    clear_migrations()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class TestSchemaBridge:
    def test_seeds_codebook_from_yaml_labels(self, td):
        cfg = {
            "task_dir": td,
            "annotation_task_name": "P",
            "annotation_schemes": [{
                "name": "s", "annotation_type": "radio",
                "codebook": True,
                "labels": ["alpha", {"name": "beta"}],
            }],
        }
        apply_codebook_to_schemes(cfg)
        assert cfg["annotation_schemes"][0]["labels"] == ["alpha", "beta"]
        assert Codebook.load(td, "P").labels() == ["alpha", "beta"]

    def test_idempotent_second_call(self, td):
        cfg = {
            "task_dir": td, "annotation_task_name": "P",
            "annotation_schemes": [{
                "name": "s", "annotation_type": "radio",
                "codebook": True, "labels": ["x"]}],
        }
        apply_codebook_to_schemes(cfg)
        apply_codebook_to_schemes(cfg)
        assert len(Codebook.load(td, "P")) == 1

    def test_seeds_from_every_codebook_scheme_not_just_the_first(self, td):
        """A label declared only on a later scheme must still reach the codebook.

        Codebook-backed schemes share one codebook, and seeding was gated on
        `is_empty()` *inside* the per-scheme loop: the first scheme closed the
        gate, so every later scheme's own labels were dropped and never
        rendered anywhere. Every other test here uses a single codebook scheme,
        which is why this went unseen.
        """
        cfg = {
            "task_dir": td, "annotation_task_name": "P",
            "annotation_schemes": [
                {"name": "codes", "annotation_type": "span",
                 "codebook": True, "labels": ["a", "b"]},
                {"name": "themes", "annotation_type": "multiselect",
                 "codebook": True, "labels": ["a", "b", "only_on_themes"]},
            ],
        }
        apply_codebook_to_schemes(cfg)
        assert "only_on_themes" in Codebook.load(td, "P").labels()
        # Both schemes source the same shared codebook.
        assert cfg["annotation_schemes"][0]["labels"] == \
               cfg["annotation_schemes"][1]["labels"]
        assert "only_on_themes" in cfg["annotation_schemes"][0]["labels"]

    def test_multi_scheme_seed_does_not_resurrect_deleted_codes(self, td):
        """Seeding stays a first-run bootstrap, even across several schemes."""
        from potato.codebook.service import delete_code

        def cfg():
            return {
                "task_dir": td, "annotation_task_name": "P",
                "annotation_schemes": [
                    {"name": "codes", "annotation_type": "span",
                     "codebook": True, "labels": ["a"]},
                    {"name": "themes", "annotation_type": "multiselect",
                     "codebook": True, "labels": ["a", "doomed"]},
                ],
            }

        apply_codebook_to_schemes(cfg())
        book = Codebook.load(td, "P")
        assert "doomed" in book.labels()
        delete_code(td, project="P", code_id=book.label_to_id()["doomed"])

        second = cfg()
        apply_codebook_to_schemes(second)   # restart
        assert "doomed" not in second["annotation_schemes"][1]["labels"]

    def test_db_is_source_of_truth_after_seed(self, td):
        create_code(td, project="P", name="from_db", created_by="alice")
        cfg = {
            "task_dir": td, "annotation_task_name": "P",
            "annotation_schemes": [{
                "name": "s", "annotation_type": "radio",
                "codebook": True, "labels": ["ignored_yaml"]}],
        }
        apply_codebook_to_schemes(cfg)
        # codebook non-empty -> YAML labels are NOT re-seeded
        assert cfg["annotation_schemes"][0]["labels"] == ["from_db"]

    def test_non_codebook_scheme_untouched(self, td):
        cfg = {
            "task_dir": td, "annotation_task_name": "P",
            "annotation_schemes": [{
                "name": "s", "annotation_type": "radio",
                "labels": ["keep"]}],
        }
        apply_codebook_to_schemes(cfg)
        assert cfg["annotation_schemes"][0]["labels"] == ["keep"]
        assert Codebook.load(td, "P").is_empty()


class TestCodebookModeResolution:
    def test_default_standard_is_fixed(self):
        assert get_codebook_mode({}) == "fixed"

    def test_qda_default_open(self):
        assert get_codebook_mode(
            {"qda_mode": {"enabled": True}}) == "open"

    def test_solo_default_open(self):
        assert get_codebook_mode(
            {"solo_mode": {"enabled": True}}) == "open"

    def test_explicit_scalar_wins(self):
        assert get_codebook_mode({"codebook_mode": "extensible"}) \
            == "extensible"

    def test_block_mode_used(self):
        assert get_codebook_mode(
            {"codebook": {"mode": "open"}}) == "open"

    def test_crowd_force_locks_fixed(self):
        assert get_codebook_mode(
            {"codebook_mode": "open", "prolific": {}}) == "fixed"
        assert get_codebook_mode(
            {"codebook_mode": "open",
             "login": {"type": "mturk"}}) == "fixed"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ConfigValidationError):
            validate_codebook_config({"codebook_mode": "bogus"})

    def test_valid_modes_accepted(self):
        for m in ("fixed", "extensible", "open"):
            validate_codebook_config({"codebook_mode": m})  # no raise
