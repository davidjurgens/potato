"""`potato.routes` is imported before any app serves.

`potato/routes.py` registers 159 handlers with module-level `@app.route`
decorators against `potato.flask_server.app`, and `create_app()` does
`global app; app = Flask(...)` -- it rebinds that name to the app it builds.
Flask refuses a `route` call on an app that has already handled a request, so
importing routes late raises:

    AssertionError: The setup method 'route' can no longer be called on the
    application. It has already handled its first request.

That message names nothing about Potato, which is the expensive part. A
two-file reproduction exists today:

    pytest tests/unit/test_proxy_prefix_static_urls.py \\
           tests/unit/test_qa_bugfix_regressions.py

Both files pass alone, `pytest tests/unit` is green, and the failure is
identical at HEAD. The full suite passes because something between those two
files resets the state -- which makes the green order-luck rather than
evidence.

The underlying design (module-level decorators on a rebound global) has not
been changed; that is a larger call, and the two candidate fixes -- eager
importing at boot, or moving all 159 decorators into `configure_routes` --
trade against the boot-import-weight rule. What is pinned here is the one
thing that keeps the normal path working, so a refactor that makes the import
lazy fails loudly instead of shipping a landmine.
"""

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Builds an app the way a WSGI factory does and reports whether routes was
#: imported by the time the app existed -- before any request is made.
_PROBE = r"""
import sys
assert "potato.routes" not in sys.modules, (
    "something imported potato.routes before create_app ran; this probe "
    "cannot measure what it is for")

from potato.flask_server import create_app
app = create_app()

print("ROUTES_IMPORTED", "potato.routes" in sys.modules or "routes" in sys.modules)
print("HAS_SERVED", getattr(app, "_got_first_request", False))
"""


def _probe():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT)
    assert result.returncode == 0, (
        f"the probe failed: {result.stderr[-2000:]}")
    out = dict(
        line.split(" ", 1) for line in result.stdout.strip().splitlines()
        if line.startswith(("ROUTES_IMPORTED", "HAS_SERVED")))
    return {key: value.strip() == "True" for key, value in out.items()}


class TestRoutesImportOrder:
    def test_create_app_imports_routes_before_returning(self):
        probe = _probe()
        assert probe.get("ROUTES_IMPORTED") is True, (
            "create_app() returned without importing the routes module. Its "
            "module-level @app.route decorators will now run against whatever "
            "app is current at first import, and if that app has served, Flask "
            "refuses with a message that names nothing about Potato. See the "
            "note at the `global app` line in create_app().")

    def test_the_app_has_not_served_when_routes_lands(self):
        # The other half of the same invariant: importing routes early is only
        # useful if nothing has served by then.
        probe = _probe()
        assert probe.get("HAS_SERVED") is False
