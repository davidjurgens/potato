"""A select's `labels` can name a text file of options, one per line.

The select generator read a string `labels` as a path, relative to the working
directory and with no path check, but validation refused every string first,
so the option could not be used. The file is now read when the config loads,
inside task_dir, and `labels` becomes the list.
"""

import json
import os

import pytest
import yaml

from potato.server_utils.config_module import (
    ConfigSecurityError,
    ConfigValidationError,
    load_and_validate_config,
    validate_single_annotation_scheme,
)
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _project(name, scheme, files=None, extra=None):
    """A project dir with one data file, `files` written into it, and a config."""
    test_dir = create_test_directory(name)
    for rel, content in (files or {}).items():
        path = os.path.join(test_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    with open(os.path.join(test_dir, "data.jsonl"), "w") as handle:
        handle.write(json.dumps({"id": "1", "text": "item"}) + "\n")
    config = {
        "annotation_task_name": name,
        "task_dir": ".",
        "output_annotation_dir": "out",
        "data_files": [os.path.join(test_dir, "data.jsonl")],
        "item_properties": {"id_key": "id", "text_key": "text"},
    }
    if scheme is not None:
        config["annotation_schemes"] = [scheme]
    config.update(extra or {})
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as handle:
        yaml.safe_dump(config, handle)
    return test_dir, path


def _select(labels, **more):
    scheme = {"annotation_type": "select", "name": "lang", "description": "Language?",
              "labels": labels}
    scheme.update(more)
    return scheme


def _load(name, scheme, files=None, extra=None):
    test_dir, path = _project(name, scheme, files, extra)
    return load_and_validate_config(path, test_dir), test_dir


class TestTheFileBecomesTheList:
    def test_one_option_per_line_in_order(self):
        config, _ = _load("select_file_basic", _select("options/langs.txt"),
                          {"options/langs.txt": "English\nFrench\nSwahili\n"})
        assert config["annotation_schemes"][0]["labels"] == ["English", "French", "Swahili"]

    def test_a_bom_crlf_and_blank_lines_are_not_kept(self):
        content = "﻿English\r\n\r\n   \r\n  French  \r\nSwahili"
        config, _ = _load("select_file_bom", _select("langs.txt"),
                          {"langs.txt": content.encode("utf-8")})
        assert config["annotation_schemes"][0]["labels"] == ["English", "French", "Swahili"]

    def test_the_page_lists_the_options(self):
        from potato.server_utils.schemas.registry import schema_registry
        config, _ = _load("select_file_page", _select("langs.txt"),
                          {"langs.txt": "English\nFrench\n"})
        html, _ = schema_registry.generate(config["annotation_schemes"][0])
        assert 'value="English"' in html and 'value="French"' in html

    def test_randomization_orders_the_files_options(self):
        from potato.server_utils.presentation_order import presentation_order
        options = [f"option {n}" for n in range(8)]
        config, _ = _load("select_file_order", _select("o.txt", randomize_order=True),
                          {"o.txt": "\n".join(options)})
        orders = {tuple(presentation_order(config["annotation_schemes"][0], f"u{n}", "1"))
                  for n in range(5)}
        assert all(sorted(order) == sorted(options) for order in orders)
        assert len(orders) > 1

    def test_inline_phase_questions_are_loaded_too(self):
        extra = {"phases": {"order": ["prestudy", "annotation"],
                            "prestudy": {"type": "prestudy",
                                         "annotation_schemes": [_select("langs.txt")]},
                            "annotation": {"type": "annotation"}}}
        config, _ = _load("select_file_inline_phase", None,
                          {"langs.txt": "English\nFrench\n"}, extra)
        assert config["phases"]["prestudy"]["annotation_schemes"][0]["labels"] == \
            ["English", "French"]

    def test_potato_validate_reads_a_phase_files_label_file(self):
        from potato.server_utils.config_module import validate_phase_question_files
        test_dir = create_test_directory("select_file_phase_validate")
        with open(os.path.join(test_dir, "langs.txt"), "w") as handle:
            handle.write("English\nEnglish\n")
        with open(os.path.join(test_dir, "pre.json"), "w") as handle:
            json.dump([_select("langs.txt")], handle)
        config = {"task_dir": test_dir,
                  "phases": {"prestudy": {"type": "prestudy", "file": "pre.json"}}}
        with pytest.raises(ConfigValidationError, match=r"pre\.json\[0\]\.labels.*more than once"):
            validate_phase_question_files(config, test_dir)

    def test_every_place_a_scheme_can_be_written_is_loaded(self):
        """scheme_sets, training, batch groups and segment_schemes were
        skipped, and validation then blamed the caller."""
        from potato.server_utils.select_label_files import (
            config_schemes, resolve_select_label_files)
        test_dir = create_test_directory("select_file_everywhere")
        with open(os.path.join(test_dir, "langs.txt"), "w") as handle:
            handle.write("English\nFrench\n")
        config = {
            "annotation_schemes": [{"annotation_type": "audio_annotation", "name": "a",
                                    "segment_schemes": [_select("langs.txt")]}],
            "phases": {"pre": {"annotation_schemes": [_select("langs.txt")]}},
            "training": {"annotation_schemes": ["a", _select("langs.txt")]},
            "scheme_sets": {"short": [_select("langs.txt")]},
            "batch_assignment": {"groups": [{"schemes": [_select("langs.txt")]},
                                            {"schemes": "short"}]},
        }
        paths = [where for where, scheme in config_schemes(config)
                 if scheme.get("annotation_type") == "select"]
        assert paths == ["annotation_schemes[0].segment_schemes[0]",
                         "phases.pre.annotation_schemes[0]",
                         "training.annotation_schemes[1]",
                         "scheme_sets['short'][0]",
                         "batch_assignment.groups[0].schemes[0]"]
        resolve_select_label_files(config_schemes(config), test_dir)
        assert all(scheme["labels"] == ["English", "French"]
                   for _w, scheme in config_schemes(config)
                   if scheme.get("annotation_type") == "select")

    def test_a_scheme_set_loads_end_to_end(self):
        config, _ = _load("select_file_scheme_set", _select(["a", "b"]),
                          {"langs.txt": "English\nFrench\n"},
                          {"scheme_sets": {"short": [_select("langs.txt", name="short_lang")]}})
        assert config["scheme_sets"]["short"][0]["labels"] == ["English", "French"]


class TestRefusals:
    def test_a_path_outside_the_project_is_refused_like_other_paths(self):
        outside = create_test_directory("select_file_outside_target")
        with open(os.path.join(outside, "langs.txt"), "w") as handle:
            handle.write("English\n")
        with pytest.raises(ConfigSecurityError,
                           match=r"annotation_schemes\[0\]\.labels: Path .* outside the project directory"):
            _load("select_file_outside", _select(os.path.join(outside, "langs.txt")))

    def test_a_missing_file_names_where_it_looked(self):
        with pytest.raises(ConfigValidationError,
                           match=r"annotation_schemes\[0\]\.labels: no label file at 'nope\.txt'"):
            _load("select_file_missing", _select("nope.txt"))

    def test_an_empty_file_is_refused(self):
        with pytest.raises(ConfigValidationError, match="has no options"):
            _load("select_file_empty", _select("langs.txt"), {"langs.txt": "\n  \n"})

    def test_an_option_listed_twice_is_refused(self):
        with pytest.raises(ConfigValidationError, match="more than once.*French"):
            _load("select_file_dupe", _select("langs.txt"),
                  {"langs.txt": "English\nFrench\nFrench \n"})

    @pytest.mark.parametrize("kind", ["radio", "multiselect"])
    def test_radio_and_multiselect_still_take_a_list_only(self, kind):
        scheme = {"annotation_type": kind, "name": "q", "description": "?",
                  "labels": "langs.txt"}
        with pytest.raises(ConfigValidationError, match="labels must be a list"):
            _load(f"select_file_{kind}", scheme, {"langs.txt": "a\nb\n"})

    def test_the_generator_does_not_read_a_path_itself(self):
        """A path that skipped config loading is not opened here, where it
        would be read from the working directory with no path check."""
        from potato.server_utils.schemas.select import generate_select_layout
        html, _ = generate_select_layout(_select(os.path.join(REPO, "requirements.txt")))
        assert "flask" not in html.lower()

    def test_a_built_in_list_beside_labels_warns_that_labels_is_ignored(self, caplog):
        with caplog.at_level("WARNING"):
            validate_single_annotation_scheme(
                _select(["unused"], use_predefined_labels="country"), "annotation_schemes[0]")
        assert any("ignores labels" in r.getMessage() for r in caplog.records)


def test_the_preview_reads_the_file():
    from potato.preview_cli import load_config
    _, path = _project("select_file_preview", _select("langs.txt"), {"langs.txt": "English\n"})
    assert load_config(path)["annotation_schemes"][0]["labels"] == ["English"]


def test_a_phase_question_file_is_loaded_at_boot():
    """The server reads survey phase files itself, after config validation."""
    from tests.unit.test_boot_paths_init_parity import _boot_factory_and_run
    test_dir, path = _project(
        "select_file_boot", _select("langs.txt"), {"langs.txt": "English\nFrench\n"},
        {"phases": {"order": ["prestudy", "annotation"],
                    "prestudy": {"type": "prestudy", "file": "pre.json"},
                    "annotation": {"type": "annotation"}}})
    with open(os.path.join(test_dir, "pre.json"), "w") as handle:
        json.dump([_select("options/where.txt", name="where")], handle)
    os.makedirs(os.path.join(test_dir, "options"), exist_ok=True)
    with open(os.path.join(test_dir, "options", "where.txt"), "w") as handle:
        handle.write("Home\nWork\n")
    out = _boot_factory_and_run(path, (
        "from potato.server_utils.config_module import config\n"
        "out['main'] = config['annotation_schemes'][0]['labels']\n"
        "out['phase'] = config['_phase_page_schemes']['prestudy'][0]['labels']\n"))
    assert out == {"main": ["English", "French"], "phase": ["Home", "Work"]}
