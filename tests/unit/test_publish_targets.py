"""Mocked tests for the HuggingFace and Zenodo publishing targets.

Neither target touches the network here: the HF SDK is injected as fake modules and
Zenodo's REST calls are monkeypatched on ``requests``. This verifies the adapters
call the right APIs with the right payloads and surface DOIs/URLs correctly.
"""

import sys
import types

import pytest

from potato.publish.bundle import PublishBundle
from potato.publish.config import DatasetMetadata


def _bundle():
    return PublishBundle(
        splits={"annotations": [{"instance_id": "i0", "user_id": "A1",
                                 "sentiment.pos": "pos"}],
                "gold": [{"instance_id": "i0", "n_annotators": 1,
                          "sentiment.pos": "pos"}]},
        schemas=[{"annotation_type": "radio", "name": "sentiment",
                  "description": "d", "labels": ["pos", "neg"]}],
        metadata=DatasetMetadata.from_dict({
            "pretty_name": "My DS", "license": "cc-by-4.0", "keywords": ["nlp"],
            "authors": [{"name": "Ada", "orcid": "0000-0001"}]}),
        config={},
        stats={},
        card_markdown="# My DS\n",
    )


class TestHuggingFace:
    def test_push_calls_sdk(self, monkeypatch):
        calls = {}

        class FakeDataset:
            @staticmethod
            def from_list(rows):
                return {"rows": rows}

        class FakeDatasetDict(dict):
            def push_to_hub(self, repo_id, token=None, private=False,
                            commit_message=""):
                calls["push"] = {"repo_id": repo_id, "private": private,
                                 "splits": list(self.keys())}

        class FakeCard:
            def __init__(self, content):
                calls["card_content"] = content

            def push_to_hub(self, repo_id, token=None):
                calls["card_repo"] = repo_id

        datasets_mod = types.ModuleType("datasets")
        datasets_mod.Dataset = FakeDataset
        datasets_mod.DatasetDict = FakeDatasetDict
        hub_mod = types.ModuleType("huggingface_hub")
        hub_mod.DatasetCard = FakeCard
        monkeypatch.setitem(sys.modules, "datasets", datasets_mod)
        monkeypatch.setitem(sys.modules, "huggingface_hub", hub_mod)

        from potato.publish.targets import push_to_huggingface
        result = push_to_huggingface(_bundle(), "org/my-ds", token="hf_x",
                                     private=True)

        assert calls["push"]["repo_id"] == "org/my-ds"
        assert calls["push"]["private"] is True
        assert set(calls["push"]["splits"]) == {"annotations", "gold"}
        assert calls["card_repo"] == "org/my-ds"
        assert result["url"] == "https://huggingface.co/datasets/org/my-ds"

    def test_bad_repo_id_rejected(self):
        from potato.publish.targets import push_to_huggingface
        with pytest.raises(ValueError):
            push_to_huggingface(_bundle(), "no-slash-here")


class TestZenodo:
    def _fake_requests(self, monkeypatch, published=False):
        state = {"posts": [], "puts": []}

        class Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        def fake_post(url, json=None, timeout=None, params=None):
            state["posts"].append(url)
            if url.endswith("/actions/publish"):
                return Resp({"doi": "10.5072/zenodo.123",
                             "links": {"html": "https://sandbox.zenodo.org/record/123"}})
            # create deposition
            return Resp({"id": 123,
                         "links": {"bucket": "https://sandbox.zenodo.org/api/files/abc",
                                   "html": "https://sandbox.zenodo.org/deposit/123"},
                         "metadata": {"prereserve_doi": {"doi": "10.5072/zenodo.123"}}})

        def fake_put(url, data=None, json=None, timeout=None, params=None):
            state["puts"].append(url)
            return Resp({"id": 123})

        import requests
        monkeypatch.setattr(requests, "post", fake_post)
        monkeypatch.setattr(requests, "put", fake_put)
        return state

    def test_draft_deposition(self, monkeypatch):
        self._fake_requests(monkeypatch)
        from potato.publish.targets import deposit_to_zenodo
        result = deposit_to_zenodo(_bundle(), token="zx", sandbox=True,
                                   publish=False)
        assert result["deposition_id"] == 123
        assert result["published"] is False
        assert result["sandbox"] is True

    def test_publish_returns_doi(self, monkeypatch):
        state = self._fake_requests(monkeypatch, published=True)
        from potato.publish.targets import deposit_to_zenodo
        result = deposit_to_zenodo(_bundle(), token="zx", sandbox=True,
                                   publish=True)
        assert result["published"] is True
        assert result["doi"] == "10.5072/zenodo.123"
        # An archive was uploaded (a PUT to the bucket) and metadata set.
        assert any("/api/files/" in u for u in state["puts"])
        assert any(u.endswith("/actions/publish") for u in state["posts"])

    def test_missing_token_errors(self, monkeypatch):
        monkeypatch.delenv("ZENODO_TOKEN", raising=False)
        from potato.publish.targets import deposit_to_zenodo
        with pytest.raises(ValueError):
            deposit_to_zenodo(_bundle(), token=None)
