"""A CLI flag that was not passed does not overwrite the config file.

`config_module` builds `config_updates` under a comment reading "Only override
config settings if command line arguments are explicitly provided". Five keys
did not honour it -- they were written in unconditionally, so argparse's own
default landed on top of the YAML.

`persist_sessions` is the one that bites. A config file saying
`persist_sessions: true` got no error, no warning and not the behaviour, and
`configure_session`'s refusal to run persistent sessions without a `secret_key`
could not fire on the path everyone uses, because the value never reached it.
The audit measured it on one file, varying only the command line: `potato start
k.yaml` booted, `potato start k.yaml --persist-sessions` raised. Same file.

`run_server` then did it a second time, on its own, after config_module was
finished -- so fixing only the first site would have left the live `potato
start` path broken.

The other four are the same shape and were found alongside: `customjs_hostname`
was reset to None, and `customjs`, `verbose` and `very_verbose` to False, for
anyone who set them in YAML.

None of the four flags has a `--no-` counterpart, so absence can never mean
"off". That is what makes guarding on truthiness the whole fix rather than a
guess about intent.
"""

import argparse

import pytest


CLI_KEYS = ["persist_sessions", "customjs", "verbose", "very_verbose"]


def parsed_args(argv):
    """The real parser, so the defaults under test are the shipped ones.

    `arguments()` reads sys.argv itself, so the only way to drive it with a
    given command line is to be that command line.
    """
    import sys

    from potato.server_utils.arg_utils import arguments

    saved = sys.argv
    sys.argv = ["potato"] + list(argv)
    try:
        return arguments()
    finally:
        sys.argv = saved


class TestTheShippedDefaults:
    """If any of these stops being falsy-by-default, the guard below changes
    meaning and this file should be read again."""

    @pytest.mark.parametrize("flag", CLI_KEYS)
    def test_the_flag_defaults_to_off(self, flag):
        args = parsed_args(["start", "cfg.yaml"])
        assert getattr(args, flag) is False, (
            f"--{flag} no longer defaults to False; the override guard reads "
            "absence as 'no instruction', which only holds for a store_true")

    def test_the_hostname_defaults_to_none(self):
        assert parsed_args(["start", "cfg.yaml"]).customjs_hostname is None

    @pytest.mark.parametrize("flag", CLI_KEYS)
    def test_there_is_no_off_switch(self, flag):
        """Absence can only mean "no instruction" while there is no way to say
        "off" on the command line. If one is ever added, the guard has to grow
        a tri-state."""
        parser_flags = _all_option_strings()
        dashed = "--" + flag.replace("_", "-")
        for candidate in ("--no-" + flag.replace("_", "-"),
                          dashed.replace("--", "--no", 1)):
            assert candidate not in parser_flags, (
                f"{candidate} exists, so absence of {dashed} is no longer "
                "unambiguous")


def _all_option_strings():
    """Every long option the parser knows, subcommands included."""
    import argparse
    import sys

    from potato.server_utils import arg_utils

    found = set()
    real_parse = argparse.ArgumentParser.parse_args

    def capture(self, *a, **kw):
        stack = [self]
        while stack:
            parser = stack.pop()
            for action in parser._actions:
                found.update(action.option_strings)
                # `mode` is a positional whose choices are plain strings, so
                # only descend into choices that are parsers.
                choices = getattr(action, "choices", None) or {}
                values = choices.values() if hasattr(choices, "values") else choices
                stack.extend(c for c in values
                             if isinstance(c, argparse.ArgumentParser))
        return real_parse(self, *a, **kw)

    saved = sys.argv
    sys.argv = ["potato", "start", "cfg.yaml"]
    argparse.ArgumentParser.parse_args = capture
    try:
        arg_utils.arguments()
    finally:
        argparse.ArgumentParser.parse_args = real_parse
        sys.argv = saved
    assert found, "captured no options; the parser shape changed"
    return found


# ----------------------------------------------------------------------
# run_server's own override -- the live `potato start` path
# ----------------------------------------------------------------------

class TestPersistSessionsSurvivesToTheGuard:
    """`configure_session` is where `persist_sessions` is finally read. The
    audit confirmed it raises correctly when called on the parsed YAML; the
    defect was that the YAML value never got there."""

    def _configure(self, config):
        from flask import Flask
        from potato.server_utils.session_config import configure_session

        return configure_session(Flask(__name__), config)

    def test_persist_without_a_secret_key_is_still_refused(self):
        """The guard itself, unchanged. Pinned because everything below is
        about making sure the value reaches it."""
        with pytest.raises(ValueError, match="secret_key"):
            self._configure({"persist_sessions": True})

    def test_a_config_file_value_reaches_the_guard(self):
        """This is the defect, stated as behaviour: a config that says
        `persist_sessions: true` and has no `secret_key` must be refused, and
        was not, because the CLI default overwrote it first."""
        config = _apply_cli_overrides({"persist_sessions": True},
                                      argv=["start", "cfg.yaml"])
        assert config.get("persist_sessions") is True, (
            "the config file value was overwritten by the CLI default before "
            "anything could act on it")
        with pytest.raises(ValueError, match="secret_key"):
            self._configure(config)

    def test_the_flag_still_turns_it_on(self):
        config = _apply_cli_overrides(
            {}, argv=["start", "cfg.yaml", "--persist-sessions"])
        assert config.get("persist_sessions") is True


def _apply_cli_overrides(config_data, argv):
    """Run the config-file value and the parsed CLI args through the same
    merge the server does, and return the resulting config."""
    import os
    import json

    import yaml

    from potato.server_utils import config_module
    from tests.helpers.test_utils import create_test_directory

    task_dir = create_test_directory("audit37_cli")
    data_path = os.path.join(task_dir, "items.json")
    with open(data_path, "w", encoding="utf-8") as fh:
        json.dump([{"id": "s1", "text": "well that went great"}], fh)

    full = {
        "port": 8000, "annotation_task_name": "audit37",
        "task_dir": task_dir, "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": os.path.join(task_dir, "out"),
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm",
             "description": "Sarcasm?", "labels": ["Sarcastic", "Sincere"]}],
    }
    full.update(config_data)
    cfg_path = os.path.join(task_dir, "cfg.yaml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(full, fh)

    args = parsed_args([argv[0], cfg_path] + list(argv[2:]))
    cwd = os.getcwd()
    # `init_config` merges into a module-global dict that is never cleared, so
    # in a full-suite run this config would inherit whatever an earlier test
    # left behind -- including a `secret_key`, which is exactly the value the
    # persist_sessions guard turns on. Start from empty and put back what was
    # there, so this test measures the merge and not the run order.
    snapshot = dict(config_module.config)
    config_module.config.clear()
    try:
        config_module.init_config(args)
        return dict(config_module.config)
    finally:
        os.chdir(cwd)
        config_module.config.clear()
        config_module.config.update(snapshot)


class TestTheOtherFourAreNotClobbered:

    @pytest.mark.parametrize("key,value", [
        ("customjs", True),
        ("verbose", True),
        ("very_verbose", True),
    ])
    def test_a_yaml_true_survives_an_absent_flag(self, key, value):
        config = _apply_cli_overrides({key: value},
                                      argv=["start", "cfg.yaml"])
        assert config.get(key) is True, (
            f"`{key}: true` in the config file was reset by the CLI default")

    def test_a_yaml_hostname_survives_an_absent_flag(self):
        config = _apply_cli_overrides(
            {"customjs": True, "customjs_hostname": "js.example.org"},
            argv=["start", "cfg.yaml"])
        assert config.get("customjs_hostname") == "js.example.org", (
            "`customjs_hostname` was reset to None by the CLI default, so the "
            "page fell back to localhost:4173")
