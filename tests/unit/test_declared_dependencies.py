"""Libraries the code relies on are declared, or fail with a clear message.

defusedxml: the FLExText, PAGE, TEI and LimeSurvey importers refuse entity
expansion through it. It was imported under a guard but declared nowhere, so
a plain `pip install potato-annotation` fell back to the stdlib parser.

msgpack: optional. BinaryCIF needs it, and its absence must say what to
install rather than raise a bare ImportError.
"""

import ast
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_list(name):
    tree = ast.parse(open(os.path.join(REPO, "setup.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return [ast.literal_eval(e) for e in node.value.elts]
    raise AssertionError(f"{name} not found in setup.py")


def _dist(spec):
    return re.split(r"[<>=!~\[; ]", spec.strip(), 1)[0].lower()


def _requirements():
    out = []
    for line in open(os.path.join(REPO, "requirements.txt"), encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.append(_dist(line))
    return out


def test_defusedxml_is_a_core_dependency():
    core = [_dist(s) for s in _setup_list("_CORE_DEPS")]
    assert "defusedxml" in core
    assert "defusedxml" in _requirements()


def test_defusedxml_pin_matches_between_setup_and_requirements():
    core = {_dist(s): s for s in _setup_list("_CORE_DEPS")}
    reqs = [ln.strip() for ln in open(os.path.join(REPO, "requirements.txt"), encoding="utf-8")
            if _dist(ln.split("#", 1)[0] or " ") == "defusedxml"]
    assert reqs == [core["defusedxml"]]


def test_binarycif_without_msgpack_says_what_to_install(monkeypatch):
    from potato.media.structures import StructureError, parse_bcif
    monkeypatch.setitem(sys.modules, "msgpack", None)   # import raises ImportError
    with pytest.raises(StructureError, match=r"pip install msgpack"):
        parse_bcif(b"\x80")
