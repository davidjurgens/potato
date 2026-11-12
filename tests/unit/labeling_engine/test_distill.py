"""Distillation: train on human + certified labels, never on cert or audit
items, and put the new tier first, where it is recertified like any tier."""

import random

import pytest

from potato.labeling_engine import distill
from potato.labeling_engine.items import ItemView
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

LABELS = ["positive", "negative"]
WORDS = {"positive": ["great", "love", "excellent", "happy"],
         "negative": ["awful", "hate", "broken", "refund"]}


@pytest.fixture(autouse=True)
def _db():
    clear_db_cache()
    yield
    clear_db_cache()


def _items(n=1200, seed=0):
    rng = random.Random(seed)
    out = []
    for k in range(n):
        g = rng.choice(LABELS)
        text = f"{rng.choice(WORDS[g])} {rng.choice(WORDS[g])} item {k}"
        out.append(ItemView(f"i{k}", text, data={"gold": g}))
    return out


def _engine(tmp_path, **features):
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "d",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio", "labels": LABELS}],
           "labeling_engine": {
               "enabled": True,
               "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.1,
                            "options": {"separability": 0.8}}],
               "contracts": [{"id": "acc", "kind": "selective_risk", "schema": "s",
                              "error": 0.15}],
               "features": {"distill": True, **features},
               "distill": {"min_labels": 100}}}
    return Engine(cfg)


def _prepare(eng, items):
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], "ann", request_id=r.id)
    eng.certify(scheme)
    eng.resolve(scheme, open_requests=False)
    return scheme


def test_training_set_excludes_cert_and_audit_items(tmp_path):
    eng = _engine(tmp_path)
    items = _items()
    scheme = _prepare(eng, items)
    rows = distill.training_rows(eng, scheme, {i.item_id: i for i in items})
    cert = {r.item_id for r in eng.store.requests(split="cert")}
    assert cert and rows
    assert not ({r["instance_id"] for r in rows} & cert)
    assert any(r["silver"] for r in rows) and any(not r["silver"] for r in rows)


def test_distilled_tier_goes_first_and_stales_the_contract(tmp_path):
    eng = _engine(tmp_path)
    items = _items()
    scheme = _prepare(eng, items)
    before = eng.cascade_hash(scheme)
    assert distill.due(eng, scheme)
    entry = distill.distill_scheme(eng, scheme, items)
    assert entry and entry["n_train"] >= 100
    assert eng.tiers(scheme)[0] == "distilled-s"
    assert eng.cascade_hash(scheme) != before
    assert eng.contract_status(scheme)["acc"]["status"] == "stale"
    eng.predict(scheme, items)
    preds = eng.store.current_predictions("s", eng.tier_versions(scheme)[0])
    gold = {i.item_id: i.data["gold"] for i in items}
    acc = sum(p.value == gold[i] for i, p in preds.items()) / len(preds)
    assert acc > 0.9                         # the text is learnable
    res = eng.certify(scheme)["acc"]
    assert res["status"] in ("met", "insufficient", "infeasible")
    assert "distilled-s" in res["metrics"]["route"]
    # A restart finds the distilled tier again.
    clear_db_cache()
    again = Engine(eng.app_config)
    assert again.tiers(again.scheme("s"))[0] == "distilled-s"


def test_turning_distillation_off_restores_the_configured_cascade(tmp_path):
    eng = _engine(tmp_path)
    items = _items()
    scheme = _prepare(eng, items)
    distill.distill_scheme(eng, scheme, items)
    cfg = dict(eng.app_config)
    cfg["labeling_engine"] = {**cfg["labeling_engine"], "features": {}}
    off = Engine(cfg)
    assert off.tiers(off.scheme("s")) == ["fx"]


def test_too_few_labels_trains_nothing(tmp_path):
    eng = _engine(tmp_path)
    items = _items(200)
    scheme = eng.scheme("s")
    eng.register_items(items)
    assert distill.distill_scheme(eng, scheme, items) is None
    assert not distill.due(eng, scheme)


# --- image studies ------------------------------------------------------------

COLOURS = {"red": (200, 30, 30), "blue": (30, 30, 200)}


def _image_items(tmp_path, n=160, seed=0, remote=False):
    """Red and blue squares with noise, stored under media/ and referenced
    the way an image study's text_key does (/media/<file>)."""
    from PIL import Image
    rng = random.Random(seed)
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    out = []
    for k in range(n):
        g = rng.choice(list(COLOURS))
        base = COLOURS[g]
        img = Image.new("RGB", (48, 48))
        img.putdata([tuple(max(0, min(255, c + rng.randint(-40, 40))) for c in base)
                     for _ in range(48 * 48)])
        img.save(media / f"img{k}.png")
        ref = (f"http://images.example.org/img{k}.png" if remote else f"/media/img{k}.png")
        out.append(ItemView(f"i{k}", ref, data={"gold": g, "image_url": ref}))
    return out


def _image_engine(tmp_path, **distill_opts):
    cfg = {"task_dir": str(tmp_path), "annotation_task_name": "img",
           "media_directory": "media",
           "annotation_schemes": [{"name": "s", "annotation_type": "radio",
                                   "labels": list(COLOURS)}],
           "labeling_engine": {
               "enabled": True,
               "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.3}],
               "contracts": [{"id": "acc", "kind": "selective_risk", "schema": "s",
                              "error": 0.15}],
               "features": {"distill": True},
               "distill": {"min_labels": 40, **distill_opts}}}
    return Engine(cfg)


def _prepare_images(eng, items, rate=0.6):
    scheme = eng.scheme("s")
    eng.register_items(items)
    eng.predict(scheme, items)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=rate)
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in eng.store.requests(status=["open"]):
        eng.record_human_label(r.item_id, "s", gold[r.item_id], "ann", request_id=r.id)
    eng.certify(scheme)
    eng.resolve(scheme, open_requests=False)
    return scheme


class _RecordingTrainer:
    """Stands in for sklearn-text so the wiring is checked without CLIP."""
    name = "sklearn-text"

    def __init__(self):
        self.spec = self.rows = None

    def fit(self, spec, bundle, log):
        from types import SimpleNamespace
        self.spec, self.rows = spec, list(bundle.read_split("train"))
        return SimpleNamespace(metrics={})


def test_an_image_study_trains_on_image_files_with_clip(tmp_path, monkeypatch):
    """The distilled tier read an image study's text, which is only the image
    URL, through bag-of-words."""
    from potato.training import registry
    eng = _image_engine(tmp_path)
    items = _image_items(tmp_path)
    scheme = _prepare_images(eng, items)
    assert distill.modality_of(eng, items) == "image"
    fake = _RecordingTrainer()
    monkeypatch.setattr(registry, "get_trainer", lambda name: fake)
    entry = distill.distill_scheme(eng, scheme, items)
    assert entry and entry["options"]["modality"] == "image"
    assert fake.spec.params.get("vectorizer") == "clip"
    assert fake.rows and all(r["media"].endswith(".png") for r in fake.rows)
    assert all((tmp_path / "media" / r["media"].rsplit("/", 1)[-1]).exists()
               for r in fake.rows)


def test_a_text_study_keeps_the_text_vectorizer(tmp_path, monkeypatch):
    from potato.training import registry
    eng = _engine(tmp_path)
    items = _items(400)
    scheme = _prepare(eng, items)
    fake = _RecordingTrainer()
    monkeypatch.setattr(registry, "get_trainer", lambda name: fake)
    distill.distill_scheme(eng, scheme, items)
    assert "vectorizer" not in fake.spec.params
    assert all("media" not in r for r in fake.rows)


def test_remote_images_are_not_trained_on(tmp_path, monkeypatch):
    """Remote URLs are not downloaded, so they cannot be training rows."""
    from potato.training import registry
    eng = _image_engine(tmp_path)
    items = _image_items(tmp_path, remote=True)
    scheme = _prepare_images(eng, items)
    fake = _RecordingTrainer()
    monkeypatch.setattr(registry, "get_trainer", lambda name: fake)
    assert distill.distill_scheme(eng, scheme, items) is None
    assert fake.spec is None


def _clip_available():
    import os
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        from sentence_transformers import SentenceTransformer
        SentenceTransformer("clip-ViT-B-32")
        return True
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.timeout(600)
@pytest.mark.skipif(not _clip_available(), reason="CLIP (clip-ViT-B-32) not available offline")
def test_a_distilled_image_tier_labels_images_it_has_not_seen(tmp_path):
    """End to end with real CLIP embeddings: red and blue squares."""
    eng = _image_engine(tmp_path)
    items = _image_items(tmp_path)
    scheme = _prepare_images(eng, items)
    entry = distill.distill_scheme(eng, scheme, items)
    assert entry and eng.tiers(scheme)[0] == "distilled-s"
    eng.predict(scheme, items)
    preds = eng.store.current_predictions("s", eng.tier_versions(scheme)[0])
    trained_on = set()
    import json, os
    with open(os.path.join(entry["options"]["artifact_dir"], "train.jsonl")) as f:
        trained_on = {json.loads(l)["instance_id"] for l in f}
    gold = {i.item_id: i.data["gold"] for i in items}
    held_out = [i for i in preds if i not in trained_on and preds[i].value is not None]
    assert len(held_out) >= 20
    acc = sum(preds[i].value == gold[i] for i in held_out) / len(held_out)
    assert acc > 0.9
