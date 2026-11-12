"""
Dataset versioning tests, run against BOTH storage backends via a parametrized
fixture so file and sqlite stay in parity.
"""

import pytest

from potato.eval_datasets.models import Example
from potato.eval_datasets.storage import create_store


@pytest.fixture(params=["file", "sqlite"])
def store(request, tmp_path):
    return create_store(request.param, str(tmp_path))


def _ex(id, text, ref=None, split="test", **meta):
    return Example(id=id, inputs={"text": text}, reference_outputs=ref, split=split, metadata=meta)


def test_create_and_get_dataset(store):
    store.create_dataset("d1", description="desc")
    ds = store.get_dataset("d1")
    assert ds is not None and ds.name == "d1" and ds.description == "desc"
    assert ds.versions == []


def test_create_is_idempotent(store):
    store.create_dataset("d1")
    store.create_dataset("d1")
    assert len(store.list_datasets()) == 1


def test_add_examples_creates_version(store):
    store.create_dataset("d1")
    v = store.add_examples("d1", [_ex("a", "x"), _ex("b", "y")])
    assert v.version_id == "v0001"
    assert v.example_count == 2
    examples = store.list_examples("d1")
    assert {e.id for e in examples} == {"a", "b"}


def test_each_mutation_increments_version(store):
    store.create_dataset("d1")
    store.add_examples("d1", [_ex("a", "x")])
    store.add_examples("d1", [_ex("b", "y")])
    store.delete_example("d1", "a")
    versions = store.list_versions("d1")
    assert [v.version_id for v in versions] == ["v0001", "v0002", "v0003"]
    # latest has only b
    assert {e.id for e in store.list_examples("d1")} == {"b"}


def test_update_example_replaces(store):
    store.create_dataset("d1")
    store.add_examples("d1", [_ex("a", "x")])
    store.update_example("d1", _ex("a", "updated"))
    examples = store.list_examples("d1")
    assert len(examples) == 1
    assert examples[0].inputs["text"] == "updated"


def test_as_of_pins_old_version(store):
    store.create_dataset("d1")
    store.add_examples("d1", [_ex("a", "x")])          # v0001
    store.add_examples("d1", [_ex("b", "y")])          # v0002
    v1 = store.list_examples("d1", as_of="v0001")
    assert {e.id for e in v1} == {"a"}
    latest = store.list_examples("d1", as_of="latest")
    assert {e.id for e in latest} == {"a", "b"}


def test_tag_resolution(store):
    store.create_dataset("d1")
    store.add_examples("d1", [_ex("a", "x")])          # v0001
    store.add_examples("d1", [_ex("b", "y")])          # v0002
    assert store.tag_version("d1", "v0001", "prod")
    assert store.resolve_version("d1", "prod") == "v0001"
    assert {e.id for e in store.list_examples("d1", as_of="prod")} == {"a"}


def test_tag_moves_to_one_version(store):
    store.create_dataset("d1")
    store.add_examples("d1", [_ex("a", "x")])          # v0001
    store.add_examples("d1", [_ex("b", "y")])          # v0002
    store.tag_version("d1", "v0001", "prod")
    store.tag_version("d1", "v0002", "prod")           # move tag
    assert store.resolve_version("d1", "prod") == "v0002"
    v1 = next(v for v in store.list_versions("d1") if v.version_id == "v0001")
    assert "prod" not in v1.tags


def test_split_and_metadata_filter(store):
    store.create_dataset("d1")
    store.add_examples("d1", [
        _ex("a", "x", split="train", lang="en"),
        _ex("b", "y", split="test", lang="en"),
        _ex("c", "z", split="test", lang="fr"),
    ])
    assert {e.id for e in store.list_examples("d1", splits=["test"])} == {"b", "c"}
    assert {e.id for e in store.list_examples("d1", metadata_filter={"lang": "fr"})} == {"c"}


def test_delete_dataset(store):
    store.create_dataset("d1")
    store.add_examples("d1", [_ex("a", "x")])
    assert store.delete_dataset("d1") is True
    assert store.get_dataset("d1") is None
    assert store.delete_dataset("d1") is False


def test_resolve_unknown_returns_none(store):
    store.create_dataset("d1")
    assert store.resolve_version("d1", "latest") is None  # no versions yet
    store.add_examples("d1", [_ex("a", "x")])
    assert store.resolve_version("d1", "nonexistent") is None
