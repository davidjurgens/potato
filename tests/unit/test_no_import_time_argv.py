"""No module under potato/ may parse sys.argv when it is imported.

potato/remove_users_from_queue.py ran its argument parser, and then rewrote
annotation files, at module level. Anything that imports every module (autodoc,
coverage, an agent sweeping the package) ran it with its own argv. A module's
command-line entry point belongs in a function or under `if __name__ ==
"__main__":`.
"""

import ast
from pathlib import Path

POTATO = Path(__file__).resolve().parents[2] / "potato"


def _is_main_guard(node):
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


def _module_level_parse_args(tree):
    hits = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                or _is_main_guard(stmt):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("parse_args", "parse_known_args"):
                hits.append(node.lineno)
    return hits


def test_no_module_parses_argv_at_import():
    offenders = []
    for path in sorted(POTATO.rglob("*.py")):
        lines = _module_level_parse_args(ast.parse(path.read_text(), str(path)))
        offenders += [f"{path.relative_to(POTATO.parent)}:{n}" for n in lines]
    assert not offenders, f"argv parsed at import time: {offenders}"


def test_the_check_sees_a_module_level_call():
    """Guard the guard: the walker must flag the shape it exists to catch."""
    tree = ast.parse("import argparse\nargs = argparse.ArgumentParser().parse_args()\n")
    assert _module_level_parse_args(tree) == [2]
