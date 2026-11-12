"""
Server integration test for semantic curation: build an index, similarity
search, save + resolve a slice, and curate a slice into a dataset.

A fake 2-D embedder is injected into the in-process manager so the test is fast
and hermetic (no sentence-transformers model load).
"""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


# Deterministic 2-D embeddings keyed by substring, so item texts map to a space.
def _fake_embed(text):
    t = (text or "").lower()
    if "cat" in t or "feline" in t:
        return [1.0, 0.0]
    if "dog" in t or "puppy" in t:
        return [0.0, 1.0]
    return [0.5, 0.5]


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    schemes = [{"annotation_type": "radio", "name": "ok",
                "description": "ok?", "labels": ["yes", "no"]}]
    extra = {"curation": {"enabled": True}, "datasets": {"enabled": True, "storage": "file"}}
    with TestConfigManager(
        "curation_search", schemes,
        additional_config=extra, admin_api_key="test-admin-api-key",
    ) as test_config:
        server = FlaskTestServer(port=9065, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        # Inject the fake embedder into the in-process curation singleton.
        from potato.curation.manager import get_curation_manager
        from potato.curation.embeddings import Embedder
        mgr = get_curation_manager()
        assert mgr is not None
        mgr.embedder = Embedder(embed_fn=_fake_embed)
        # Add a few items with cat/dog texts to embed.
        from potato.item_state_management import get_item_state_manager
        ism = get_item_state_manager()
        for iid, text in [("c1", "a fluffy cat"), ("c2", "a feline friend"),
                          ("d1", "a loyal dog"), ("d2", "a playful puppy")]:
            ism.add_item(iid, {"id": iid, "text": text, "metadata": {"species": "cat" if iid.startswith("c") else "dog"}})
        request.cls.server = server
        yield server
        server.stop()


class TestCurationSearch:
    def _admin(self):
        s = requests.Session()
        s.headers.update({"X-API-Key": self.server.admin_api_key})
        return s, self.server.base_url

    def test_build_and_search(self):
        s, base = self._admin()
        r = s.post(f"{base}/admin/catalog/api/build")
        assert r.status_code == 200 and r.json()["indexed"] >= 4

        r = s.post(f"{base}/admin/catalog/api/search",
                   json={"query": "kitten cat", "top_k": 2, "threshold": 0.5})
        assert r.status_code == 200, r.text
        ids = [h["instance_id"] for h in r.json()["results"]]
        assert set(ids) <= {"c1", "c2"}    # only cat-space items above threshold
        assert ids                          # and at least one hit

    def test_anchor_search_excludes_self(self):
        s, base = self._admin()
        s.post(f"{base}/admin/catalog/api/build")
        r = s.post(f"{base}/admin/catalog/api/search",
                   json={"anchor_id": "c1", "top_k": 5, "threshold": 0.5})
        ids = [h["instance_id"] for h in r.json()["results"]]
        assert "c1" not in ids and "c2" in ids

    def test_slice_save_resolve_and_to_dataset(self):
        s, base = self._admin()
        s.post(f"{base}/admin/catalog/api/build")
        # Save a semantic slice for cat-like items. Threshold 0.9 excludes the
        # harness's neutral default items (cosine ~0.71) so only true cats match.
        r = s.post(f"{base}/admin/catalog/api/slices",
                   json={"name": "cats", "query": "cat", "threshold": 0.9})
        assert r.status_code == 201

        r = s.get(f"{base}/admin/catalog/api/slices/cats/resolve")
        assert r.status_code == 200
        assert set(r.json()["instance_ids"]) <= {"c1", "c2"}

        # Curate the slice into a dataset.
        r = s.post(f"{base}/admin/catalog/api/slices/cats/to_dataset",
                   json={"dataset": "cat-traces"})
        assert r.status_code == 201, r.text
        assert r.json()["imported"] >= 1
        # The dataset now exists with the curated examples.
        ds = s.get(f"{base}/datasets/api/datasets/cat-traces")
        assert ds.status_code == 200 and ds.json()["versions"]

    def test_search_requires_admin(self):
        base = self.server.base_url
        r = requests.post(f"{base}/admin/catalog/api/search", json={"query": "x"})
        assert r.status_code in (401, 403)
