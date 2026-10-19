"""Install the plugins under examples/plugins for a test, without pip.

``tests/data/plugins/example-site`` holds a .dist-info for each example
plugin, with the same entry points as its pyproject.toml. Putting that folder
and the plugin's source folder on sys.path is what ``pip install -e`` amounts
to as far as importlib.metadata and the import system are concerned.
"""

import os
import sys
from contextlib import contextmanager

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXAMPLE_SITE = os.path.join(REPO_ROOT, "tests", "data", "plugins", "example-site")
EXAMPLE_SOURCES = [os.path.join(REPO_ROOT, "examples", "plugins", "counter", "plugin")]


@contextmanager
def example_plugins_installed():
    from potato import plugins

    added = [p for p in [EXAMPLE_SITE, *EXAMPLE_SOURCES] if p not in sys.path]
    sys.path[:0] = added
    before = set(plugins.loaded())
    try:
        yield
    finally:
        for name in set(plugins.loaded()) - before:
            plugins.unload(name)
        for path in added:
            sys.path.remove(path)
        for module in [m for m in sys.modules if m.startswith("potato_plugin_example")]:
            del sys.modules[module]


def example_plugin_types():
    """{"schema": {...}, "display": {...}}: the types the example plugins add."""
    from potato import plugins

    types = {"schema": set(), "display": set()}
    with example_plugins_installed():
        for name in plugins.discover():
            if name in plugins.loaded():
                continue
            try:
                plugin = plugins.load_plugin(name)
            except plugins.PluginError:
                continue  # another installed plugin, not one of the examples
            types["schema"].update(plugin.schemas)
            types["display"].update(plugin.displays)
    return types
