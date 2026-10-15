"""Phone-width layout of the labeling engine's pages.

The admin page (contract table, charts, request and call tables) and the note
the engine puts above an item on /annotate, on real device emulation (see
``tests/helpers/mobile.py``). Pocket's auto-redirect is off here so a phone
reaches /annotate; Pocket on an engine study is covered in
``tests/server/test_labeling_engine_server.py``.
"""

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import PHONES, layout_problems, mobile_page  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)

pytestmark = pytest.mark.playwright

ADMIN_KEY = "engine-mobile-admin-key"


@pytest.fixture(scope="module")
def engine_server():
    test_dir = create_test_directory("labeling_engine_mobile")
    data = [{"id": f"item_{k}", "text": f"A review of a product, number {k}, "
             "long enough to wrap on a phone screen.", "gold": "positive" if k % 2 else "negative"}
            for k in range(40)]
    config_file = create_test_config(
        test_dir,
        [{"name": "sentiment", "description": "Sentiment", "annotation_type": "radio",
          "labels": ["positive", "negative"]}],
        data_files=[create_test_data_file(test_dir, data)],
        assignment_strategy="engine", admin_api_key=ADMIN_KEY,
        additional_config={
            "labeling_engine": {
                "enabled": True,
                "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.1}],
                "contracts": [{"id": "acc", "kind": "selective_risk", "schema": "sentiment",
                               "error": 0.2, "confidence": 0.8}],
                "humans": {"calibration_rate": 0.5},
                "runtime": {"planner_interval": 3600}},
            "pocket": {"enabled": True, "auto_redirect": False},
        })
    server = FlaskTestServer(port=find_free_port(preferred_port=9660), config_file=config_file)
    if not server.start():
        pytest.fail("could not start the labeling engine server")
    from potato.labeling_engine.integration.hooks import clear_engine, get_engine, get_planner
    get_planner().tick()
    # Answer some calibration requests so the charts have data to draw.
    eng = get_engine()
    gold = {d["id"]: d["gold"] for d in data}
    for r in eng.store.requests(status=["open"], purpose=["calibration"])[:12]:
        eng.record_human_label(r.item_id, r.schema, gold[r.item_id], "seed_user",
                               request_id=r.id)
    yield server
    server.stop()
    clear_engine()
    cleanup_test_directory(test_dir)


@pytest.mark.parametrize("device", PHONES)
def test_admin_page_fits(engine_server, device):
    with mobile_page(device, engine_server.base_url,
                     extra_headers={"X-API-Key": ADMIN_KEY}) as page:
        page.goto("/admin/labeling-engine")
        page.wait_for_selector("#le-schemes svg")
        page.wait_for_selector("#le-calls table, #le-calls .le-empty")
        problems = layout_problems(page, ["#le-plan", "#le-certify", "#le-calls-next",
                                          ".le-statements"])
        assert not problems, "\n".join(problems)


@pytest.mark.parametrize("device", PHONES)
def test_annotate_note_fits(engine_server, device):
    with mobile_page(device, engine_server.base_url) as page:
        user = f"phone_{device.split()[0].lower()}"
        page.context.request.post(f"{engine_server.base_url}/register",
                                  form={"email": user, "pass": "pass"})
        page.context.request.post(f"{engine_server.base_url}/auth",
                                  form={"email": user, "pass": "pass"})
        page.goto("/annotate")
        page.wait_for_selector(".engine-request-note")
        problems = layout_problems(page, [".engine-request-note", "#next-btn"])
        assert not problems, "\n".join(problems)
