"""
The project-wide embedder: what it picks, and whether it admits what it picked.

The failure this replaces was silent. `get_text()` returns an item's first
string value when there is no text key, so a vision project embedded its
instance ids — and the corpus map plotted a UMAP of `img_01`, `img_02`, …
without a word about it. Every test here therefore checks two things: the right
backend and field were chosen, and the choice is legible afterwards.

No model is loaded anywhere in this file. Backends are registered by module
path and only imported on use, which is also what keeps them off the boot path.
"""

import sys
import types

import pytest

from potato.embedders import (
    EmbeddingBackend,
    backend_names,
    detect,
    parse_config,
    register,
    resolve,
    unregister,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

IMAGE_ITEMS = [
    {"id": "img_01", "image_url": "media/cat.jpg"},
    {"id": "img_02", "image_url": "media/dog.png"},
    {"id": "img_03", "image_url": "media/bird.webp"},
]
TEXT_ITEMS = [
    {"id": "t1", "text": "the clinic was closed"},
    {"id": "t2", "text": "three weeks for an appointment"},
]
AUDIO_ITEMS = [{"id": "a1", "audio_url": "clips/one.wav"},
               {"id": "a2", "audio_url": "clips/two.mp3"}]
VIDEO_ITEMS = [{"id": "v1", "video_url": "clips/one.mp4"},
               {"id": "v2", "video_url": "clips/two.webm"}]
#: A vision task whose prompt is identical on every item — the case where
#: embedding the text produces one useless blob.
MULTIMODAL_ITEMS = [
    {"id": "m1", "image_url": "media/a.jpg", "text": "Is this AI-generated?"},
    {"id": "m2", "image_url": "media/b.jpg", "text": "Is this AI-generated?"},
]

TEXT_CONFIG = {"item_properties": {"text_key": "text"}}


class FakeBackend(EmbeddingBackend):
    """Deterministic vectors, no dependencies, records what it was asked."""

    name = "fake"
    modality = "fake"
    default_model = "fake-v1"
    calls = []

    def embed(self, references):
        import numpy
        FakeBackend.calls.append(list(references))
        return numpy.array([[float(len(r)), float(i)]
                            for i, r in enumerate(references)])


@pytest.fixture
def fake_backend():
    FakeBackend.calls = []
    register(FakeBackend)
    yield FakeBackend
    unregister("fake")


class TestDetection:
    def test_an_image_corpus_is_detected(self):
        backend, field, reason, _ = detect(IMAGE_ITEMS, TEXT_CONFIG)
        assert (backend, field) == ("image", "image_url")
        assert "image_url" in reason

    def test_an_audio_corpus_is_detected(self):
        backend, field, _, _ = detect(AUDIO_ITEMS, TEXT_CONFIG)
        assert (backend, field) == ("audio", "audio_url")

    def test_a_video_corpus_is_detected(self):
        backend, field, _, _ = detect(VIDEO_ITEMS, TEXT_CONFIG)
        assert (backend, field) == ("video", "video_url")

    def test_a_text_corpus_stays_text(self):
        backend, field, _, _ = detect(TEXT_ITEMS, TEXT_CONFIG)
        assert (backend, field) == ("text", "text")

    def test_media_wins_over_a_shared_prompt(self):
        """Both fields are present; the images are what varies."""
        backend, field, _, alternatives = detect(MULTIMODAL_ITEMS, TEXT_CONFIG)
        assert (backend, field) == ("image", "image_url")

    def test_a_custom_text_key_is_respected(self):
        items = [{"id": "1", "utterance": "hello"}]
        config = {"item_properties": {"text_key": "utterance"}}
        backend, field, _, _ = detect(items, config)
        assert (backend, field) == ("text", "utterance")

    def test_extension_beats_field_name(self):
        """A field called `notes` holding image paths is still images."""
        items = [{"id": "1", "notes": "shots/a.png"},
                 {"id": "2", "notes": "shots/b.png"}]
        backend, field, _, _ = detect(items, TEXT_CONFIG)
        assert (backend, field) == ("image", "notes")

    def test_a_sentence_in_an_image_named_field_is_not_a_reference(self):
        items = [{"id": "1", "image": "a photograph of a cat sitting down"}]
        backend, _, _, _ = detect(items, TEXT_CONFIG)
        assert backend == "text"

    def test_query_strings_do_not_hide_the_extension(self):
        items = [{"id": "1", "src": "https://cdn.example.com/a.jpg?w=800&token=x"}]
        backend, field, _, _ = detect(items, TEXT_CONFIG)
        assert (backend, field) == ("image", "src")

    def test_an_id_only_corpus_refuses_rather_than_embedding_ids(self):
        """The whole point. `get_text()` would have returned 'img_01' here."""
        items = [{"id": "img_01"}, {"id": "img_02"}]
        backend, field, reason, _ = detect(items, TEXT_CONFIG)
        assert field is None
        assert "nothing to embed" in reason

    def test_no_items(self):
        backend, _, reason, _ = detect([], TEXT_CONFIG)
        assert backend == "text"
        assert "no items" in reason


class TestConfigParsing:
    def test_defaults(self):
        settings = parse_config({})
        assert settings.backend == "auto"
        assert settings.model is None

    def test_unknown_keys_become_backend_options(self):
        settings = parse_config({"embeddings": {
            "backend": "custom", "entrypoint": "mod:fn", "batch_size": 8}})
        assert settings.options == {"entrypoint": "mod:fn", "batch_size": 8}

    def test_a_non_mapping_block_is_ignored_not_fatal(self):
        assert parse_config({"embeddings": "clip"}).backend == "auto"


class TestResolution:
    def test_the_configured_backend_wins_over_detection(self, fake_backend):
        embedder = resolve({"embeddings": {"backend": "fake",
                                           "source_field": "image_url"}},
                           samples=IMAGE_ITEMS)
        assert embedder.spec.backend == "fake"
        assert embedder.spec.source_field == "image_url"
        assert "configured" in embedder.spec.chosen_because

    def test_a_configured_backend_still_gets_a_detected_field(self, fake_backend):
        embedder = resolve({"embeddings": {"backend": "fake"}},
                           samples=IMAGE_ITEMS)
        assert embedder.spec.backend == "fake"

    def test_an_unknown_backend_reports_instead_of_raising(self):
        embedder = resolve({"embeddings": {"backend": "nope"}},
                           samples=TEXT_ITEMS)
        assert not embedder.available
        assert "Unknown embedding backend" in embedder.spec.unavailable_reason

    def test_nothing_to_embed_is_unavailable_with_a_reason(self, fake_backend):
        embedder = resolve({}, samples=[{"id": "a"}, {"id": "b"}])
        assert not embedder.available
        assert embedder.spec.unavailable_reason

    def test_the_spec_survives_into_a_dict_for_the_ui(self, fake_backend):
        spec = resolve({"embeddings": {"backend": "fake",
                                       "source_field": "image_url"}},
                       samples=IMAGE_ITEMS).spec.to_dict()
        assert spec["backend"] == "fake"
        assert spec["source_field"] == "image_url"
        assert spec["available"] is True
        assert "chosen_because" in spec


class TestEmbeddingItems:
    def test_it_embeds_the_chosen_field_not_the_id(self, fake_backend):
        embedder = resolve({"embeddings": {"backend": "fake",
                                           "source_field": "image_url"}},
                           samples=IMAGE_ITEMS)
        vectors = embedder.embed_items({i["id"]: i for i in IMAGE_ITEMS})
        assert set(vectors) == {"img_01", "img_02", "img_03"}
        assert fake_backend.calls[-1] == ["media/cat.jpg", "media/dog.png",
                                          "media/bird.webp"]

    def test_items_without_the_field_are_skipped_not_faked(self, fake_backend):
        items = {"a": {"id": "a", "image_url": "x.jpg"}, "b": {"id": "b"}}
        embedder = resolve({"embeddings": {"backend": "fake",
                                           "source_field": "image_url"}},
                           samples=list(items.values()))
        vectors = embedder.embed_items(items)
        assert set(vectors) == {"a"}

    def test_an_unavailable_embedder_returns_nothing(self):
        embedder = resolve({"embeddings": {"backend": "nope"}},
                           samples=IMAGE_ITEMS)
        assert embedder.embed_items({i["id"]: i for i in IMAGE_ITEMS}) == {}


class TestCustomBackend:
    """The admin-defined path: bring your own encoder."""

    def test_a_python_entrypoint_is_called(self):
        module = types.ModuleType("fake_lab_encoders")
        module.embed_batch = lambda refs: [[1.0, float(len(r))] for r in refs]
        sys.modules["fake_lab_encoders"] = module
        try:
            embedder = resolve({"embeddings": {
                "backend": "custom",
                "source_field": "image_url",
                "modality": "image",
                "entrypoint": "fake_lab_encoders:embed_batch",
            }}, samples=IMAGE_ITEMS)
            assert embedder.available
            assert embedder.spec.modality == "image"
            vectors = embedder.embed_items({i["id"]: i for i in IMAGE_ITEMS})
            assert len(vectors) == 3
            assert list(vectors["img_01"]) == [1.0, 13.0]
        finally:
            del sys.modules["fake_lab_encoders"]

    def test_custom_without_a_target_is_refused_with_advice(self):
        embedder = resolve({"embeddings": {"backend": "custom"}},
                           samples=IMAGE_ITEMS)
        assert not embedder.available
        assert "entrypoint" in embedder.spec.unavailable_reason

    def test_a_malformed_entrypoint_is_refused_before_import(self):
        embedder = resolve({"embeddings": {"backend": "custom",
                                           "entrypoint": "no_colon_here"}},
                           samples=IMAGE_ITEMS)
        assert not embedder.available
        assert "module.path:callable" in embedder.spec.unavailable_reason

    def test_a_wrong_shaped_return_is_an_error_not_a_silent_map(self):
        module = types.ModuleType("bad_encoders")
        module.embed_batch = lambda refs: [[1.0, 2.0]]      # one row for three
        sys.modules["bad_encoders"] = module
        try:
            embedder = resolve({"embeddings": {
                "backend": "custom", "source_field": "image_url",
                "entrypoint": "bad_encoders:embed_batch"}}, samples=IMAGE_ITEMS)
            with pytest.raises(RuntimeError, match="expected"):
                embedder.embed_items({i["id"]: i for i in IMAGE_ITEMS})
        finally:
            del sys.modules["bad_encoders"]


class TestConfigValidation:
    """Reject at startup what would otherwise show up as an empty corpus map."""

    def validate(self, block):
        from potato.server_utils.config_module import validate_embeddings_config
        validate_embeddings_config({"embeddings": block} if block is not None else {})

    def test_absent_and_default_blocks_are_fine(self):
        self.validate(None)
        self.validate({"backend": "auto"})
        self.validate({"backend": "image", "model": "clip-ViT-B-32"})

    def test_an_unknown_backend_is_rejected_by_name(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="not a known backend"):
            self.validate({"backend": "clip"})     # the model, not the backend

    def test_custom_with_nothing_to_call_is_rejected(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="entrypoint"):
            self.validate({"backend": "custom"})

    def test_a_dotted_entrypoint_is_rejected_before_the_run(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="module.path:callable"):
            self.validate({"backend": "custom", "entrypoint": "mypkg.mod.fn"})

    def test_a_string_instead_of_a_block(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="must be a dictionary"):
            from potato.server_utils.config_module import validate_embeddings_config
            validate_embeddings_config({"embeddings": "clip"})

    def test_the_block_is_a_known_config_key(self):
        """Otherwise every project using it gets an 'unrecognized key' warning."""
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS
        assert "embeddings" in KNOWN_CONFIG_KEYS


class TestBootWeight:
    """Naming a backend must not import its model library."""

    def test_the_package_imports_no_ml_stack(self):
        assert "image" in backend_names() and "audio" in backend_names()

    def test_resolving_an_unavailable_backend_does_not_import_it(self):
        """available() probes with find_spec; it must not construct a model."""
        import importlib.util
        before = set(sys.modules)
        resolve({"embeddings": {"backend": "text"}}, samples=TEXT_ITEMS)
        new = set(sys.modules) - before
        assert not any(m.startswith(("torch", "transformers"))
                       for m in new), sorted(new)[:10]
