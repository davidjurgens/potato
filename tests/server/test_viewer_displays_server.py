"""Viewer displays against a running server: the media route's range requests
(igv.js reads indexed BAM/VCF/FASTA a slice at a time), gzip files served as
their own bytes, the rendered page, and the Mol* bundle requirement."""

import os
import shutil
import subprocess
import sys

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES = os.path.join(REPO, "examples", "advanced")


def _copy_example(name, tag):
    work = os.path.join(create_test_directory(tag), name)
    shutil.copytree(os.path.join(EXAMPLES, name), work,
                    ignore=shutil.ignore_patterns("annotation_output", "*.sqlite*", ".potato_cache"))
    return work


@pytest.fixture(scope="class")
def variant_server():
    work = _copy_example("variant-review", "viewer_server_variants")
    server = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not server.start():
        pytest.fail("could not start the variant-review example")
    server.work = work
    yield server
    server.stop()


def _login(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register", data={"action": "signup", "email": user, "pass": "pass"})
    s.post(f"{server.base_url}/auth", data={"action": "login", "email": user, "pass": "pass"})
    return s


def _file(server, rel):
    with open(os.path.join(server.work, "media", rel), "rb") as f:
        return f.read()


class TestMediaRanges:
    @pytest.mark.parametrize("rel", ["calls/sample1.vcf.gz", "reads/sample1.bam",
                                     "genome/synthetic.fa", "calls/sample1.vcf.gz.tbi"])
    def test_range_request_returns_exactly_those_bytes(self, variant_server, rel):
        data = _file(variant_server, rel)
        s = _login(variant_server, "ranges")
        r = s.get(f"{variant_server.base_url}/media/{rel}", headers={"Range": "bytes=10-49"})
        assert r.status_code == 206
        assert r.headers["Content-Range"] == f"bytes 10-49/{len(data)}"
        assert r.content == data[10:50]
        tail = s.get(f"{variant_server.base_url}/media/{rel}", headers={"Range": "bytes=-12"})
        assert tail.status_code == 206 and tail.content == data[-12:]

    def test_a_plain_request_advertises_ranges(self, variant_server):
        r = _login(variant_server, "ranges2").get(f"{variant_server.base_url}/media/genome/synthetic.fa.fai")
        assert r.status_code == 200 and r.headers.get("Accept-Ranges") == "bytes"

    def test_gzip_files_are_served_as_their_own_bytes(self, variant_server):
        """A bgzipped VCF read through its .tbi needs the compressed bytes.
        With `Content-Encoding: gzip` the browser inflated them first and every
        index offset pointed into the wrong data."""
        rel = "calls/sample1.vcf.gz"
        s = _login(variant_server, "gzip")
        for headers in ({}, {"Range": "bytes=0-27"}):
            r = s.get(f"{variant_server.base_url}/media/{rel}", headers=headers,
                      stream=True)
            assert "Content-Encoding" not in r.headers, r.headers
            raw = r.raw.read()
            assert raw[:2] == b"\x1f\x8b"         # still gzip on the wire, not inflated
            r.close()

    def test_unsatisfiable_range(self, variant_server):
        r = _login(variant_server, "ranges3").get(
            f"{variant_server.base_url}/media/genome/synthetic.fa.fai",
            headers={"Range": "bytes=100000-100010"})
        assert r.status_code == 416

    def test_media_still_refuses_traversal(self, variant_server):
        r = _login(variant_server, "ranges4").get(
            f"{variant_server.base_url}/media/..%2F..%2Fconfig.yaml", headers={"Range": "bytes=0-10"})
        assert r.status_code in (403, 404)


    def test_page_carries_the_viewer_and_loads_its_scripts(self, variant_server):
        s = _login(variant_server, "page")
        page = s.get(f"{variant_server.base_url}/annotate").text
        assert 'data-viewer-kind="genome_locus"' in page
        assert "viewers/viewer-framework.js" in page and "viewers/genome-locus.js" in page
        assert 'data-annotation-type="viewer_selection"' in page
        lib = s.get(f"{variant_server.base_url}/static/vendor/igv-3.8.9/igv.min.js")
        assert lib.status_code == 200 and len(lib.content) > 1_000_000


def _validate(config_path, vendor_dir):
    env = dict(os.environ, POTATO_VENDOR_DIR=vendor_dir, PYTHONPATH=REPO)
    return subprocess.run([sys.executable, os.path.join(REPO, "potato", "flask_server.py"),
                           "validate", config_path], capture_output=True, text=True, env=env,
                          cwd=REPO, timeout=120)


class TestMolstarBundle:
    @pytest.fixture(scope="class")
    def molstar_config(self):
        import yaml
        work = _copy_example("protein-binding-site", "viewer_server_molstar")
        path = os.path.join(work, "config.yaml")
        with open(path) as f:
            config = yaml.safe_load(f)
        config["instance_display"]["fields"][1]["display_options"]["engine"] = "molstar"
        with open(path, "w") as f:
            yaml.safe_dump(config, f)
        return path

    def test_validate_names_the_fetch_command_when_missing(self, molstar_config):
        result = _validate(molstar_config, create_test_directory("viewer_vendor_empty"))
        assert result.returncode != 0
        assert "potato vendor fetch molstar" in result.stdout + result.stderr

    def test_fetch_then_validate_and_serve(self, molstar_config, monkeypatch):
        vendor = create_test_directory("viewer_vendor_molstar")
        env = dict(os.environ, POTATO_VENDOR_DIR=vendor, PYTHONPATH=REPO)
        fetch = subprocess.run([sys.executable, "-m", "potato.vendoring.cli", "fetch", "molstar"],
                               capture_output=True, text=True, env=env, cwd=REPO, timeout=300)
        if fetch.returncode != 0:
            pytest.skip(f"could not fetch Mol* (offline?): {fetch.stderr.strip()[-200:]}")
        result = _validate(molstar_config, vendor)
        assert result.returncode == 0, result.stdout + result.stderr

        monkeypatch.setenv("POTATO_VENDOR_DIR", vendor)
        server = FlaskTestServer(config_file=molstar_config)
        if not server.start():
            pytest.fail("could not start the Mol* config")
        try:
            s = _login(server, "molstar")
            page = s.get(f"{server.base_url}/annotate").text
            assert "/vendor-fetched/molstar-5.12.0/molstar.js" in page
            js = s.get(f"{server.base_url}/vendor-fetched/molstar-5.12.0/molstar.js")
            assert js.status_code == 200 and len(js.content) > 4_000_000
        finally:
            server.stop()
