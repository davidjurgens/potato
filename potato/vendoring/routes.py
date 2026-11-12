"""Serves bundles installed with ``potato vendor fetch``.

``GET /vendor-fetched/<name>-<version>/<path>``

Only files the bundle recorded at install are served, so nothing else in the
vendor directory is reachable. The bytes are pinned per version, so the
response can be cached for a long time.
"""

from __future__ import annotations


def vendor_fetched(dirname: str, path: str):
    from flask import abort, send_file
    from potato import vendoring
    for bundle in vendoring.all_bundles():
        if bundle.dirname == dirname:
            break
    else:
        abort(404)
    resolved = vendoring.file_path(bundle.name, path)
    if resolved is None:
        abort(404)
    mimetype = "application/wasm" if path.endswith(".wasm") else None
    response = send_file(str(resolved), mimetype=mimetype, max_age=31536000)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if not path.endswith((".js", ".mjs", ".css", ".wasm")):
        # A file opened on its own must not run script on this origin.
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


def register_vendor_routes(app) -> None:
    if "vendor_fetched" in app.view_functions:
        return
    app.add_url_rule("/vendor-fetched/<dirname>/<path:path>", "vendor_fetched", vendor_fetched)
