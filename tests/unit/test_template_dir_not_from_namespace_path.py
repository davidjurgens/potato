"""Templates come from the checkout, never from `potato.__path__`.

A directory called `potato` with no `__init__.py` earlier on the path -- the
usual residue of an older non-editable install -- makes the top-level name
resolve to a namespace package. `potato.__path__` then points at that stale
directory while every submodule still imports from the real checkout through
the editable finder. On the machine this was written on, that leftover contains
a `templates/` directory dated two months before the code that would read it.

Nothing reads it today, and two separate mechanisms are why:

* Flask derives `app.root_path`, and so its Jinja search path, from the calling
  module's `__file__` (`Flask(__name__)`).
* `front_end.py` builds its own template paths from
  `os.path.dirname(os.path.abspath(__file__))`.

Both land in the checkout. Neither is a decision anyone recorded, though, and
the natural-looking way to find a package's data directory --
`potato.__path__[0]`, or `importlib.resources.files("potato")` -- would read the
stale copy instead. Switching to either would serve two-month-old templates on
a machine where every test still passes, which is the same silent
edit-has-no-effect symptom that made the editable install necessary in the
first place.

Run in a subprocess from OUTSIDE the checkout, because that is the only place
the shadow exists: with the repo root as cwd, the real package wins and there
is nothing to detect.
"""

import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Resolves every template directory the server can reach, and reports the
#: paths rather than a verdict, so a failure says which one went wrong.
_PROBE = r"""
import json, os
import potato
import potato.server_utils.front_end as front_end
from potato.flask_server import app

# Asked, not recomputed. A probe that rebuilds the path from
# front_end.__file__ measures its own arithmetic: the first version of this
# file did exactly that, and a mutation switching front_end to
# potato.__path__[0] passed it.
front_end_templates = os.path.abspath(front_end.bundled_template_dir())

print(json.dumps({
    "namespace_path": [os.path.abspath(p) for p in getattr(potato, "__path__", [])],
    "package_file": getattr(potato, "__file__", None),
    "flask_root": os.path.abspath(app.root_path),
    "jinja_searchpath": [os.path.abspath(p)
                         for p in app.jinja_loader.searchpath],
    "front_end_templates": front_end_templates,
    "front_end_file": os.path.abspath(front_end.__file__),
    # Resolving a real template rather than trusting the search path: a loader
    # can list a directory it never actually reads from.
    "resolved_base_template": front_end_templates if os.path.isfile(
        os.path.join(front_end_templates, "base_template_v2.html")) else None,
}))
"""


def _probe():
    """Import Potato from a directory that is not the checkout."""
    with tempfile.TemporaryDirectory() as outside:
        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            capture_output=True, text=True, timeout=300, cwd=outside)
    assert result.returncode == 0, (
        f"the probe failed to import Potato from outside the checkout: "
        f"{result.stderr[-2000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _inside(path, root):
    return os.path.commonpath([os.path.abspath(path), root]) == root


class TestTemplatesComeFromTheCheckout:
    def test_the_jinja_search_path_is_in_the_checkout(self):
        probe = _probe()
        assert probe["jinja_searchpath"], "Flask has no template search path"
        for path in probe["jinja_searchpath"]:
            assert _inside(path, REPO_ROOT), (
                f"Flask would load templates from {path}, which is outside "
                f"{REPO_ROOT}. app.root_path is {probe['flask_root']}.")

    def test_the_jinja_search_path_sits_beside_flask_root(self):
        # The mechanism, stated: Flask derives root_path from the calling
        # module's __file__. If that ever changes to a package-path lookup this
        # is the assertion that notices.
        probe = _probe()
        for path in probe["jinja_searchpath"]:
            assert _inside(path, probe["flask_root"]), (
                f"{path} is not inside app.root_path ({probe['flask_root']})")

    def test_front_end_resolves_templates_beside_its_own_file(self):
        probe = _probe()
        assert probe["resolved_base_template"], (
            "base_template_v2.html was not found in the directory front_end.py "
            f"builds: {probe['front_end_templates']}")
        assert _inside(probe["front_end_templates"], REPO_ROOT)

    def test_no_template_directory_comes_from_the_namespace_path(self):
        """The failure this file exists for.

        Skipped where there is no shadow: with a healthy install
        `potato.__path__` IS the checkout, so every path below is legitimately
        inside it and the assertion cannot distinguish anything.
        """
        import pytest

        probe = _probe()
        if probe["package_file"] is not None:
            pytest.skip("`potato` imports as a real package here, so "
                        "potato.__path__ and the checkout are the same "
                        "directory and there is nothing to tell apart")

        stale = [path for path in probe["namespace_path"]
                 if not _inside(path, REPO_ROOT)]
        assert stale, "namespace package with no directory outside the checkout"

        reachable = (probe["jinja_searchpath"]
                     + [probe["front_end_templates"]])
        for path in reachable:
            for shadow in stale:
                assert not _inside(path, shadow), (
                    f"{path} resolves inside {shadow}, a leftover directory "
                    f"outside the checkout. Templates would be read from it.")
