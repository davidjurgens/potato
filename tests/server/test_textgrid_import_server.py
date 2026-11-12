"""An imported TextGrid opens with its segmentation filled in (pre-annotation
into tiered_annotation's hidden input), and the audio is served from media/."""

import json
import os
from pathlib import Path

import pytest
import requests

from potato.importers import projects
from potato.importers.projects.writer import write_project
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory
from tests.unit.test_textgrid_project_import import _source


@pytest.fixture(scope="module")
def tg_server(request):
    d, src = _source("tg_import_server")
    out = d / "project"
    write_project(projects.IMPORTERS["textgrid"].parse_path(src), str(out), source=str(src))
    # The in-process harness resolves a relative output dir against the
    # working directory; pin it so the export reads what the server wrote.
    import yaml
    cfg = yaml.safe_load((out / "config.yaml").read_text())
    cfg["output_annotation_dir"] = str(out / "annotation_output")
    (out / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    server = FlaskTestServer(config=str(out / "config.yaml"))
    server.project_config = str(out / "config.yaml")
    if not server.start():
        pytest.fail("Failed to start Flask test server on the imported TextGrid project")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(str(d))))
    return server


def test_segments_are_prefilled_and_media_served(tg_server):
    s = requests.Session()
    s.post(f"{tg_server.base_url}/register", data={"action": "signup", "email": "tg", "pass": "p"}, timeout=5)
    s.post(f"{tg_server.base_url}/auth", data={"action": "login", "email": "tg", "pass": "p"}, timeout=5)
    page = s.get(f"{tg_server.base_url}/annotate", timeout=5).text
    from bs4 import BeautifulSoup
    field = BeautifulSoup(page, "html.parser").find("input", id="input-tiers")
    assert field is not None, "tiered hidden input missing"
    assert field.get("data-server-set") == "true"
    data = json.loads(field["value"])
    assert [a["label"] for a in data["annotations"]["words"]] == ["hello", 'world "quoted"']
    audio = s.get(f"{tg_server.base_url}/media/clip01.wav", timeout=5)
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_saved_tiers_export_back_out(tg_server):
    """Audit 96 L3: the page saves {"tiers": {"_data": "<json>"}}; the TextGrid
    and EAF exports must unwrap it, not write empty tiers."""
    from potato.export.cli import build_export_context
    from potato.export.eaf_exporter import EAFExporter
    from potato.export.textgrid_exporter import TextGridExporter
    base = tg_server.base_url
    s = requests.Session()
    s.post(f"{base}/register", data={"action": "signup", "email": "tg_save", "pass": "p"}, timeout=5)
    s.post(f"{base}/auth", data={"action": "login", "email": "tg_save", "pass": "p"}, timeout=5)
    page = s.get(f"{base}/annotate", timeout=5).text
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    value = soup.find("input", id="input-tiers")["value"]
    iid = soup.find("input", id="instance_id")["value"]
    r = s.post(f"{base}/updateinstance", json={"instance_id": iid,
               "annotations": {"tiers:::_data": value}, "span_annotations": []}, timeout=5)
    assert r.status_code == 200
    config = tg_server.project_config
    ctx = build_export_context(config)
    out = os.path.join(os.path.dirname(config), "export_check")
    for exporter, ext in ((TextGridExporter(), ".TextGrid"), (EAFExporter(), ".eaf")):
        result = exporter.export(ctx, out)
        assert result.success and result.stats["annotations"] >= 2, (ext, result.stats)
        text = open(next(f for f in result.files_written if f.endswith(ext)), encoding="utf-8").read()
        assert "hello" in text, ext
