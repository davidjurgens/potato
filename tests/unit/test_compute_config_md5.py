"""
Tests for ``compute_config_md5`` and ``_stringify_dict_keys`` in
``potato.server_utils.front_end``.

Regression coverage for GitHub issue #153: a YAML config can produce a nested
dict with mixed key types (e.g. ``str`` and ``bool`` from YAML 1.1 booleans
like ``yes``/``no``), which crashes ``json.dumps(..., sort_keys=True)`` with
``TypeError: '<' not supported between instances of 'str' and 'bool'``.
"""

from potato.server_utils.front_end import _stringify_dict_keys, compute_config_md5


class TestStringifyDictKeys:
    def test_passes_through_scalars(self):
        assert _stringify_dict_keys("x") == "x"
        assert _stringify_dict_keys(42) == 42
        assert _stringify_dict_keys(None) is None

    def test_converts_bool_keys_to_strings(self):
        result = _stringify_dict_keys({True: "yes", False: "no"})
        assert result == {"True": "yes", "False": "no"}

    def test_recurses_into_nested_dicts(self):
        result = _stringify_dict_keys({"outer": {True: "yes", "name": "v"}})
        assert result == {"outer": {"True": "yes", "name": "v"}}

    def test_recurses_through_lists(self):
        result = _stringify_dict_keys([{True: "a"}, {1: "b", "name": "c"}])
        assert result == [{"True": "a"}, {"1": "b", "name": "c"}]

    def test_recurses_through_tuples(self):
        result = _stringify_dict_keys(({True: "a"},))
        assert result == ({"True": "a"},)


class TestComputeConfigMd5:
    def test_handles_mixed_str_and_bool_keys(self):
        # Reproduces issue #153: would raise TypeError pre-fix.
        config = {
            "task_dir": ".",
            "options": {True: "yes", "name": "value", False: "no"},
        }
        digest = compute_config_md5(config)
        assert isinstance(digest, str)
        assert len(digest) == 32

    def test_handles_mixed_str_and_int_keys(self):
        config = {"scores": {1: "one", 2: "two", "label": "score"}}
        digest = compute_config_md5(config)
        assert isinstance(digest, str)
        assert len(digest) == 32

    def test_is_deterministic_across_insertion_order(self):
        config_a = {"b": 1, "a": 2, "mixed": {True: "yes", "name": "v"}}
        config_b = {"a": 2, "mixed": {"name": "v", True: "yes"}, "b": 1}
        assert compute_config_md5(config_a) == compute_config_md5(config_b)

    def test_strips_non_serializable_meta_keys(self):
        config_with_meta = {"task_dir": ".", "__config_file__": "x", "site_file": "y"}
        config_clean = {"task_dir": "."}
        assert compute_config_md5(config_with_meta) == compute_config_md5(config_clean)

    def test_string_only_config_still_works(self):
        config = {"task_dir": ".", "site_dir": "default"}
        digest = compute_config_md5(config)
        assert isinstance(digest, str)
        assert len(digest) == 32
