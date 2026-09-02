"""
No package directory under ``potato/`` may share a name with a distribution we
depend on.

Potato is routinely run as ``python potato/flask_server.py start config.yaml``
-- the invocation used throughout ``examples/README.md`` and the screenshot
tooling. That puts ``<repo>/potato/`` at the front of ``sys.path``, so a
subpackage named ``foo`` becomes importable as top-level ``foo`` and shadows the
real ``foo`` for the rest of the process.

This already bit the project once: an eval-datasets package named ``datasets``
shadowed HuggingFace ``datasets``, and had to be renamed to ``eval_datasets``.
The same trap is waiting for ``mcp`` (the Model Context Protocol SDK), which is
why the MCP server lives in ``potato/mcp_server/``.
"""

import ast
import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POTATO_PKG = os.path.join(REPO_ROOT, "potato")
SETUP_PY = os.path.join(REPO_ROOT, "setup.py")
REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")

# A distribution's PyPI name is not always its import name. Only the import name
# can shadow, so map the ones that differ.
_DIST_TO_IMPORT = {
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
    "python-dateutil": "dateutil",
    "python-docx": "docx",
    "scikit-learn": "sklearn",
    "pillow": "PIL",
    "google-genai": "google",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "python-multipart": "multipart",
    "msgpack-python": "msgpack",
    "pytest-cov": "pytest_cov",
    "sentence-transformers": "sentence_transformers",
    "umap-learn": "umap",
    "huggingface-hub": "huggingface_hub",
}

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def _import_name(dist: str) -> str:
    dist = dist.strip().lower()
    return _DIST_TO_IMPORT.get(dist, dist.replace("-", "_"))


def _declared_dependencies() -> set:
    """Every distribution named in requirements.txt or setup.py's dep lists."""
    names = set()

    if os.path.isfile(REQUIREMENTS):
        with open(REQUIREMENTS, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                m = _REQ_LINE.match(line)
                if m:
                    names.add(_import_name(m.group(1)))

    # Read the `_*_DEPS` list literals out of setup.py by parsing it. A regex
    # over the whole file also swept up the extras_require *keys* ("ai",
    # "deploy", "export", "publish"), which are feature-group labels rather than
    # distributions and collide with real subpackage names.
    with open(SETUP_PY, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not any(t.startswith("_") and t.endswith("_DEPS") for t in targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                m = _REQ_LINE.match(element.value)
                if m:
                    names.add(_import_name(m.group(1)))

    return names


def _potato_subpackages() -> set:
    return {
        entry
        for entry in os.listdir(POTATO_PKG)
        if os.path.isdir(os.path.join(POTATO_PKG, entry))
        and not entry.startswith((".", "_"))
    }


class TestNoShadowedDependencies:
    def test_inputs_are_non_trivial(self):
        """Fail loudly if either side of the comparison stops being collected."""
        assert len(_declared_dependencies()) > 20
        assert len(_potato_subpackages()) > 10

    def test_no_subpackage_shadows_a_dependency(self):
        clashes = sorted(_potato_subpackages() & _declared_dependencies())
        assert not clashes, (
            "These directories under potato/ share a name with a distribution "
            "Potato depends on. Running `python potato/flask_server.py` puts "
            "potato/ on sys.path, so they would shadow the real package: "
            + ", ".join(clashes)
            + ". Rename them (see potato/eval_datasets/ and potato/mcp_server/)."
        )

    @pytest.mark.parametrize("forbidden", ["datasets", "mcp"])
    def test_known_traps_stay_renamed(self, forbidden):
        """Pin the two collisions that have already been reasoned about.

        These hold even if the dependency is later dropped from the manifests --
        both names are ones a future contributor would reach for by instinct.
        """
        assert forbidden not in _potato_subpackages(), (
            f"potato/{forbidden}/ shadows the '{forbidden}' distribution. "
            f"Use potato/eval_{forbidden}/ or potato/{forbidden}_server/ instead."
        )
