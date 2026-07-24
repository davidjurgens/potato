"""Unit tests for the cross-document Event Registry (Phase 0).

Covers serialization roundtrips, persistence, seed idempotency, and the
import-weight guard (the registry package must NOT pull in the ML stack).
"""

import json
import os
import sys

import pytest

from potato.event_registry.manager import (
    Event,
    EvidenceCitation,
    EventRegistryManager,
    StaleWriteError,
)


@pytest.fixture
def cfg(tmp_path):
    return {
        "output_annotation_dir": str(tmp_path),
        "task_dir": str(tmp_path),
        "event_template": {
            "enabled": True,
            "slots": [{"name": "event_type"}, {"name": "where"}],
        },
    }


class TestSerialization:
    def test_evidence_roundtrip(self):
        c = EvidenceCitation(
            slot_name="where", doc_id="doc_2", span_start=5, span_end=15,
            quoted_text="in Bangkok", span_id="s1", created_by="alice",
        )
        assert EvidenceCitation.from_dict(c.to_dict()).to_dict() == c.to_dict()

    def test_event_roundtrip(self):
        ev = Event(id="evt_1", template_name="t", title="Flood")
        ev.slot_values["event_type"] = "flood"
        ev.member_doc_ids.extend(["doc_1", "doc_2"])
        ev.evidence.append(
            EvidenceCitation(slot_name="where", doc_id="doc_2", span_start=0, span_end=3)
        )
        assert Event.from_dict(ev.to_dict()).to_dict() == ev.to_dict()


class TestPersistence:
    def test_create_mutate_reload(self, cfg):
        m = EventRegistryManager(cfg)
        ev = m.create_event("alice", title="Flood 2011")
        m.update_slot(ev.id, "event_type", "flood", "alice")
        m.add_member(ev.id, "doc_1")
        m.add_evidence(
            ev.id,
            EvidenceCitation(slot_name="where", doc_id="doc_2", span_start=5,
                             span_end=15, quoted_text="in Bangkok"),
        )
        assert os.path.exists(os.path.join(cfg["output_annotation_dir"], "event_registry.json"))

        # Fresh manager reads the same file.
        m2 = EventRegistryManager(cfg)
        ev2 = m2.get_event(ev.id)
        assert ev2.slot_values["event_type"] == "flood"
        # Evidence from doc_2 implies membership.
        assert set(ev2.member_doc_ids) == {"doc_1", "doc_2"}
        assert ev2.evidence[0].quoted_text == "in Bangkok"

    def test_list_events_by_doc(self, cfg):
        m = EventRegistryManager(cfg)
        a = m.create_event("u", title="A")
        b = m.create_event("u", title="B")
        m.add_member(a.id, "doc_1")
        m.add_member(b.id, "doc_2")
        ids = {e.id for e in m.list_events(doc_id="doc_1")}
        assert ids == {a.id}

    def test_remove_evidence_and_member(self, cfg):
        m = EventRegistryManager(cfg)
        ev = m.create_event("u")
        m.add_evidence(ev.id, EvidenceCitation(slot_name="s", doc_id="d1", span_start=0, span_end=1))
        m.remove_evidence(ev.id, 0)
        assert m.get_event(ev.id).evidence == []
        m.add_member(ev.id, "d9")
        m.remove_member(ev.id, "d9")
        assert "d9" not in m.get_event(ev.id).member_doc_ids

    def test_delete_event(self, cfg):
        m = EventRegistryManager(cfg)
        ev = m.create_event("u")
        assert m.delete_event(ev.id) is True
        assert m.get_event(ev.id) is None
        assert m.delete_event("nope") is False


class TestOptimisticLocking:
    def test_stale_write_rejected(self, cfg):
        m = EventRegistryManager(cfg)
        ev = m.create_event("alice")
        stamp = ev.updated_at

        # First writer succeeds and bumps updated_at.
        m.update_slot(ev.id, "event_type", "flood", "alice", expected_updated_at=stamp)

        # Second writer using the OLD stamp is rejected.
        with pytest.raises(StaleWriteError) as ei:
            m.update_slot(ev.id, "event_type", "quake", "bob", expected_updated_at=stamp)
        assert ei.value.current.slot_values["event_type"] == "flood"

    def test_unconditional_write_always_wins(self, cfg):
        m = EventRegistryManager(cfg)
        ev = m.create_event("u")
        # No expected_updated_at -> last-write-wins (backwards-compatible default).
        m.update_slot(ev.id, "x", "1", "u")
        m.update_slot(ev.id, "x", "2", "u")
        assert m.get_event(ev.id).slot_values["x"] == "2"


class TestSeeding:
    def test_seed_loads_and_is_idempotent(self, cfg, tmp_path):
        seed = tmp_path / "seed.json"
        seed.write_text(json.dumps({
            "events": [{"id": "evt_seed_x", "title": "Quake",
                        "slot_values": {"event_type": "earthquake"}}]
        }))
        cfg["event_template"]["seed_events"] = str(seed)

        m = EventRegistryManager(cfg)
        assert m.get_event("evt_seed_x").provenance == "seeded"

        # Annotator edits the seeded event; a restart must not clobber it.
        m.update_slot("evt_seed_x", "event_type", "tsunami", "bob")
        m2 = EventRegistryManager(cfg)
        assert m2.get_event("evt_seed_x").slot_values["event_type"] == "tsunami"


class TestImportWeight:
    def test_registry_is_import_light(self):
        """The event_registry package must not pull in the ML stack at import."""
        # Import fresh in a subprocess-free way: just assert current state after
        # importing the module (already imported above, but ML stack must be absent
        # unless some *other* test loaded it — so check the module's own deps).
        import importlib
        mod = importlib.import_module("potato.event_registry.manager")
        assert mod is not None
        # The manager module itself references none of these at module scope.
        src = open(mod.__file__).read()
        for banned in ("import sentence_transformers", "import sklearn",
                       "import umap", "from sentence_transformers"):
            assert banned not in src, f"event_registry.manager must not {banned}"
