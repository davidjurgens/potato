"""Curation: an argument that was ignored, a key file that was not written,
and a cluster that would not say why it had no name.

Round 38 opened by praising the note `/admin/catalog/api/duplicates` returns
on a text-only project -- "This is NOT a finding of zero duplicates." All three
fixes here are that same note applied where it was missing: a zero, a blank or
a default that the caller would otherwise read as a measurement.

1. `POST /api/search` reads `top_k`. Sending `k` -- the name most callers reach
   for -- returned the default ten, which reads as an index that cannot
   discriminate rather than an argument that was thrown away.

2. `RBACManager.has_valid_admin_key` returned False on a missing header BEFORE
   calling `get_admin_api_key`, which is the function that generates
   {task_dir}/admin_api_key.txt. So an unauthenticated request was told it
   needed a key while the file holding that key did not exist -- and presenting
   a WRONG key created it. Anyone whose first admin request went to a route
   gated this way had nowhere to read the answer.

3. A cluster with no axial code arrived as `topic-3` with an empty description
   whether no endpoint was configured, the caller asked for clustering only, or
   the model returned nothing. Three situations, one blank.
"""

import json
import os

import pytest

from potato.curation.discovery import DiscoveredCluster, discover_failure_modes


# ----------------------------------------------------------------------
# 1. `k` is read, and an argument that is not read is reported
# ----------------------------------------------------------------------

class _Index:
    """Six vectors in two obvious groups, so top_k is the only thing that can
    decide how many come back."""

    def __init__(self, n=6):
        self._v = {f"i{j}": [1.0 if j < n // 2 else 0.0,
                             0.0 if j < n // 2 else 1.0,
                             j * 0.001]
                   for j in range(n)}

    def ids(self):
        return list(self._v)

    def get(self, iid):
        return self._v.get(iid)


def _search(client, **body):
    return client.post("/admin/catalog/api/search", json=body,
                       headers=_key_header())


def test_top_k_is_still_read():
    """The documented spelling, pinned so the alias cannot displace it."""
    client, mgr = _seeded_client()
    r = _search(client, query="delay", top_k=3)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert len(r.get_json()["results"]) == 3


def test_the_explicit_name_wins_when_both_are_sent():
    """A caller who sends both meant the one this endpoint documents."""
    client, mgr = _seeded_client()
    r = _search(client, query="delay", top_k=2, k=5)
    assert len(r.get_json()["results"]) == 2


def test_an_argument_the_endpoint_does_not_read_is_rejected():
    """The behaviour, driven through the real route."""
    client, _ = _seeded_client()
    r = _search(client, query="train delay", limit=4)
    assert r.status_code == 400, r.get_data(as_text=True)
    payload = r.get_json()
    assert "limit" in payload["error"]
    assert "top_k" in payload["accepted"], payload


def test_k_actually_limits_the_result_count():
    client, _ = _seeded_client()
    default = _search(client, query="delay").get_json()
    four = _search(client, query="delay", k=4).get_json()
    assert len(default["results"]) == len(_TEXTS), (
        "fixture: the default should return everything above threshold, so "
        "that a smaller k is visibly different")
    assert len(four["results"]) == 4, (
        f"`k` was ignored: got {len(four['results'])} results, the same as the "
        f"default {len(default['results'])}")


# ----------------------------------------------------------------------
# 2. The key file exists by the time you are told you need it
# ----------------------------------------------------------------------

def test_a_rejected_request_still_leaves_the_key_on_disk(tmp_path=None):
    from potato.server_utils import admin_key
    from potato.server_utils.rbac import RBACManager
    from tests.helpers.test_utils import create_test_directory

    task_dir = create_test_directory("audit38_key")
    key_path = os.path.join(task_dir, "admin_api_key.txt")
    if os.path.exists(key_path):
        os.remove(key_path)
    admin_key._generated_admin_api_key = None

    class _Req:
        headers = {}
        args = {}
        cookies = {}

        def get_json(self, *a, **kw):
            return None

    manager = RBACManager({"task_dir": task_dir})
    allowed = manager.has_valid_admin_key(_Req(), {})

    assert allowed is False, "a request with no key must still be refused"
    assert os.path.exists(key_path), (
        "the request was told it needed an admin key and the file that holds "
        f"the key was not written: {key_path}")
    with open(key_path, encoding="utf-8") as fh:
        assert fh.read().strip(), "the key file is empty"


def test_the_right_key_still_passes_and_a_wrong_one_still_fails():
    from potato.server_utils import admin_key
    from potato.server_utils.rbac import RBACManager
    from tests.helpers.test_utils import create_test_directory

    task_dir = create_test_directory("audit38_key_roundtrip")
    admin_key._generated_admin_api_key = None
    config = {"task_dir": task_dir, "admin_api_key": "s3cret"}
    manager = RBACManager(config)

    class _Req:
        def __init__(self, key):
            self.headers = {"X-API-Key": key} if key else {}
            self.args = {}
            self.cookies = {}

        def get_json(self, *a, **kw):
            return None

    assert manager.has_valid_admin_key(_Req("s3cret"), {}) is True
    assert manager.has_valid_admin_key(_Req("wrong"), {}) is False


# ----------------------------------------------------------------------
# 3. An unnamed cluster says why
# ----------------------------------------------------------------------

class TestAnUnnamedClusterSaysWhy:

    def _clusters(self, llm):
        return discover_failure_modes(
            _Index(), lambda i: f"complaint text for {i}", k=2, llm=llm)

    def test_no_endpoint_is_named_as_the_reason(self):
        clusters = self._clusters(llm=None)
        assert clusters, "the fixture produced no clusters"
        for c in clusters:
            assert c.suggested_label == ""
            assert c.suggested_description, (
                "an unnamed cluster came back with a blank description, which "
                "reads as 'this cluster has nothing to say about it'")
            assert "ai_support" in c.suggested_description, (
                c.suggested_description)

    def test_a_silent_model_is_named_as_a_different_reason(self):
        """"No endpoint" and "the endpoint said nothing" are different
        problems with different fixes, so they must not share a sentence."""
        class _Mute:
            def query(self, *a, **kw):
                return "{}"

        clusters = self._clusters(llm=_Mute())
        assert clusters
        reasons = {c.suggested_description for c in clusters}
        assert all("did not return one" in r for r in reasons), reasons
        assert all("ai_support" not in r for r in reasons), reasons

    def test_a_named_cluster_keeps_the_model_s_description(self):
        """The reason text must not overwrite a real answer."""
        class _Namer:
            def query(self, *a, **kw):
                return json.dumps({"label": "missing handoff",
                                   "description": "The agent never escalated."})

        clusters = self._clusters(llm=_Namer())
        assert clusters
        for c in clusters:
            assert c.suggested_label == "missing handoff"
            assert c.suggested_description == "The agent never escalated."


# ----------------------------------------------------------------------
# Harness
# ----------------------------------------------------------------------

_TEXTS = [
    "my train never showed up and nobody told us anything",
    "the train was cancelled with no announcement at all",
    "the parcel arrived crushed and the box was open",
    "my package turned up damaged and partly unsealed",
    "the agent hung up on me halfway through the call",
    "the representative disconnected me mid conversation",
]


def _key_header():
    return {"X-API-Key": "s3cret"}


def _client():
    """A Flask app with the curation blueprint and a real manager over six
    short complaint texts."""
    import flask

    from potato.curation import manager as manager_mod
    from potato.curation.routes import curation_bp
    from tests.helpers.test_utils import create_test_directory

    task_dir = create_test_directory("audit38_search")
    config = {
        "task_dir": task_dir,
        "output_annotation_dir": os.path.join(task_dir, "out"),
        "admin_api_key": "s3cret",
        "curation": {"enabled": True},
        "annotation_schemes": [],
    }

    from potato.server_utils.rbac import init_rbac_manager

    init_rbac_manager(config)
    mgr = manager_mod.init_curation_manager(config)
    assert mgr is not None, "curation manager did not start"

    # A deterministic stand-in for the embedder and the item store: the route
    # under test is about argument handling, not about embedding quality.
    mgr.embedder = _Embedder()
    mgr._item_text = lambda iid: _TEXTS[int(iid[1:])]

    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(curation_bp)
    return app.test_client(), mgr


def _seeded_client():
    """A client whose index already holds the six complaint texts."""
    client, mgr = _client()
    # Straight into the index: build_index reads the ItemStateManager, and
    # these tests are about the route's argument handling, not item loading.
    for n, text in enumerate(_TEXTS):
        mgr.index.add(f"i{n}", mgr.embedder.embed(text))
    assert len(mgr.index.ids()) == len(_TEXTS)
    return client, mgr


class _Embedder:
    """Bag-of-words cosine, so 'delay' really is nearer the train pair."""

    def embed(self, text):
        words = sorted(set(str(text).lower().split()))
        vec = [0.0] * 64
        for w in words:
            vec[hash(w) % 64] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_many(self, texts):
        return [self.embed(t) for t in texts]
