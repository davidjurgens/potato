"""
Guards for ``potato/server_utils/config_key_docs.py``.

That table documents config keys by dotted path, in parallel with
``KNOWN_CONFIG_KEYS``. Two things can go wrong with a parallel table: it can
describe keys that do not exist, and it can fall behind keys that do. These
tests cover both, plus the one place the table could contradict the server --
the int/bool coercion tables in ``config_module``, which are what load-time
validation actually enforces.

Coverage is a ratchet. ``data/undocumented_config_keys.txt`` grandfathers in
everything that was undocumented when the table landed; a key added after that
must come with an entry.
"""

import os

import pytest

from potato.server_utils.config_key_docs import (
    CONFIG_KEY_DOCS,
    UNSET,
    ConfigKeyDoc,
    documented_paths,
    get_key_doc,
)
from potato.server_utils.config_module import (
    KNOWN_CONFIG_KEYS,
    _OPTIONAL_BOOL_FIELDS,
    _OPTIONAL_INT_FIELDS,
)

ALLOWLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "undocumented_config_keys.txt"
)

# Keys the server writes onto the config dict itself. They are not authored by
# anyone, so they are not documentation gaps.
def _is_internal(path: str) -> bool:
    return any(part.startswith("_") for part in path.split("."))


def _walk(mapping, prefix=""):
    """Every dotted path in KNOWN_CONFIG_KEYS, including nested sub-keys."""
    for key, value in mapping.items():
        path = f"{prefix}{key}"
        yield path
        if isinstance(value, dict):
            yield from _walk(value, path + ".")
        elif isinstance(value, set):
            for sub in sorted(value):
                yield f"{path}.{sub}"


def _known_paths() -> set:
    return {p for p in _walk(KNOWN_CONFIG_KEYS) if not _is_internal(p)}


def _allowlist() -> set:
    with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
        return {
            line.strip()
            for line in f
            if line.strip() and not line.lstrip().startswith("#")
        }


class TestTableIntegrity:
    def test_no_orphan_documentation(self):
        """Every documented path must name a key the server recognizes.

        Catches typos and keys renamed out from under the table.
        """
        orphans = sorted(documented_paths() - _known_paths())
        assert not orphans, (
            "These paths are documented but absent from KNOWN_CONFIG_KEYS, so "
            "nothing reads them: " + ", ".join(orphans)
        )

    def test_entries_are_the_right_shape(self):
        for path, doc in CONFIG_KEY_DOCS.items():
            assert isinstance(doc, ConfigKeyDoc), path
            assert doc.summary.strip(), f"{path} has an empty summary"
            assert not doc.summary.endswith("."), (
                f"{path}: summaries read as labels, not sentences -- drop the "
                f"trailing period"
            )
            valid = {"string", "integer", "number", "boolean", "object", "array", "any"}
            parts = doc.type.split("|")
            assert all(p in valid for p in parts), (
                f"{path} has an unrecognized type {doc.type!r}"
            )
            assert "any" not in parts or len(parts) == 1, (
                f"{path}: 'any' cannot be one arm of a union"
            )

    def test_see_also_targets_exist(self):
        known = _known_paths()
        for path, doc in CONFIG_KEY_DOCS.items():
            for target in doc.see_also:
                assert target in known, (
                    f"{path} points at {target!r}, which is not a config key"
                )

    def test_get_key_doc_round_trips(self):
        assert get_key_doc("task_dir") is CONFIG_KEY_DOCS["task_dir"]
        assert get_key_doc("no_such_key_anywhere") is None


class TestAgreesWithTheServer:
    """The table must not claim a type the server contradicts at load time."""

    def test_int_fields_are_typed_integer(self):
        for key in _OPTIONAL_INT_FIELDS:
            doc = get_key_doc(key)
            if doc is None:
                continue
            assert "integer" in doc.type.split("|"), (
                f"{key} is coerced by _OPTIONAL_INT_FIELDS but documented as "
                f"{doc.type!r}"
            )

    def test_bool_fields_are_typed_boolean(self):
        for key in _OPTIONAL_BOOL_FIELDS:
            doc = get_key_doc(key)
            if doc is None:
                continue
            assert "boolean" in doc.type.split("|"), (
                f"{key} is coerced by _OPTIONAL_BOOL_FIELDS but documented as "
                f"{doc.type!r}"
            )

    def test_required_flags_match_the_validator(self):
        """Anything marked required must be one the validator actually demands."""
        from potato.server_utils.config_schema import REQUIRED_TOP_LEVEL

        for path, doc in CONFIG_KEY_DOCS.items():
            if not doc.required or "." in path:
                continue
            assert path in REQUIRED_TOP_LEVEL, (
                f"{path} is marked required but validate_yaml_structure() does "
                f"not insist on it"
            )


class TestCoverageRatchet:
    def test_allowlist_only_names_real_keys(self):
        stale = sorted(_allowlist() - _known_paths())
        assert not stale, (
            "These allowlist entries are no longer config keys; delete them: "
            + ", ".join(stale[:20])
        )

    def test_allowlist_has_no_documented_keys(self):
        """A key cannot be both documented and grandfathered."""
        both = sorted(_allowlist() & documented_paths())
        assert not both, (
            "These keys are documented, so their allowlist entries are dead "
            "weight -- remove them from "
            "tests/unit/data/undocumented_config_keys.txt: " + ", ".join(both[:20])
        )

    def test_no_new_key_is_undocumented(self):
        missing = sorted(_known_paths() - documented_paths() - _allowlist())
        assert not missing, (
            "These config keys have no entry in CONFIG_KEY_DOCS:\n  "
            + "\n  ".join(missing)
            + "\n\nAdd one to potato/server_utils/config_key_docs.py. It flows "
            "into the published JSON Schema, the generated config reference, "
            "and the MCP describe_config_key tool. Do not add the key to "
            "tests/unit/data/undocumented_config_keys.txt -- that list only "
            "shrinks."
        )

    def test_the_ratchet_is_actually_engaged(self):
        """Fail if the allowlist has grown to swallow everything.

        Without this, a well-meaning regeneration of the allowlist would make
        test_no_new_key_is_undocumented vacuous and nobody would notice.
        """
        known = _known_paths()
        documented = documented_paths()
        assert len(documented) >= 100, (
            f"only {len(documented)} paths documented; the table has been gutted"
        )
        top_level = {p for p in known if "." not in p}
        top_documented = top_level & documented
        assert len(top_documented) / len(top_level) > 0.4, (
            f"top-level coverage fell to "
            f"{len(top_documented)}/{len(top_level)}"
        )
