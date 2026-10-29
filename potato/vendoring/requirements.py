"""
Which fetchable bundles a config needs, and the check that they are installed.

Features declare what they need: runtime adapters through
``RuntimeAdapter.required_bundles`` and viewer displays through
``required_bundles(display_config)``. ``potato vendor fetch --for-config``
reads :func:`required_bundles`.

The check that fails ``potato validate`` and server start on a missing bundle
is not :func:`check_installed`. It is the viewer-display validation
(``config_module._validate_viewer_displays`` ->
``viewer_display.validate_viewer_field``), which names the ``potato vendor
fetch`` command. No runtime adapter declares a bundle yet, so viewer displays
are the only features that need one. :func:`check_installed` covers both
kinds but nothing calls it at boot or in ``potato validate``; a runtime
adapter that starts declaring bundles needs it (or an equivalent) wired into
config validation.
"""

from __future__ import annotations

from typing import Any, Dict, List


def required_bundles(config: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    from potato.runtimes.phase import runtime_entries
    from potato.runtimes.registry import get_adapter
    for _name, entry in runtime_entries(config):
        adapter = get_adapter(entry.get("_kind"))
        if adapter is not None:
            names.extend(adapter.required_bundles(entry))
    try:
        from potato.server_utils.displays.registry import display_required_bundles
        names.extend(display_required_bundles(config))
    except ImportError:
        pass
    # chemical_structure with `rdkit: true` (RDKit.js).
    from potato.chemistry.structures import required_bundles as _chemistry_bundles
    names.extend(_chemistry_bundles(config))
    return list(dict.fromkeys(names))


def check_installed(config: Dict[str, Any]) -> None:
    """Raise ConfigValidationError naming the fetch command when a bundle the
    config needs is not installed. Not called at boot; see the module note."""
    from potato import vendoring
    from potato.server_utils.config_module import ConfigValidationError
    missing = vendoring.missing(required_bundles(config))
    if missing:
        raise ConfigValidationError(
            f"This config needs browser libraries that are not installed: "
            f"{', '.join(missing)}. Install them with `{vendoring.fetch_hint(missing)}` "
            f"(or `potato vendor fetch --for-config <config>`).")
