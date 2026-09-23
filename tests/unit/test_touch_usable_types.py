"""TOUCH_USABLE_TYPES decides who sees "use a desktop browser" on a phone.

A misspelled type would silently show the warning on a task that works, and a
type missing from the Pocket list would mean Pocket hosts something the
warning calls unusable.
"""

from potato.pocket.config import (
    POCKET_CAPABLE_TYPES,
    TOUCH_USABLE_TYPES,
    touch_usability,
)
from potato.server_utils.schemas.registry import schema_registry


def test_every_touch_usable_type_is_registered():
    registered = set(schema_registry.get_supported_types())
    assert TOUCH_USABLE_TYPES <= registered, TOUCH_USABLE_TYPES - registered


def test_everything_pocket_hosts_is_touch_usable():
    assert POCKET_CAPABLE_TYPES <= TOUCH_USABLE_TYPES


def test_a_task_is_usable_only_if_every_scheme_is():
    ok = {"annotation_schemes": [{"name": "a", "annotation_type": "pairwise"},
                                 {"name": "b", "annotation_type": "span"}]}
    assert touch_usability(ok) == (True, [])
    mixed = {"annotation_schemes": [{"name": "a", "annotation_type": "radio"},
                                    {"name": "links", "annotation_type": "span_link"}]}
    assert touch_usability(mixed) == (False, ["links"])


def test_no_schemes_is_usable():
    assert touch_usability({}) == (True, [])
