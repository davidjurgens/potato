"""Every place the deploy preflight tells you to use ${ENV_VAR} must expand it.

D006 flags a literal credential at any key path and says "Replace it with
${ENV_VAR}". Substitution covered only a list of blocks, so following the
advice in trace_ingestion left its webhook secret as the literal "${API_KEY}":
the real key was rejected and the placeholder accepted.
"""

import pytest

from potato.deploy import preflight
from potato.server_utils import config_module
from potato.server_utils.config_module import _substitute_llm_block_env_vars


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("POTATO_TEST_SECRET", "the-real-value")


def test_the_leaf_names_match_the_preflight():
    assert set(preflight._SECRET_KEY_NAMES) <= set(config_module._SECRET_LEAF_NAMES)


@pytest.mark.parametrize("leaf", preflight._SECRET_KEY_NAMES)
def test_every_name_d006_flags_is_expanded_in_any_block(leaf):
    config = {"some_block": {"nested": [{leaf: "Bearer ${POTATO_TEST_SECRET}"}]}}
    _substitute_llm_block_env_vars(config)
    assert config["some_block"]["nested"][0][leaf] == "Bearer the-real-value"


def test_a_secret_shaped_value_replaced_by_a_reference_is_expanded():
    """D006 also flags by value shape (sk-..., hf_...) under any key name."""
    config = {"webhooks": {"signing": "${POTATO_TEST_SECRET}"}}
    _substitute_llm_block_env_vars(config)
    assert config["webhooks"]["signing"] == "the-real-value"


def test_trace_ingestion_api_key():
    config = {"trace_ingestion": {"enabled": True, "api_key": "${POTATO_TEST_SECRET}"}}
    _substitute_llm_block_env_vars(config)
    assert config["trace_ingestion"]["api_key"] == "the-real-value"


def test_prose_with_a_reference_inside_is_left_alone():
    """Only credential leaves and whole-value references expand; a prompt that
    mentions ${...} in passing keeps its text."""
    config = {"instructions": {"prompt": "Use ${POTATO_TEST_SECRET} in the template"}}
    _substitute_llm_block_env_vars(config)
    assert config["instructions"]["prompt"] == "Use ${POTATO_TEST_SECRET} in the template"
