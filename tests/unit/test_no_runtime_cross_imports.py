"""
Structural test: ban function-level cross-imports between `potato.flask_server`
and `potato.routes`.

Background: PR #147 ("Fix annotation-page back-navigation crash") fixed a
production crash caused by `render_page_with_annotations()` doing a lazy
`from potato.routes import _instance_meets_required_annotation_rules` at
request time. In environments with a stale installed package copy, this
re-triggered Flask's route registration after the first request and raised
"route can no longer be called" assertion.

Lazy imports between these two modules are almost always workarounds for
circular imports. They hide at review time, they hide in unit tests that
mock everything, and they can crash production in specific conditions.

This test parses both files with `ast` and fails if any function body
contains an `ImportFrom` whose module is the other file. Module-level
imports (the usual circular-import workaround location) are fine.

To suppress for a legitimate case, add `# noqa: cross-import` on the
import line — the test will skip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


POTATO_DIR = Path(__file__).resolve().parent.parent.parent / "potato"
BANNED_PAIRS = {
    "potato.flask_server": {"potato.routes"},
    "potato.routes": {"potato.flask_server"},
}


def _collect_function_level_imports(tree: ast.AST):
    """Yield (func_name, lineno, module) for every ImportFrom inside a FunctionDef."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and sub.module is not None:
                yield node.name, sub.lineno, sub.module


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "source_module,module_file",
    [
        ("potato.flask_server", POTATO_DIR / "flask_server.py"),
        ("potato.routes", POTATO_DIR / "routes.py"),
    ],
)
def test_no_function_level_sibling_imports(source_module, module_file):
    """No function body in flask_server.py or routes.py may import from the other.

    Module-level imports (at the top of the file) are allowed — they are the
    standard location for this kind of dependency and are subject to Python's
    normal import cycle detection.
    """
    assert module_file.exists(), f"Expected file not found: {module_file}"

    source_lines = _read_lines(module_file)
    tree = ast.parse(module_file.read_text(encoding="utf-8"), filename=str(module_file))
    banned_targets = BANNED_PAIRS[source_module]

    violations: list[str] = []
    for func_name, lineno, module in _collect_function_level_imports(tree):
        if module not in banned_targets:
            continue
        # Allow a targeted escape hatch via a trailing comment
        line_text = source_lines[lineno - 1] if lineno - 1 < len(source_lines) else ""
        if "noqa: cross-import" in line_text:
            continue
        violations.append(
            f"{module_file.name}:{lineno} in function `{func_name}`: "
            f"`from {module} import ...` — hoist this to the module top."
        )

    assert not violations, (
        "Function-level cross-imports detected between flask_server.py and "
        "routes.py. These are almost always circular-import workarounds and "
        "caused the PR #147 production crash. Move them to module scope or "
        "add `# noqa: cross-import` if truly intentional.\n\n"
        + "\n".join(violations)
    )


def test_both_modules_are_parseable():
    """Sanity: both files must parse with ast.parse (no SyntaxError)."""
    for path in [POTATO_DIR / "flask_server.py", POTATO_DIR / "routes.py"]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
