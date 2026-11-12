"""ai_support accepts every text endpoint the AI support docs list.

openrouter is registered in the endpoint factory, and docs/ai-intelligence/
ai_support.md shows `endpoint_type: "open_router"`, but validation refused
both spellings with "must be one of: ...".
"""

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, validate_ai_support_config)


def _cfg(endpoint_type):
    return {"ai_support": {"enabled": True, "endpoint_type": endpoint_type,
                           "ai_config": {"model": "m", "api_key": "k"}}}


@pytest.mark.parametrize("endpoint_type", ["openrouter", "open_router"])
def test_openrouter_is_accepted(endpoint_type):
    validate_ai_support_config(_cfg(endpoint_type))


def test_an_unknown_type_is_still_refused():
    with pytest.raises(ConfigValidationError, match="must be one of"):
        validate_ai_support_config(_cfg("not_a_provider"))
