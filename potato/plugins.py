"""
Plugins: annotation schemes and display types from installed packages.

A plugin is a Python package that declares an entry point in the
``potato.plugins`` group. The entry point names a function that takes a
:class:`PluginAPI` and registers what the plugin provides::

    # the plugin's pyproject.toml
    [project.entry-points."potato.plugins"]
    counter = "potato_plugin_example:register"

    # potato_plugin_example/__init__.py
    def register(api):
        api.add_schema("counter", generate_counter_layout,
                       optional_fields=["min", "max"])
        api.add_display("word_count", WordCountDisplay())
        api.add_assets("static", scripts=["counter.js"], styles=["counter.css"])

A project turns a plugin on by naming it in its config::

    plugins:
      - counter

Only plugins a config names are loaded. Installing a package is not enough,
because a plugin is ordinary Python running inside the server with the
server's permissions. Loading happens at the top of config validation, so the
server, ``potato validate`` and ``potato preview`` all see the same types.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "potato.plugins"
STATIC_URL_PREFIX = "/plugin-static"


class PluginError(Exception):
    """A plugin could not be found, loaded or registered."""


@dataclass
class LoadedPlugin:
    name: str
    package: str
    version: str
    schemas: List[str] = field(default_factory=list)
    displays: List[str] = field(default_factory=list)
    static_dir: Optional[str] = None
    scripts: List[str] = field(default_factory=list)
    styles: List[str] = field(default_factory=list)

    def asset_url(self, path: str) -> str:
        """The path a page uses for one of this plugin's static files.

        Relative to the deployment root; the base template puts the URL
        prefix in front.
        """
        return f"{STATIC_URL_PREFIX}/{self.name}/{path}?v={self.version}"


class PluginAPI:
    """What a plugin's ``register(api)`` function receives.

    Nothing is registered until ``register`` returns without an error, so a
    plugin that fails halfway leaves no partial set of types behind.
    """

    def __init__(self, name: str, package: str, version: str, module_dir: Optional[str]):
        self.name = name
        self.package = package
        self.version = version
        self._module_dir = module_dir
        self._schemas: List[Any] = []
        self._displays: List[tuple] = []
        self._static_dir: Optional[str] = None
        self._scripts: List[str] = []
        self._styles: List[str] = []

    def add_schema(self, name: str, generator: Callable, *,
                   required_fields: Sequence[str] = ("name", "description"),
                   optional_fields: Sequence[str] = (),
                   description: str = "",
                   supports_keybindings: bool = False) -> None:
        """Register an annotation type.

        ``generator(annotation_scheme)`` returns ``(html, keybindings)``, like
        the built-in generators in ``potato/server_utils/schemas/``. Every
        config key the generator reads belongs in ``optional_fields``:
        validation warns about any other key on a scheme of this type.
        """
        from potato.server_utils.schemas.registry import SchemaDefinition
        if not callable(generator):
            raise PluginError(f"plugin '{self.name}': the generator for '{name}' is not callable")
        if any(s.name == name for s in self._schemas):
            raise PluginError(f"plugin '{self.name}' registers annotation type '{name}' twice")
        self._schemas.append(SchemaDefinition(
            name=name, generator=generator, required_fields=list(required_fields),
            optional_fields=list(optional_fields), description=description,
            supports_keybindings=supports_keybindings))

    def add_display(self, name: str, display: Any) -> None:
        """Register a display type: an instance of ``BaseDisplay``."""
        from potato.server_utils.displays.base import BaseDisplay
        if not isinstance(display, BaseDisplay):
            raise PluginError(f"plugin '{self.name}': display '{name}' must be a BaseDisplay "
                              f"instance, not {type(display).__name__}")
        if any(existing == name for existing, _ in self._displays):
            raise PluginError(f"plugin '{self.name}' registers display type '{name}' twice")
        self._displays.append((name, display))

    def add_assets(self, static_dir: str, *, scripts: Iterable[str] = (),
                   styles: Iterable[str] = ()) -> None:
        """Serve a folder of static files and load some of them on every page.

        ``static_dir`` is relative to the plugin's package folder. Files in it
        are served at ``/plugin-static/<plugin>/<file>``; ``scripts`` and
        ``styles`` are added to every annotation and phase page.
        """
        base = self._module_dir or os.getcwd()
        folder = os.path.realpath(os.path.join(base, static_dir))
        if not os.path.isdir(folder):
            raise PluginError(f"plugin '{self.name}': static folder not found: {folder}")
        self._static_dir = folder
        for kind, names, target in (("script", scripts, self._scripts),
                                    ("style", styles, self._styles)):
            for asset in names:
                if not os.path.isfile(os.path.join(folder, asset)):
                    raise PluginError(f"plugin '{self.name}': {kind} '{asset}' is not in {folder}")
                target.append(asset)


_LOADED: Dict[str, LoadedPlugin] = {}
_TYPE_OWNERS: Dict[str, str] = {}


def _entry_points():
    from importlib.metadata import entry_points
    found = entry_points()
    if hasattr(found, "select"):
        return list(found.select(group=ENTRY_POINT_GROUP))
    return list(found.get(ENTRY_POINT_GROUP, []))  # Python 3.9


def discover() -> Dict[str, Any]:
    """Installed plugins, by entry-point name. Nothing is imported."""
    return {ep.name: ep for ep in _entry_points()}


def _package_of(entry_point) -> tuple:
    dist = getattr(entry_point, "dist", None)
    if dist is None:
        return entry_point.value.split(":")[0].split(".")[0], "0"
    return dist.metadata["Name"], dist.version


def load_plugin(name: str) -> LoadedPlugin:
    """Load one plugin by its entry-point name. Loading twice is a no-op."""
    if name in _LOADED:
        return _LOADED[name]
    installed = discover()
    if name not in installed:
        known = ", ".join(sorted(installed)) or "none"
        raise PluginError(f"plugin '{name}' is not installed (installed plugins: {known}). "
                          f"Install the package that provides it, then check it with "
                          f"`potato plugins`.")
    entry_point = installed[name]
    package, version = _package_of(entry_point)
    try:
        target = entry_point.load()
    except Exception as exc:
        raise PluginError(f"plugin '{name}' failed to import ({entry_point.value}): {exc}") from exc
    register = target if callable(target) else getattr(target, "register", None)
    if not callable(register):
        raise PluginError(f"plugin '{name}': entry point {entry_point.value} is neither a "
                          f"function nor a module with a register(api) function")

    module = getattr(register, "__module__", None)
    module_file = getattr(sys.modules.get(module), "__file__", None) if module else None
    api = PluginAPI(name, package, version, os.path.dirname(module_file) if module_file else None)
    try:
        register(api)
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError(f"plugin '{name}' raised while registering: {exc}") from exc

    _commit(api)
    plugin = LoadedPlugin(
        name=name, package=package, version=version,
        schemas=[s.name for s in api._schemas], displays=[d[0] for d in api._displays],
        static_dir=api._static_dir, scripts=list(api._scripts), styles=list(api._styles))
    _LOADED[name] = plugin
    logger.info("Loaded plugin %s (%s %s): schemas %s, displays %s", name, package, version,
                plugin.schemas or "none", plugin.displays or "none")
    return plugin


def _commit(api: PluginAPI) -> None:
    """Register everything, or nothing if any name is taken."""
    from potato.server_utils.displays import display_registry
    from potato.server_utils.schemas.registry import schema_registry

    taken = []
    for schema in api._schemas:
        if schema_registry.is_registered(schema.name):
            owner = _TYPE_OWNERS.get(("schema", schema.name))
            taken.append(f"annotation type '{schema.name}' "
                         f"({'from plugin ' + repr(owner) if owner else 'built in'})")
    for name, _display in api._displays:
        if display_registry.get(name) is not None:
            owner = _TYPE_OWNERS.get(("display", name))
            taken.append(f"display type '{name}' "
                         f"({'from plugin ' + repr(owner) if owner else 'built in'})")
    if taken:
        raise PluginError(f"plugin '{api.name}' uses names that already exist: {'; '.join(taken)}")

    for schema in api._schemas:
        schema_registry.register(schema)
        _TYPE_OWNERS[("schema", schema.name)] = api.name
    for name, display in api._displays:
        display_registry.register_plugin(name, display)
        _TYPE_OWNERS[("display", name)] = api.name


def unload(name: str) -> None:
    """Remove a plugin and its types. For tests; a running server never unloads."""
    from potato.server_utils.displays import display_registry
    from potato.server_utils.schemas.registry import schema_registry

    plugin = _LOADED.pop(name, None)
    if plugin is None:
        return
    for schema in plugin.schemas:
        schema_registry._schemas.pop(schema, None)
        _TYPE_OWNERS.pop(("schema", schema), None)
    for display in plugin.displays:
        display_registry._plugins.pop(display, None)
        _TYPE_OWNERS.pop(("display", display), None)


def load_plugins(names: Iterable[str]) -> List[LoadedPlugin]:
    return [load_plugin(name) for name in names]


def owner_of(kind: str, type_name: str) -> Optional[str]:
    """The plugin that registered a type (``kind`` is "schema" or "display")."""
    return _TYPE_OWNERS.get((kind, type_name))


def loaded() -> Dict[str, LoadedPlugin]:
    return dict(_LOADED)


def plugin_assets(names: Optional[Iterable[str]] = None) -> Dict[str, List[str]]:
    """Script and style URLs for the base template, from the plugins ``names``.

    Pass the config's ``plugins`` list. One process can have loaded plugins for
    another config (the MCP server, tests), and their scripts do not belong on
    this project's pages.
    """
    scripts, styles = [], []
    for name in names or []:
        plugin = _LOADED.get(name)
        if plugin is None:
            continue
        scripts.extend(plugin.asset_url(s) for s in plugin.scripts)
        styles.extend(plugin.asset_url(s) for s in plugin.styles)
    return {"scripts": scripts, "styles": styles}


def static_folder(name: str) -> Optional[str]:
    plugin = _LOADED.get(name)
    return plugin.static_dir if plugin else None


# --- config -----------------------------------------------------------------

def configured_names(config_data: Dict[str, Any]) -> List[str]:
    """The ``plugins:`` list, checked for shape. Raises ValueError."""
    names = config_data.get("plugins")
    if names is None:
        return []
    if not isinstance(names, list):
        raise ValueError("plugins must be a list of installed plugin names")
    seen = []
    for index, name in enumerate(names):
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"plugins[{index}] must be a plugin name (a non-empty string)")
        if name in seen:
            raise ValueError(f"plugins lists '{name}' twice")
        seen.append(name)
    return seen


def _walk(node: Any, path: str):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def unlisted_plugin_types(config_data: Dict[str, Any]) -> List[str]:
    """Types a config uses from plugins it does not list.

    One process can load plugins for one config and then validate another
    (tests, the MCP server). Without this check the second config would pass
    here and fail on a fresh ``potato start``.
    """
    listed = set(configured_names(config_data))
    problems = []
    for path, node in _walk(config_data, ""):
        annotation_type = node.get("annotation_type")
        if isinstance(annotation_type, str):
            owner = owner_of("schema", annotation_type)
            if owner and owner not in listed:
                problems.append(f"{path}: annotation type '{annotation_type}' comes from plugin "
                                f"'{owner}'; add '{owner}' to plugins")
        display_type = node.get("type")
        if isinstance(display_type, str) and ".fields[" in path:
            owner = owner_of("display", display_type)
            if owner and owner not in listed:
                problems.append(f"{path}: display type '{display_type}' comes from plugin "
                                f"'{owner}'; add '{owner}' to plugins")
    return problems


# --- CLI --------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """``potato plugins``: list installed plugins, or load one to check it."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="potato plugins",
        description="List installed Potato plugins, or load one to check that it registers.")
    parser.add_argument("check", nargs="?", metavar="NAME",
                        help="load this plugin and print what it registers")
    args = parser.parse_args(argv)

    if args.check:
        try:
            plugin = load_plugin(args.check)
        except Exception as exc:  # noqa: BLE001 - report any failure, not a traceback
            print(f"error: {exc}")
            return 1
        print(f"{plugin.name}: {plugin.package} {plugin.version}")
        print(f"  annotation types: {', '.join(plugin.schemas) or 'none'}")
        print(f"  display types:    {', '.join(plugin.displays) or 'none'}")
        print(f"  scripts:          {', '.join(plugin.scripts) or 'none'}")
        print(f"  styles:           {', '.join(plugin.styles) or 'none'}")
        return 0

    installed = discover()
    if not installed:
        print("No plugins installed. A plugin is a package with a "
              f"'{ENTRY_POINT_GROUP}' entry point; see docs/advanced/plugins.md.")
        return 0
    for name, entry_point in sorted(installed.items()):
        package, version = _package_of(entry_point)
        print(f"{name:<20} {package} {version}  ({entry_point.value})")
    print("\nTurn one on with `plugins: [<name>]` in a config. "
          "`potato plugins <name>` loads it and lists its types.")
    return 0
