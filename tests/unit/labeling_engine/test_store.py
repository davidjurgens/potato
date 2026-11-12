"""
The engine store: append-only predictions, the request ledger, resolved-label
history, budgets and the writer lock, all in engine.sqlite.
"""

import os
import threading

import pytest

from potato.labeling_engine.model import (
    Budget, ContractVersion, HumanRequest, ModelCall, Prediction, ResolvedLabel,
    Run, SamplingDesign, SourceVersion,
)
from potato.labeling_engine.store import EngineStore
from potato.persistence import clear_db_cache, get_db


@pytest.fixture
def store(tmp_path):
    clear_db_cache()
    s = EngineStore(str(tmp_path))
    yield s
    clear_db_cache()


def _sv(**kw):
    return SourceVersion(source_id="gemma", kind="llm", model="gemma-4",
                         endpoint_type="vllm", **kw)


class TestFile:

    def test_tables_live_in_engine_sqlite_not_project(self, store, tmp_path):
        store.item_count()
        assert os.path.exists(tmp_path / "engine.sqlite")
        proj = get_db(str(tmp_path))
        names = {r["name"] for r in proj.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "prediction" not in names

    def test_store_survives_a_cleared_migration_registry(self, tmp_path):
        from potato.persistence import clear_migrations
        clear_db_cache()
        clear_migrations()
        EngineStore(str(tmp_path)).upsert_items([{"item_id": "a"}])
        assert EngineStore(str(tmp_path)).item_count() == 1


class TestSourceVersion:

    def test_version_id_changes_with_anything_that_changes_answers(self):
        base = _sv(params={"temperature": 0})
        assert _sv(params={"temperature": 0}).version_id == base.version_id
        assert _sv(params={"temperature": 0.7}).version_id != base.version_id
        assert _sv(params={"temperature": 0},
                   prompt_template_hash="x").version_id != base.version_id
        assert _sv(params={"temperature": 0}, revision="r2").version_id != base.version_id

    def test_register_is_idempotent(self, store):
        sv = _sv()
        store.register_source_version(sv)
        store.register_source_version(sv)
        assert store.get_source_version(sv.version_id).model == "gemma-4"


class TestPredictionsAreAppendOnly:

    def test_rerun_appends_and_current_is_latest(self, store):
        sv = store.register_source_version(_sv())
        store.add_predictions([Prediction("i1", "s", sv, "pos", raw_conf=0.6)])
        store.add_predictions([Prediction("i1", "s", sv, "neg", raw_conf=0.9)])
        cur = store.current_predictions("s", sv)
        assert cur["i1"].value == "neg"
        hist = store.prediction_history("i1", "s")
        assert [p.value for p in hist] == ["pos", "neg"]

    def test_current_is_per_source_version(self, store):
        a = store.register_source_version(_sv())
        b = store.register_source_version(_sv(prompt_template_hash="v2"))
        store.add_predictions([Prediction("i1", "s", a, "pos"),
                               Prediction("i1", "s", b, "neg")])
        assert store.current_predictions("s", a)["i1"].value == "pos"
        assert store.current_predictions("s", b)["i1"].value == "neg"

    def test_current_filtered_by_items(self, store):
        sv = store.register_source_version(_sv())
        store.add_predictions([Prediction(f"i{k}", "s", sv, k) for k in range(1200)])
        got = store.current_predictions("s", sv, item_ids=["i3", "i1100", "nope"])
        assert set(got) == {"i3", "i1100"}
        assert store.predicted_item_ids("s", sv) == {f"i{k}" for k in range(1200)}

    def test_structured_values_and_confidence_round_trip(self, store):
        sv = store.register_source_version(_sv())
        box = [{"label": "cat", "bbox": [1, 2, 3, 4], "score": 0.8}]
        store.add_predictions([Prediction("i1", "img", sv, box,
                                          conf={"cat": 0.8}, call_ids=[3, 4])])
        p = store.current_predictions("img", sv)["i1"]
        assert p.value == box and p.conf == {"cat": 0.8} and p.call_ids == [3, 4]

    def test_failed_batch_writes_nothing(self, store):
        sv = store.register_source_version(_sv())
        bad = Prediction("i2", None, sv, "neg")  # schema_name is NOT NULL
        with pytest.raises(Exception):
            store.add_predictions([Prediction("i1", "s", sv, "pos"), bad])
        assert store.prediction_count() == 0


class TestCalls:

    def test_calls_and_totals(self, store):
        sv = store.register_source_version(_sv())
        store.add_calls([
            ModelCall(sv, "vllm", "gemma-4", "p", "i1", input_tokens=10,
                      output_tokens=2, cost_usd=0.01, estimated=False),
            ModelCall(sv, "vllm", "gemma-4", "p", "i2", cache_hit=True, cost_usd=0.0),
            ModelCall(sv, "vllm", "gemma-4", "p", "i3", error="timeout"),
        ])
        t = store.call_totals()
        assert t["n_calls"] == 3
        assert t["cost_usd"] == pytest.approx(0.01)
        row = t["by_source"][0]
        assert row["cache_hits"] == 1 and row["errors"] == 1 and row["unpriced"] == 1
        assert [c.input_hash for c in store.calls()] == ["i3", "i2", "i1"]
        assert store.calls()[2].estimated is False


class TestLedger:

    def test_request_round_trip_keeps_inclusion_probability(self, store):
        did = store.add_design(SamplingDesign("bernoulli", {"rate": 0.2}, seed=7))
        [rid] = store.add_requests([HumanRequest(
            "i1", "s", "calibration", inclusion_prob=0.2, design_id=did, split="dev")])
        r = store.get_request(rid)
        assert r.inclusion_prob == 0.2 and r.design_id == did and r.visibility == "blind"
        assert store.get_design(did).params == {"rate": 0.2}

    def test_filters_and_priority_order(self, store):
        store.add_requests([
            HumanRequest("a", "s", "verify", 1.0, visibility="shown", priority=1),
            HumanRequest("b", "s", "calibration", 0.1, priority=5),
            HumanRequest("c", "s", "calibration", 0.1, status="done"),
        ])
        open_ = store.requests(status=["open"])
        assert [r.item_id for r in open_] == ["b", "a"]
        assert [r.item_id for r in store.requests(purpose=["calibration"])] == ["b", "c"]
        assert store.request_counts() == {"verify": {"open": 1},
                                          "calibration": {"open": 1, "done": 1}}

    def test_update_refuses_design_fields(self, store):
        [rid] = store.add_requests([HumanRequest("a", "s", "calibration", 0.5)])
        store.update_request(rid, status="done", label="pos", user_id="u1")
        assert store.get_request(rid).label == "pos"
        with pytest.raises(ValueError):
            store.update_request(rid, inclusion_prob=1.0)


class TestResolved:

    def test_history_is_kept(self, store):
        store.set_resolved([ResolvedLabel("i1", "s", "pos", "auto", "accepted")])
        store.set_resolved([ResolvedLabel("i1", "s", "neg", "human", "accepted")])
        [cur] = store.resolved(schema="s")
        assert cur.value == "neg" and cur.origin == "human"
        assert [h.value for h in store.resolved_history("i1", "s")] == ["pos", "neg"]

    def test_status_move_by_origin(self, store):
        store.set_resolved([ResolvedLabel("a", "s", 1, "auto", "accepted"),
                            ResolvedLabel("b", "s", 1, "human", "accepted")])
        assert store.mark_resolved_status("s", ["accepted"], "pending_recert",
                                          origin="auto") == 1
        st = {r.item_id: r.status for r in store.resolved(schema="s")}
        assert st == {"a": "pending_recert", "b": "accepted"}


class TestItemsContractsBudgets:

    def test_item_meta_merges_and_persists(self, store, tmp_path):
        store.upsert_items([{"item_id": "a", "meta": {"required_annotations": 3}},
                            {"item_id": "b"}])
        store.upsert_items([{"item_id": "a", "meta": {"split": "dev"}}])
        clear_db_cache()
        again = EngineStore(str(tmp_path))
        assert again.get_item_meta("a") == {"required_annotations": 3, "split": "dev"}
        assert again.items_with_meta_key("required_annotations") == {"a": 3}
        assert again.item_count() == 2

    def test_looks_counted_per_cascade(self, store):
        store.add_contract_version(ContractVersion("c", "selective_risk", {}, "h1", looks=1))
        store.add_contract_version(ContractVersion("c", "selective_risk", {}, "h1", looks=2))
        store.add_contract_version(ContractVersion("c", "selective_risk", {}, "h2", looks=1))
        assert store.looks_used("c", "h1") == 2
        assert store.looks_used("c", "h2") == 1
        assert store.looks_used("c", "h3") == 0
        assert store.latest_contract_version("c").cascade_hash == "h2"

    def test_spend_accumulates_and_limit_survives(self, store):
        store.set_budget(Budget("human_usd", limit=50))
        store.add_spend("human_usd", 10)
        assert store.add_spend("human_usd", 2.5) == 12.5
        store.set_budget(Budget("human_usd", limit=60))
        b = store.get_budget("human_usd")
        assert b.limit == 60 and b.spent == 12.5

    def test_runs(self, store):
        rid = store.start_run(Run("predict", cursor={"done": 0}))
        store.update_run(rid, cursor={"done": 5})
        store.update_run(rid, status="done")
        r = store.get_run(rid)
        assert r.cursor == {"done": 5} and r.status == "done" and r.finished_at


class TestWriterLock:

    def test_second_holder_refused_until_stale(self, store):
        assert store.acquire_writer("cli-1")
        assert not store.acquire_writer("server")
        assert store.acquire_writer("cli-1")  # re-entrant for the holder
        assert store.acquire_writer("server", stale_after=-1)  # stale: taken over
        assert store.writer_holder() == "server"
        store.release_writer("server")
        assert store.writer_holder() is None


def test_concurrent_writers_do_not_interleave_transactions(store):
    sv = store.register_source_version(_sv())
    errors = []

    def write(k):
        try:
            store.add_predictions([Prediction(f"t{k}-{j}", "s", sv, j)
                                   for j in range(200)])
        except Exception as e:  # pragma: no cover - the assertion reports it
            errors.append(e)

    threads = [threading.Thread(target=write, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert store.prediction_count() == 1600


class TestWriterLock:
    """potato-skill B4, B12/E8 and A7."""

    def test_a_killed_holder_on_this_host_is_taken_over_at_once(self, store):
        import socket
        import subprocess
        import sys
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        dead = f"server:{socket.gethostname()}:{p.pid}:1"
        assert store.acquire_writer(dead)
        assert store.live_writer() is None
        assert store.acquire_writer(store.writer_name("cli"))

    def test_a_live_holder_keeps_the_lock(self, store):
        mine = store.writer_name("server")
        assert store.acquire_writer(mine)
        assert store.live_writer() == mine
        assert not store.acquire_writer(store.writer_name("cli"))

    def test_the_heartbeat_runs_during_a_long_tick(self, store):
        import time as _t
        mine = store.writer_name("server")
        assert store.acquire_writer(mine)
        store.conn.execute("UPDATE writer_lock SET heartbeat = ?", (_t.time() - 500,))
        with store.holding_writer(mine, every=0.05):
            _t.sleep(0.3)
            # Without the thread the lock would be up for takeover here.
            assert not store.acquire_writer(store.writer_name("cli"), stale_after=1.0)
