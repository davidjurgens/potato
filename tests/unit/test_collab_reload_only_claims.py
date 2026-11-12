"""The schemes whose cleared answer shows only after a reload, in three places.

collab.js leaves a teammate's clear of these schemes to the reload banner
(``REDRAWN_FROM_INPUT``: annotation.js's restore pass skips an empty value).
The docs name them in one row of the live-update table, and the browser sweep
skips their clear check (``CLEARED_ON_RELOAD_ONLY``). A scheme added to any one
of the three without the others is either an untested claim or a skipped
check nobody documented.
"""

import ast
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# How the docs row names each scheme.
DOC_NAMES = {
    "ranking": {"ranking"},
    "hierarchical multiselect": {"hierarchical_multiselect"},
    "pairwise": {"pairwise"},
    "best-worst scaling": {"bws"},
    "text edit": {"text_edit"},
    "extractive QA": {"extractive_qa"},
    "error spans": {"error_span"},
    "trajectory evaluation and editing": {"trajectory_eval", "trajectory_edit"},
}


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def _collab_js_set():
    src = _read("potato", "static", "collab.js")
    body = re.search(r"const REDRAWN_FROM_INPUT = new Set\(\[(.*?)\]\);", src, re.S).group(1)
    return set(re.findall(r"'([a-z_]+)'", body))


def _sweep_set():
    tree = ast.parse(_read("tests", "playwright", "test_collab_widget_sweep.py"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "CLEARED_ON_RELOAD_ONLY" for t in node.targets)):
            return set(ast.literal_eval(node.value))
    raise AssertionError("CLEARED_ON_RELOAD_ONLY not found in the sweep")


def _doc_row_names():
    rows = [line for line in _read("docs", "advanced", "collaborative_sessions.md").splitlines()
            if line.startswith("|") and "shows after a reload" in line]
    assert len(rows) == 1, f"expected one reload-only row, found {len(rows)}"
    first_cell = rows[0].split("|")[1].strip()
    return [name.strip() for name in first_cell.split(",")]


def test_the_docs_row_names_only_known_schemes():
    unknown = [name for name in _doc_row_names() if name.lower() not in
               {k.lower() for k in DOC_NAMES}]
    assert not unknown, f"add these to DOC_NAMES with their annotation types: {unknown}"


def test_the_docs_row_the_sweep_and_collab_js_agree():
    lower = {k.lower(): v for k, v in DOC_NAMES.items()}
    documented = set().union(*(lower[name.lower()] for name in _doc_row_names()))
    assert documented == _sweep_set() == _collab_js_set(), (
        f"docs {sorted(documented)}\nsweep {sorted(_sweep_set())}\n"
        f"collab.js {sorted(_collab_js_set())}")
