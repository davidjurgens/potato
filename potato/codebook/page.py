"""
Codebook full-page document view.

A *second* blueprint (no /api prefix) serving the human-facing living
codebook document at ``/codebook``. Kept separate from ``codebook_bp`` so
the page route sits at the site root while the JSON API stays under
``/api/codebook``. Registered in routes.py's blueprint block — a
module-level ``@app.route`` would 404 under the served ``create_app()`` app.

The page is a shell; all content loads via the codebook content API
(``/api/codebook/document`` …), which enforces auth + mode gating. The
page itself redirects unauthenticated users to login and 404s when the
codebook feature is disabled.
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, session

codebook_page_bp = Blueprint("codebook_page", __name__)


@codebook_page_bp.route("/codebook")
def codebook_document_page():
    from potato.server_utils.config_module import config
    from potato.codebook.api import codebook_enabled
    if not codebook_enabled(config):
        return ("Codebook is not enabled in this deployment.", 404)
    if not session.get("username"):
        return redirect("/")
    return render_template(
        "codebook_document.html",
        project=config.get("annotation_task_name") or "default",
    )
