"""Config messages and accepted keys that promised something the code did not do.

Each test names the old behaviour it guards against.
"""

import logging
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from potato.server_utils import config_module
from potato.server_utils.config_module import (
    deprecated_key_warnings,
    warn_batch_groups_need_the_batch_strategy,
    validate_category_assignment_config,
)

REPO = Path(__file__).resolve().parents[2]


def test_every_docs_path_a_message_cites_exists():
    """One message pointed at docs/instance_display.md; the page lives at
    docs/annotation-types/instance_display.md."""
    source = Path(config_module.__file__).read_text()
    cited = set(re.findall(r"docs/[A-Za-z0-9_./-]+\.md", source))
    assert cited, "no docs paths found -- the pattern is wrong"
    missing = sorted(p for p in cited if not (REPO / p).is_file())
    assert not missing, missing


def test_the_batch_warning_accepts_the_mapping_form(caplog):
    """`assignment_strategy: {name: batch}` is a valid spelling; the warning
    asking for batch fired on it, so validate --strict failed a correct config."""
    config = {"assignment_strategy": {"name": "batch"},
              "batch_assignment": {"groups": [{"name": "g", "instances": ["a"]}]}}
    with caplog.at_level(logging.WARNING):
        warn_batch_groups_need_the_batch_strategy(config)
    assert "batch_assignment group" not in caplog.text


def test_the_batch_warning_still_fires_without_batch(caplog):
    config = {"batch_assignment": {"groups": [{"name": "g", "instances": ["a"]}]}}
    with caplog.at_level(logging.WARNING):
        warn_batch_groups_need_the_batch_strategy(config)
    assert "batch_assignment group" in caplog.text


def test_the_rename_advice_names_a_value_an_exporter_handles():
    """'Rename the key' left export_annotation_format: json, which no exporter
    handles; the message must give the folded value."""
    [message] = deprecated_key_warnings({"output_annotation_format": "json"})
    assert "Replace it with 'export_annotation_format: jsonl'" in message
    assert "Rename the key." not in message


@pytest.mark.parametrize("key", ["source", "combine_method"])
def test_inert_qualification_keys_warn(caplog, key):
    """Qualifications come from training only; source and combine_method were
    accepted and read by nothing."""
    value = {"source": "prestudy", "combine_method": "max"}[key]
    with caplog.at_level(logging.WARNING):
        validate_category_assignment_config(
            {"category_assignment": {"enabled": True, "qualification": {key: value}}})
    assert f"qualification.{key}" in caplog.text and "not used" in caplog.text


@patch("potato.ai.openai_endpoint.OpenAI")
def test_openai_endpoint_reads_api_base(mock_openai):
    """Validation accepted ai_config.api_base in place of base_url, but the
    endpoint read only base_url and then failed for a missing key."""
    from potato.ai.openai_endpoint import OpenAIEndpoint

    with patch.dict("os.environ", {}, clear=False) as env:
        env.pop("OPENAI_API_KEY", None)
        OpenAIEndpoint({"ai_config": {"api_base": "http://localhost:8001/v1"}})
    assert mock_openai.call_args.kwargs["base_url"] == "http://localhost:8001/v1"
