"""An imported PCIbex Latin-square study runs: each participant gets one list
and the timed reading page carries that list's sentence."""

import json
import re

import pytest
import requests

from potato.importers import projects
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory
from tests.unit.test_ibex_import import ITEMS_CSV, PCIBEX_JS, _project


@pytest.fixture(scope="module")
def ibex_server(request):
    d = _project("ibex_import_server", {"data_includes/main.js": PCIBEX_JS,
                                        "chunk_includes/items.csv": ITEMS_CSV})
    imp = projects.IMPORTERS["ibex"]
    imp.write_project(imp.parse_path(d / "src"), str(d / "out"), source=str(d / "src"))
    server = FlaskTestServer(config=str(d / "out" / "config.yaml"))
    if not server.start():
        pytest.fail("the imported Ibex project did not start")
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(str(d))))
    return server


def test_each_participant_reads_one_list(ibex_server):
    base = ibex_server.base_url
    firsts = set()
    for name in ("ibex_p1", "ibex_p2"):
        s = requests.Session()
        s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
        s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
        html = s.get(f"{base}/annotate", timeout=5).text
        cfg = json.loads(re.search(r"window\.potatoTrialTiming\s*=\s*(\{.*?\});", html, re.S).group(1))
        firsts.add(" ".join(cfg["presentation"]["regions"]))
        iid = re.search(r'id="instance_id"[^>]*value="([^"]+)"', html).group(1)
        assert iid.startswith("items_")
    assert len(firsts) == 2, "both participants got the same list"
