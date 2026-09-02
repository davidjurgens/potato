"""
Guards for the two-stage CLI dispatch in ``potato.flask_server.main()``.

Stage 1 matches ``sys.argv[1]`` directly and hands off to a sub-CLI with its own
flag grammar. Stage 2 is ``arg_utils.arguments()``, whose ``mode`` positional has
a fixed ``choices`` list followed by a required ``config_file``.

Because stage 1 runs first, a token listed in *both* places is reachable only
through stage 1 -- the stage-2 entry is dead. ``transcripts`` and ``convokit``
sat in the ``choices`` list that way for several releases, advertising modes the
parser could never be asked to handle.
"""

import ast
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLASK_SERVER = os.path.join(REPO_ROOT, "potato", "flask_server.py")


def _stage1_tokens():
    """Recover the stage-1 tokens by parsing ``main()``'s sys.argv comparisons.

    Looks for ``sys.argv[1] == '<token>'`` inside the ``main`` function. Parsing
    beats importing: ``potato.flask_server`` is expensive to import and this test
    only needs the literals.
    """
    with open(FLASK_SERVER, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    main_fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_fn is not None, "flask_server.main() not found"

    tokens = set()
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.Compare):
            continue
        if not (len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)):
            continue
        left, right = node.left, node.comparators[0]
        if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
            continue
        # sys.argv[1] == "<token>"
        if (
            isinstance(left, ast.Subscript)
            and isinstance(left.value, ast.Attribute)
            and left.value.attr == "argv"
        ):
            tokens.add(right.value)
    return tokens


def _stage2_choices():
    """Recover the server parser's ``mode`` choices.

    ``arguments()`` builds the parser and parses in one call and never returns
    the parser, so intercept ``parse_args`` to capture it.
    """
    import argparse

    from potato.server_utils import arg_utils

    captured = {}
    real_parse = argparse.ArgumentParser.parse_args

    def spy(self, *a, **kw):
        captured["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = spy
    try:
        arg_utils.arguments()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = real_parse

    parser = captured.get("parser")
    assert parser is not None, "could not capture the server argument parser"

    for action in parser._actions:
        if action.dest == "mode":
            return set(action.choices or ())
    raise AssertionError("no 'mode' positional found in the server parser")


class TestDispatchStagesAreDisjoint:
    def test_stage1_tokens_are_found(self):
        tokens = _stage1_tokens()
        # Sanity: if the parse stops working this test must fail loudly rather
        # than pass on an empty set.
        assert "deploy" in tokens
        assert "validate" in tokens
        assert "preview" in tokens

    def test_no_token_is_registered_in_both_stages(self):
        overlap = _stage1_tokens() & _stage2_choices()
        assert not overlap, (
            "These tokens are intercepted by the stage-1 sys.argv check in "
            "flask_server.main(), so their entries in the server parser's "
            "'mode' choices are unreachable: " + ", ".join(sorted(overlap))
        )

    def test_start_is_still_a_stage2_mode(self):
        assert "start" in _stage2_choices()


class TestAgentFacingCommandsAreDispatched:
    @pytest.mark.parametrize("token", ["validate", "preview"])
    def test_command_is_reachable(self, token):
        assert token in _stage1_tokens()


class TestHelpListsEveryCommand:
    """`--help` must name the stage-1 commands, or they do not exist.

    They cannot be `mode` choices, so argparse will never list them on its own.
    An agent that read `--help` and saw only
    `{start,migrate,reset-password,codebook,repair-annotations}` concluded that
    `validate` and `preview` -- the loop every Potato agent document is built
    around -- were unavailable in its build.
    """

    def test_every_dispatched_token_is_in_the_help_list(self):
        from potato.server_utils.arg_utils import STAGE1_COMMANDS

        missing = sorted(set(_stage1_tokens()) - set(STAGE1_COMMANDS))
        assert not missing, (
            f"these commands are dispatched but absent from `potato --help`: "
            f"{missing}. Add them to STAGE1_COMMANDS in arg_utils.py."
        )

    def test_the_help_list_has_no_commands_that_do_not_exist(self):
        from potato.server_utils.arg_utils import STAGE1_COMMANDS

        phantom = sorted(set(STAGE1_COMMANDS) - set(_stage1_tokens()))
        assert not phantom, (
            f"`potato --help` advertises commands nothing dispatches: {phantom}"
        )

    def test_the_help_epilog_names_them(self):
        """Read the epilog, not `arguments()` -- that one parses sys.argv."""
        from potato.server_utils.arg_utils import STAGE1_HELP

        for name in ("validate", "preview", "mcp", "import"):
            assert name in STAGE1_HELP, f"`{name}` is missing from --help"
        assert "--help" in STAGE1_HELP, (
            "the epilog should tell the reader how to get each command's own "
            "options, since argparse cannot show them"
        )
