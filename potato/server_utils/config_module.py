"""
Config module.
"""
from typing import Mapping, List, Any, Union
import os
import yaml
from potato.constants import POTATO_HOME


config = {}


def init_config(args):
    global config
    with open(args.config_file, "r") as file_p:
        config.update(yaml.safe_load(file_p))

    config.update(
        {
            "verbose": args.verbose,
            "very_verbose": args.very_verbose,
            "__debug__": args.debug,
            "__config_file__": args.config_file,
        }
    )


def validate_config(_config):
    """
    Validate that config is set up correctly.
    Check for missing fields.
    """

    required_keys = {
        "server_name": str,
        "annotation_task_name": str,
        "output_annotation_dir": "path",
        "output_annotation_format": ["json", "jsonl", "csv", "tsv"],
        "data_files": List[str],
        "item_properties": Mapping[str, str],
        "user_config": Mapping[str, Any],
        "alert_time_each_instance": int,
        "annotation_schemes": List[Mapping[str, Any]],
        "html_layout": "path",
        "base_html_template": "path",
        "header_file": "path",
        "site_dir": "path",
        "db_path": "path",
        "__config_file__": str,
        "__debug__": bool,
    }

    # Fields added during run-time
    runtime_keys = [
        "__debug__",  # server_utils.config_module.init_config(),
        "__config_file__",  # server_utils.config_module.init_config(),
        "site_file",  # server_utils.front_end.generate_site()
        "ui",  # server_utils.schemas.span.set_span_color()
        "login",  # not sure about this one
        "non_annotation_pages",  # server_utils.front_end.generate_surveyflow_pages()
        "surveyflow_site_file",  # server_utils.front_end.generate_surveyflow_pages()
        # for key in surveyflow["order"]
        "%s_pages % key",  # server_utils.front_end.generate_surveyflow_pages()
    ]

    # Required paths. Other paths are paths that will be generated
    # during runtime.
    required_paths = [
        "header_file",
        "html_layout",
        "base_html_template",
        "site_dir",
        "db_path",
    ]
    optional_keys = {
        "port": int,
        "annotation_codebook_url": str,
        "jumping_to_id_disabled": str,
        "hide_navbar": bool,
        "custom_layout": Any,
        "surveyflow": Mapping[str, Any],
        "pre_annotation_pages": List[Any],
        "post_annotation_pages": List[Any],
        "prestudy_passed_pages": List[Any],
        "prestudy_failed_pages": List[Any],
        "keyword_highlights_file": "path",
        "automatic_assignment": Mapping[str, Any],
        "list_as_text": Union[str, List, Mapping[str, Any]],
        "active_learning_config": Mapping[str, Any],
        "horizontal_key_bindings": Any,
    }

    def validate_item_properties(sub_config):
        """
        Verify item_properties
        """
        assert "id_key" in sub_config
        assert "text_key" in sub_config

    def validate_annotation_scheme(sub_config):
        """
        Verify each annotation scheme.
        """
        assert "name" in sub_config
        assert "description" in sub_config

        annotation_type = sub_config.get("annotation_type")
        assert annotation_type in [
            "multiselect",
            "radio",
            "text",
            "likert",
            "btw",
            "highlight",
            "number",
            "pure_display",
            "select",
        ], "Invalid value %s for \"annotation_type\"." % annotation_type
        if annotation_type in ["likert", "bws"]:
            assert "min_label" in sub_config
            assert "max_label" in sub_config
            assert "size_label" in sub_config
        if annotation_type in ["multiselect", "radio"]:
            assert "labels" in sub_config

    def validate_path(filepath):
        """
        Verify whether paths exist.
        """
        if os.path.exists(filepath):
            return

        # Try absolute path
        config_path = os.path.realpath(_config["__config_file__"])
        dir_path = os.path.dirname(config_path)
        abs_path = os.path.join(dir_path, filepath)
        if os.path.exists(abs_path):
            return

        # Try relative to $POTATO_HOME
        abs_path = os.path.join(POTATO_HOME, filepath)
        assert os.path.exists(abs_path)

    for field in required_keys:
        if field not in _config:
            raise ValueError("Config missing field %s!" % field)

        if field == "item_properties":
            validate_item_properties(_config[field])

        if field == "annotation_schemes":
            for scheme in _config[field]:
                validate_annotation_scheme(scheme)
        if field == "output_annotation_format":
            assert _config[field] in required_keys[field], (
                'Invalid value %s for "output_annotation_format"'
                % _config[field]
            )
        if field == "data_files":
            for _filepath in _config[field]:
                validate_path(_filepath)

        if field in required_paths:
            validate_path(config[field])
