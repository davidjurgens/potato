from pathlib import Path

from potato.flask_server import _detect_frontend_assets_for_page


def test_detect_frontend_assets_uses_current_page_html_only(tmp_path):
    html_file = tmp_path / "triage_only.html"
    html_file.write_text(
        """
        <html>
            <body>
                <form class="annotation-form triage" data-annotation-type="triage">
                    <div class="triage-container"></div>
                </form>
            </body>
        </html>
        """,
        encoding="utf-8",
    )

    assets = _detect_frontend_assets_for_page(str(html_file))

    assert assets["triage"] is True
    assert assets["web_agent_viewer"] is False
    assert assets["web_agent_playback"] is False
    assert assets["pdf_bbox"] is False
    assert assets["tiered_annotation"] is False


def test_detect_frontend_assets_includes_display_html_markers(tmp_path):
    html_file = tmp_path / "blank.html"
    html_file.write_text("<html><body></body></html>", encoding="utf-8")

    display_html = """
    <div class="web-agent-viewer" data-auto-playback="true"></div>
    <div class="pdf-display pdf-viewer-paginated pdf-bbox-mode">
        <canvas class="pdf-bbox-canvas"></canvas>
    </div>
    """

    assets = _detect_frontend_assets_for_page(str(html_file), display_html=display_html)

    assert assets["web_agent_viewer"] is True
    assert assets["web_agent_playback"] is True
    assert assets["pdf_bbox"] is True
