"""Regression tests for the 2.11.1 pre-release audit findings.

Each class names the finding it guards. They are unit tests: no CLIP model,
no server; the behaviour under test is the resolution, gating and wording
logic around those.
"""

import os
import pickle
from types import SimpleNamespace

import pytest

from tests.helpers.test_utils import create_test_directory


class _Req:
    def __init__(self, addr, headers=None):
        self.remote_addr = addr
        self.headers = headers or {}


# --------------------------------------------------------------- C1 / C3

class TestImageReferenceResolution:
    """C1: /media/... references must reach the file in media_directory."""

    @pytest.fixture
    def project(self):
        root = create_test_directory("audit91_media")
        media = os.path.join(root, "media")
        os.makedirs(media, exist_ok=True)
        path = os.path.join(media, "red.png")
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        return root, media, path

    def test_media_url_resolves_under_media_dir(self, project):
        from potato.vision_features import ImageEmbeddingVectorizer
        root, media, path = project
        vec = ImageEmbeddingVectorizer(image_root=root, media_dir=media)
        assert vec._resolve("/media/red.png") == __import__("pathlib").Path(path)

    def test_image_root_at_the_media_dir_does_not_double_join(self, project):
        from potato.vision_features import ImageEmbeddingVectorizer
        root, media, path = project
        vec = ImageEmbeddingVectorizer(image_root=media)
        assert vec._resolve("/media/red.png") is not None

    def test_remote_reference_never_resolves(self, project):
        from potato.vision_features import ImageEmbeddingVectorizer
        root, media, _ = project
        vec = ImageEmbeddingVectorizer(image_root=root, media_dir=media)
        assert vec._resolve("https://example.com/red.png") is None

    def test_active_learning_vectorizer_gets_the_project_roots(self, project):
        from potato.active_learning_manager import (ActiveLearningConfig,
                                                    ActiveLearningManager)
        root, media, _ = project
        cfg = ActiveLearningConfig(
            vectorizer_name="image",
            project_config={"task_dir": root, "media_directory": "media"})
        manager = ActiveLearningManager.__new__(ActiveLearningManager)
        manager.config = cfg
        vec = manager._create_vectorizer()
        assert vec.image_root == root
        assert os.path.abspath(vec.media_dir) == os.path.abspath(media)
        assert vec._resolve("/media/red.png") is not None


class TestImageVectorizerPickle:
    """C3: the CLIP weights must not be pickled into every saved model."""

    def test_model_is_dropped_from_the_pickle(self):
        from potato.vision_features import ImageEmbeddingVectorizer
        vec = ImageEmbeddingVectorizer()
        vec._model = bytearray(10_000_000)  # stands in for the weights
        restored = pickle.loads(pickle.dumps(vec))
        assert restored._model is None
        assert len(pickle.dumps(vec)) < 10_000
        assert vec._model is not None  # the live object keeps its model


# --------------------------------------------------------------- C2

class TestDistillDue:
    """C2: growth is measured in accepted labels at both ends."""

    def _engine(self, n_accepted, prev):
        store = SimpleNamespace(
            resolved=lambda schema, status: [object()] * n_accepted,
            kv_get=lambda key, default: {"s": prev} if prev else {})
        cfg = SimpleNamespace(feature=lambda name: True,
                              distill={"min_labels": 10, "every": 2.0})
        return SimpleNamespace(store=store, cfg=cfg)

    def test_not_due_when_accepted_labels_have_not_doubled(self):
        from potato.labeling_engine import distill
        scheme = SimpleNamespace(name="s")
        # 21 accepted when it last trained, only 10 of them usable rows.
        engine = self._engine(21, {"n_train": 10, "n_accepted": 21})
        assert distill.due(engine, scheme) is False

    def test_due_once_accepted_labels_double(self):
        from potato.labeling_engine import distill
        scheme = SimpleNamespace(name="s")
        engine = self._engine(42, {"n_train": 10, "n_accepted": 21})
        assert distill.due(engine, scheme) is True


# --------------------------------------------------------------- B2 / C4

class TestModalityDetection:
    """B2: a text item that carries a remote image_url is a text item."""

    def test_text_rows_with_remote_images_are_text(self):
        from potato.training.dataset import detect_modality
        rows = [{"text": "I loved this film", "media": "https://x.org/%d.jpg" % i}
                for i in range(10)]
        assert detect_modality([{"annotation_type": "radio"}], rows) == "text"

    def test_rows_that_are_only_a_remote_image_are_images(self):
        from potato.training.dataset import detect_modality
        rows = [{"text": "https://x.org/%d.jpg" % i, "media": "https://x.org/%d.jpg" % i}
                for i in range(10)]
        assert detect_modality([{"annotation_type": "radio"}], rows) == "image"

    def test_local_images_are_images(self):
        from potato.training.dataset import detect_modality
        rows = [{"text": "caption", "media": "ab/%d.png" % i} for i in range(10)]
        assert detect_modality([{"annotation_type": "radio"}], rows) == "image"


class TestRemoteImagesAreNotPredicted:
    """C4: a remote URL must not be read as a local file and predicted."""

    def test_resolve_media_leaves_a_url_alone(self):
        from potato.training.base import BundleRef
        bundle = BundleRef(root="/bundle", manifest={})
        url = "https://example.com/a.png"
        assert bundle.resolve_media(url) == url
        assert bundle.resolve_media("ab/a.png") == os.path.join("/bundle", "media", "ab/a.png")

    def test_readable_media_checks_the_file(self):
        from potato.training.trainers.sklearn_text import SklearnTextTrainer
        root = create_test_directory("audit91_readable")
        path = os.path.join(root, "a.png")
        open(path, "wb").close()
        assert SklearnTextTrainer._readable_media(path, check_file=True)
        assert not SklearnTextTrainer._readable_media(
            os.path.join(root, "missing.png"), check_file=True)
        assert not SklearnTextTrainer._readable_media(
            "https://example.com/a.png", check_file=True)


# --------------------------------------------------------------- B1

class TestWritebackPrelabelsAreShown:
    """B1: write-back prelabels render without a pre_annotation block."""

    def _config(self, **writeback):
        return {"model_training": {"enabled": True, "writeback": writeback},
                "annotation_schemes": []}

    def test_writeback_turns_on_the_quality_control_manager(self):
        from potato.quality_control import quality_control_needed
        assert quality_control_needed(self._config(schemas=["sentiment"]))
        assert not quality_control_needed(self._config(schemas=[]))
        assert not quality_control_needed({"model_training": {
            "enabled": False, "writeback": {"schemas": ["sentiment"]}}})

    def test_prelabels_are_read_from_the_writeback_field(self):
        from potato.quality_control import QualityControlManager
        root = create_test_directory("audit91_qc")
        qc = QualityControlManager(self._config(schemas=["s"], field="model_out"), root)
        data = {"text": "x", "model_out": {"s": {"label": "neutral", "confidence": 0.8}}}
        assert qc.extract_pre_annotations("i1", data) == data["model_out"]

    def test_an_explicit_pre_annotation_block_wins(self):
        from potato.quality_control import QualityControlManager
        root = create_test_directory("audit91_qc2")
        config = self._config(schemas=["s"], field="model_out")
        config["pre_annotation"] = {"enabled": True, "field": "other"}
        qc = QualityControlManager(config, root)
        assert qc.qc_config.pre_annotation_field == "other"


# --------------------------------------------------------------- A1 / A3

class TestDebugBypassNeedsALocalRequest:
    """A1: a loopback bind does not excuse a forwarded request."""

    @pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded"])
    def test_forwarded_request_on_a_loopback_bind_is_refused(self, header):
        from potato.server_utils.admin_key import debug_grants_admin
        cfg = {"debug": True, "host": "127.0.0.1"}
        assert debug_grants_admin(cfg, _Req("127.0.0.1", {header: "203.0.113.9"})) is False

    def test_local_request_on_a_loopback_bind_is_granted(self):
        from potato.server_utils.admin_key import debug_grants_admin
        assert debug_grants_admin({"debug": True, "host": "127.0.0.1"},
                                  _Req("127.0.0.1")) is True


class TestDebugMediaEndpoints:
    """A3: under debug, a URL-fetch endpoint answers anonymously only locally."""

    @pytest.fixture
    def endpoint(self):
        from flask import Flask
        import potato.routes as routes
        app = Flask(__name__)
        app.secret_key = "test"

        @app.route("/fetch")
        @routes.media_login_required
        def fetch():
            return "ok"

        old = dict(routes.config)
        routes.config["debug"] = True
        yield app.test_client()
        routes.config.clear()
        routes.config.update(old)

    def test_local_anonymous_request_is_served(self, endpoint):
        assert endpoint.get("/fetch", environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 200

    def test_remote_anonymous_request_is_refused(self, endpoint):
        assert endpoint.get("/fetch", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 401

    def test_forwarded_anonymous_request_is_refused(self, endpoint):
        r = endpoint.get("/fetch", environ_base={"REMOTE_ADDR": "127.0.0.1"},
                         headers={"X-Forwarded-For": "203.0.113.9"})
        assert r.status_code == 401


# --------------------------------------------------------------- D1 / D2

class TestAgentDisplayLengths:
    """D1: a string screenshot_max_height must not crash the display."""

    @pytest.mark.parametrize("value", ["600px", "600", "50vh", 600])
    def test_web_agent_trace_renders(self, value):
        from potato.server_utils.displays.web_agent_trace_display import WebAgentTraceDisplay
        html = WebAgentTraceDisplay().render(
            {"key": "t", "display_options": {"screenshot_max_height": value}},
            {"steps": [{"screenshot_url": "/media/a.png", "action_type": "click"}]})
        assert "step-details-panel" in html
        assert "pxpx" not in html

    @pytest.mark.parametrize("value,expected", [("600px", "600"), (600, "600"), ("50vh", "650")])
    def test_live_agent_viewbox_is_numeric(self, value, expected):
        import re
        from potato.server_utils.displays.live_agent_display import LiveAgentDisplay
        html = LiveAgentDisplay().render(
            {"key": "t", "display_options": {"screenshot_max_height": value}}, {})
        box = re.search(r'viewBox="0 0 (\S+) (\S+)"', html)
        assert box and box.group(2) == expected
        assert all(part.isdigit() for part in box.groups())


# --------------------------------------------------------------- B3 / retract

class _Items:
    def __init__(self, ids):
        self.data = {i: {} for i in ids}

    def set_prediction(self, iid, schema, payload, field="predictions"):
        if iid not in self.data:
            return False
        self.data[iid].setdefault(field, {})[schema] = payload
        return True

    def clear_prediction(self, iid, schema, field="predictions"):
        preds = self.data.get(iid, {}).get(field, {})
        return preds.pop(schema, None) is not None


class TestPrelabelsAcrossRuns:
    """B3: an older run's prelabel comes off an item a newer run trained on."""

    def _config(self):
        root = create_test_directory("audit91_runs")
        return {"task_dir": root, "output_annotation_dir": "out",
                "annotation_task_name": "audit91",
                "model_training": {"enabled": True,
                                   "writeback": {"schemas": ["s"]}}}

    def test_rehydrate_skips_items_a_later_run_trained_on(self, monkeypatch):
        from potato.training import store, writeback
        config = self._config()
        monkeypatch.setattr(store, "load_predictions", lambda cfg, run_id=None: [
            {"instance_id": "a", "schema_name": "s", "run_id": "r1",
             "payload": {"label": "x"}, "confidence": 0.9},
            {"instance_id": "b", "schema_name": "s", "run_id": "r1",
             "payload": {"label": "y"}, "confidence": 0.9}])
        monkeypatch.setattr(store, "all_training_split_ids", lambda cfg: {"a"})
        monkeypatch.setattr(writeback, "_rejected_keys", lambda cfg: set())
        items = _Items(["a", "b"])
        assert writeback.rehydrate_predictions(config, items) == 1
        assert "predictions" not in items.data["a"]
        assert items.data["b"]["predictions"]["s"]["label"] == "y"

    def test_clear_published_takes_prelabels_off(self):
        from potato.training.writeback import clear_published
        items = _Items(["a"])
        items.set_prediction("a", "s", {"label": "x"})
        n = clear_published(self._config(),
                            [{"instance_id": "a", "schema_name": "s"}], items)
        assert n == 1 and items.data["a"]["predictions"] == {}



# --------------------------------------------------------------- D3

class TestSsoResets:
    """D3: an SSO identity's password reset is refused, not a 500."""

    def _backend(self):
        from potato.auth_backends.oauth_backend import OAuthBackend
        backend = OAuthBackend.__new__(OAuthBackend)
        backend.users = {"sso-user": {"provider": "google"}}
        backend._local = SimpleNamespace(
            users={"local-user": "hash"},
            is_valid_username=lambda u: u == "local-user")
        return backend

    def test_only_local_accounts_have_settable_passwords(self):
        backend = self._backend()
        assert backend.has_settable_password("local-user")
        assert not backend.has_settable_password("sso-user")

    def test_no_reset_token_for_an_sso_identity(self):
        import threading
        from potato.authentication import UserAuthenticator
        auth = UserAuthenticator.__new__(UserAuthenticator)
        backend = self._backend()
        backend.is_valid_username = lambda u: u in ("sso-user", "local-user")
        auth.auth_backend = backend
        auth._token_lock = threading.Lock()
        auth._reset_tokens = {}
        assert auth.create_reset_token("sso-user") is None
        assert auth.create_reset_token("local-user") is not None
        assert auth.update_password("sso-user", "new-pass") is False


# --------------------------------------------------------------- C7 / wording

class TestSmallerFindings:
    def test_estimator_error_example_is_a_dotted_path(self):
        from potato.server_utils.config_module import (ConfigValidationError,
                                                       _validate_estimator_name)
        with pytest.raises(ConfigValidationError) as exc:
            _validate_estimator_name("active_learning.vectorizer.name", "tfidfx",
                                     kind="vectorizer")
        example = str(exc.value).rsplit("such as", 1)[-1].strip().rstrip(".")
        assert "." in example.strip("'")

    def test_distill_image_field_must_be_a_name(self):
        from potato.labeling_engine.config.schema import (EngineConfigError,
                                                          parse_engine_config)
        config = {"annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                          "labels": ["a", "b"]}],
                  "labeling_engine": {"enabled": True, "schemas": ["s"],
                                      "distill": {"image_field": 42}}}
        with pytest.raises(EngineConfigError) as exc:
            parse_engine_config(config)
        assert "image_field" in str(exc.value)

    def test_d002_does_not_claim_debug_skips_login(self):
        from potato.deploy import preflight
        ctx = SimpleNamespace(config={"debug": True})
        (finding,) = preflight._check_debug_mode(ctx)
        assert finding.code == "D002"
        assert "debug_user" in finding.message
        assert "any user" not in finding.message
