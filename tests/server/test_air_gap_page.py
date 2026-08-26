"""
A rendered page must be able to load with no internet.

The unit guards read the templates. This reads what the server actually *sent*,
which is the only version that accounts for the asset-gating layer: an asset can
be vendored, committed, and referenced by a template, and still 404 because
``FRONTEND_ASSET_MARKERS`` never turned it on for the schema in question. That
failure is invisible to a template scan and invisible to anything but the
project type that triggers it.

So this renders the annotation page for a deep-zoom project — the newest and
most heavily gated of the vision surfaces — and requires every local asset it
references to come back 200, with the external ones limited to the known,
documented set.
"""

import json
import os
import re

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

PIL = pytest.importorskip("PIL", reason="the deep-zoom page needs Pillow")

#: External hosts the app is known to still depend on, each documented in
#: docs/deployment/air_gap.md with the consequence of its absence.
KNOWN_EXTERNAL = {
    "code.jquery.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
    "stackpath.bootstrapcdn.com", "d3js.org",
}

ASSET = re.compile(
    r'(?:<script[^>]+src|<link[^>]+href)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE)


@pytest.fixture(scope="module")
def server():
    from PIL import Image

    test_dir = create_test_directory("air_gap_page")
    media = os.path.join(test_dir, "media")
    os.makedirs(media, exist_ok=True)
    Image.new("RGB", (900, 700), "white").save(os.path.join(media, "big.png"))

    data_file = os.path.join(test_dir, "items.json")
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump([{"id": "a1", "image": "big.png"}], handle)

    config = {
        "port": 0,
        "annotation_task_name": "air gap",
        "task_dir": test_dir,
        "media_directory": media,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "data_files": [data_file],
        "item_properties": {"id_key": "id", "text_key": "image"},
        "user_config": {"allow_all_users": True},
        "annotation_schemes": [{
            "annotation_type": "image_annotation",
            "name": "regions",
            "description": "Regions",
            "source_field": "image",
            "viewer": "deepzoom",
            "tools": ["bbox", "brush"],
            "labels": [{"name": "a", "color": "#f00"}],
        }],
    }
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle)

    srv = FlaskTestServer(port=find_free_port(), debug=False,
                          config_file=config_path)
    if not srv.start():
        pytest.fail("Failed to start the air-gap test server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def page(server):
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": "airgap", "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth",
                 data={"email": "airgap", "pass": "pw"})
    response = session.get(f"{server.base_url}/annotate")
    assert response.status_code == 200
    return response.text


def _assets(html):
    local, external = [], []
    for url in ASSET.findall(html):
        if url.startswith(("http://", "https://")):
            external.append(url)
        elif url.startswith("/"):
            local.append(url)
    return local, external


class TestEveryLocalAssetResolves:
    def test_the_page_references_a_realistic_number_of_assets(self, page):
        """Guards against a regex that quietly stops matching."""
        local, _external = _assets(page)
        assert len(local) > 15, f"only found {len(local)} local assets"

    def test_every_local_asset_returns_200(self, server, page):
        """
        The check a template scan cannot do. An asset can be vendored,
        committed and referenced and still 404 because the gating layer never
        enabled it for this schema — which is exactly how a newly-gated file
        breaks one project type and nothing else.
        """
        local, _external = _assets(page)
        broken = []
        for path in sorted(set(local)):
            response = requests.get(f"{server.base_url}{path}")
            if response.status_code != 200:
                broken.append(f"{path} -> {response.status_code}")
        assert not broken, (
            "The page references local assets the server does not serve:\n  "
            + "\n  ".join(broken))

    def test_the_check_would_notice_a_missing_file(self, server):
        """Proof the assertion above is not vacuously true."""
        response = requests.get(f"{server.base_url}/static/definitely-not-here.js")
        assert response.status_code == 404


class TestTheDeepZoomAssetsAreLocal:
    def test_openseadragon_is_served_from_vendor(self, server, page):
        assert "vendor/openseadragon-" in page, (
            "the deep-zoom page did not load OpenSeadragon at all")
        match = re.search(r'["\'](/static/vendor/openseadragon-[^"\']+)["\']', page)
        assert match, "OpenSeadragon is referenced but not from /static/vendor/"
        assert requests.get(f"{server.base_url}{match.group(1)}").status_code == 200

    def test_the_viewer_script_is_served(self, server, page):
        match = re.search(r'["\'](/static/deepzoom-viewer\.js[^"\']*)["\']', page)
        assert match, "deepzoom-viewer.js is not on the page"
        assert requests.get(f"{server.base_url}{match.group(1)}").status_code == 200

    def test_no_tile_asset_comes_from_a_cdn(self, page):
        _local, external = _assets(page)
        seadragon = [u for u in external if "seadragon" in u.lower()]
        assert not seadragon, f"OpenSeadragon is loaded externally: {seadragon}"


class TestExternalDependenciesAreTheKnownOnes:
    def test_no_new_external_host_appears_at_runtime(self, page):
        """
        Rendered output, not the template: a Jinja conditional or an injected
        script could add a host that no static scan of the source would see.
        """
        _local, external = _assets(page)
        hosts = {u.split("//", 1)[1].split("/", 1)[0] for u in external}
        unexpected = hosts - KNOWN_EXTERNAL
        assert not unexpected, (
            f"The rendered page loads from unlisted host(s): {sorted(unexpected)}. "
            f"Vendor them (scripts/vendor_assets.py) or document them in "
            f"docs/deployment/air_gap.md.")

    def test_the_rendered_page_loads_nothing_external(self, page):
        """
        The claim docs/deployment/air_gap.md now makes, checked against a real
        rendered page rather than the template source.

        This assertion used to run the other way: it required jQuery to still
        come from a CDN, so that the doc could not go stale while it listed
        jQuery as a blocker. Both directions guard the same thing — the page and
        the page's documentation agreeing — and the page has since caught up.
        """
        _local, external = _assets(page)
        hosts = sorted({u.split("//", 1)[1].split("/", 1)[0] for u in external})
        assert not hosts, (
            f"The annotation page loads from {hosts}. Either vendor it "
            f"(scripts/vendor_assets.py) or stop docs/deployment/air_gap.md "
            f"claiming offline deployment is supported.")


class TestTheLoginPageIsSelfContained:
    def test_no_third_party_asset_on_the_login_page(self, server):
        """
        The login page is where credentials are typed. It carried a favicon
        from colorlib.com, the site its template was adapted from.
        """
        html = requests.get(f"{server.base_url}/").text
        _local, external = _assets(html)
        hosts = {u.split("//", 1)[1].split("/", 1)[0] for u in external}
        assert "colorlib.com" not in hosts
        assert not (hosts - KNOWN_EXTERNAL), (
            f"unexpected third-party host(s) on the login page: "
            f"{sorted(hosts - KNOWN_EXTERNAL)}")
