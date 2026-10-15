"""
The engine_* MCP tools: bad parameters are refused, not served a default.
"""

import pytest
from flask import Flask

from potato.labeling_engine.integration import hooks
from potato.mcp_server.routes import mcp_bp
from potato.persistence import clear_db_cache
from potato.server_utils.agent_tokens import issue_token

from .test_engine_service import _config, _items

TOOLS = ["engine_status", "engine_requests", "engine_certificate"]


@pytest.fixture
def client(tmp_path):
    clear_db_cache()
    config = _config(tmp_path)
    config.update({"output_annotation_dir": str(tmp_path / "out"),
                   "item_properties": {"id_key": "id", "text_key": "text"},
                   "mcp": {"enabled": True, "tools": TOOLS}})
    eng = hooks.init_engine(config, start_planner=False)
    items = _items(200)
    eng.register_items(items)
    scheme = eng.scheme("sentiment")
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    app = Flask(__name__)
    app.config["mcp_task_config"] = config
    app.register_blueprint(mcp_bp)
    token = issue_token("agent", role="admin", config=config)
    c = app.test_client()

    def post(tool, payload):
        return c.post(f"/api/mcp/tools/{tool}", json=payload,
                      headers={"Authorization": f"Bearer {token}"})
    yield post
    hooks.clear_engine()
    clear_db_cache()


def test_certificate_format_html_and_unknown(client):
    r = client("engine_certificate", {"format": "html"})
    assert r.status_code == 200 and r.get_json()["html"].lstrip().startswith("<")
    r = client("engine_certificate", {"format": "xml"})
    assert r.status_code == 400 and "xml" in r.get_json()["error"]


def test_requests_takes_comma_lists_and_rejects_unknown_values(client):
    one = client("engine_requests", {"purpose": "calibration"}).get_json()["requests"]
    both = client("engine_requests", {"purpose": "calibration,verify"}).get_json()
    assert len(both["requests"]) >= len(one) > 0
    r = client("engine_requests", {"purpose": "calibraton"})
    assert r.status_code == 400 and "calibraton" in r.get_json()["error"]
    r = client("engine_requests", {"limit": "abc"})
    assert r.status_code == 400 and "limit" in r.get_json()["error"]
