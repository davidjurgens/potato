"""Every quality-control key the loader reads must survive the validator.

`gold_standards.feedback` decides whether an annotator ever sees their gold
result, and `quality_control.py` has always read it — but the known-key schema
did not list it, so the only documented route out of silent scoring failed
`potato validate --strict`, the check authors are told to run. The drawn-answer
tolerance had the same split.
"""

import pytest

from potato.server_utils.config_key_docs import CONFIG_KEY_DOCS
from potato.server_utils.config_module import KNOWN_CONFIG_KEYS


# Every sub-key `QualityControlManager._parse_config` reads, per block.
QC_SUBKEYS = {
    "attention_checks": [
        "enabled", "items_file", "frequency", "probability",
        "min_response_time", "failure_handling", "geometry_iou_tolerance",
    ],
    "gold_standards": [
        "enabled", "items_file", "mode", "frequency", "accuracy",
        "feedback", "auto_promote", "geometry_iou_tolerance",
    ],
}


@pytest.mark.parametrize(
    "block,subkey",
    [(block, subkey) for block, subkeys in QC_SUBKEYS.items() for subkey in subkeys],
)
def test_subkey_is_a_known_config_key(block, subkey):
    assert subkey in KNOWN_CONFIG_KEYS[block], (
        f"{block}.{subkey} is read by quality_control.py but "
        f"`validate --strict` rejects it"
    )


@pytest.mark.parametrize(
    "block,subkey",
    [(block, subkey) for block, subkeys in QC_SUBKEYS.items() for subkey in subkeys],
)
def test_subkey_is_documented(block, subkey):
    assert f"{block}.{subkey}" in CONFIG_KEY_DOCS, (
        f"{block}.{subkey} is missing from CONFIG_KEY_DOCS, so it does not "
        f"reach the JSON Schema or the config reference"
    )
