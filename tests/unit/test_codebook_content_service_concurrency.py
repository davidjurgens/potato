"""Concurrency tests for the codebook content service (Phase 6).

`content_service.save_scope` is the single audited mutation path for the
living document. This codebase has a long history of save/persistence bugs,
so the optimistic compare-and-swap, the global `_SAVE_LOCK`, and the
archive+insert in `replace_scope_blocks` are the highest-risk surface. These
tests hammer them with real threads to prove:

  * lost-update prevention — two writers at the same base, exactly one wins;
  * different-scope parallelism — saves to distinct codes never collide;
  * threaded same-scope atomicity — no torn writes (never zero live blocks,
    never duplicate live ordinals, exactly one winner per version step);
  * retry-converges — optimistic losers that rebase all eventually land;
  * snapshot/revision invariants — one snapshot per save, monotonic content
    revision, semantic revision only on semantic edits;
  * reload round-trip after a save (serialization drift guard at the service
    layer, not just the pure parser);
  * proposal-vs-direct race — a confirm after the scope advanced is rejected.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from potato.codebook import content_service as cs
from potato.codebook import create_code
from potato.codebook import blocks as cb_blocks
from potato.codebook import snapshots
from potato.codebook.markdown import blocks_to_markdown, markdown_to_blocks
from potato.codebook.blocks import _BLOCKS_MIGRATION
from potato.codebook.store import _CODEBOOK_MIGRATION
from potato.codebook.revision import (
    _REVISION_MIGRATION, _CODES_REV_MIGRATION, _CONTENT_PROV_MIGRATION)
from potato.codebook.changelog import _CHANGE_MIGRATION
from potato.codebook.service import clear_change_listeners
from potato.persistence import (
    clear_db_cache, clear_migrations, register_migration)


@pytest.fixture(autouse=True)
def _isolated_db():
    clear_db_cache()
    clear_migrations()
    for m in (_CODEBOOK_MIGRATION, _REVISION_MIGRATION, _CODES_REV_MIGRATION,
              _CHANGE_MIGRATION, _BLOCKS_MIGRATION, _CONTENT_PROV_MIGRATION):
        register_migration(m)
    clear_change_listeners()
    yield
    clear_db_cache()
    clear_migrations()
    clear_change_listeners()


@pytest.fixture
def td(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _code(td, name):
    return create_code(td, project="p", name=name, created_by="a")["id"]


def _def(body):
    return [{"block_type": "definition", "body_md": body}]


def _save(td, cid, body, base, actor, **kw):
    return cs.save_scope(
        td, project="p", scope_kind="code", scope_id=cid,
        blocks_in=_def(body), base_version=base, actor=actor, **kw)


# --------------------------------------------------------------------------
# Lost-update prevention
# --------------------------------------------------------------------------

class TestLostUpdate:
    def test_two_writers_same_base_exactly_one_wins(self, td):
        cid = _code(td, "race code")
        barrier = threading.Barrier(2)
        results = {}

        def writer(tag, body):
            barrier.wait()  # maximize overlap on the shared scope
            try:
                results[tag] = ("ok", _save(td, cid, body, 0, tag))
            except cs.StaleContentError as e:
                results[tag] = ("stale", e)

        ta = threading.Thread(target=writer, args=("A", "alpha wins"))
        tb = threading.Thread(target=writer, args=("B", "beta wins"))
        ta.start(); tb.start(); ta.join(); tb.join()

        kinds = sorted(k for k, _ in results.values())
        assert kinds == ["ok", "stale"], results

        # The winner's content is what persisted — never silently clobbered.
        winner = next(b for (k, b) in results.values() if k == "ok")
        live = cb_blocks.list_blocks(td, "p", code_id=cid)
        assert len(live) == 1
        assert live[0]["body_md"] == winner["blocks"][0]["body_md"]
        assert cb_blocks.scope_version(td, "p", code_id=cid) == 1

    def test_stale_loser_can_rebase_and_win(self, td):
        cid = _code(td, "rebase code")
        a = _save(td, cid, "first", 0, "A")
        assert a["scope_version"] == 1
        # B authored against base 0 -> stale
        with pytest.raises(cs.StaleContentError) as exc:
            _save(td, cid, "second-stale", 0, "B")
        assert exc.value.current_version == 1
        assert exc.value.current_blocks[0]["body_md"] == "first"
        # B rebases onto the current version and lands
        b = _save(td, cid, "second-rebased", 1, "B")
        assert b["scope_version"] == 2
        assert cb_blocks.list_blocks(
            td, "p", code_id=cid)[0]["body_md"] == "second-rebased"


# --------------------------------------------------------------------------
# Different-scope parallelism
# --------------------------------------------------------------------------

class TestParallelScopes:
    def test_two_codes_save_concurrently(self, td):
        c1 = _code(td, "code one")
        c2 = _code(td, "code two")
        start = threading.Barrier(2)
        out = {}

        def writer(cid, key, body):
            start.wait()
            out[key] = _save(td, cid, body, 0, key)

        t1 = threading.Thread(target=writer, args=(c1, "one", "body one"))
        t2 = threading.Thread(target=writer, args=(c2, "two", "body two"))
        t1.start(); t2.start(); t1.join(); t2.join()

        # Both succeed; neither cross-bumps the other's scope version.
        assert out["one"]["scope_version"] == 1
        assert out["two"]["scope_version"] == 1
        assert cb_blocks.list_blocks(
            td, "p", code_id=c1)[0]["body_md"] == "body one"
        assert cb_blocks.list_blocks(
            td, "p", code_id=c2)[0]["body_md"] == "body two"

    def test_code_and_doc_section_parallel(self, td):
        cid = _code(td, "para code")
        start = threading.Barrier(2)
        out = {}

        def code_writer():
            start.wait()
            out["code"] = _save(td, cid, "code body", 0, "cw")

        def sect_writer():
            start.wait()
            out["sect"] = cs.save_scope(
                td, project="p", scope_kind="section", scope_id="preamble",
                blocks_in=[{"block_type": "custom", "custom_label": "Preamble",
                            "body_md": "read me first"}],
                base_version=0, actor="sw")

        t1 = threading.Thread(target=code_writer)
        t2 = threading.Thread(target=sect_writer)
        t1.start(); t2.start(); t1.join(); t2.join()
        assert out["code"]["scope_version"] == 1
        assert out["sect"]["scope_version"] == 1


# --------------------------------------------------------------------------
# Threaded same-scope hammer — atomicity / no torn writes
# --------------------------------------------------------------------------

class TestHammerAtomicity:
    def test_single_round_exactly_one_winner_no_torn_state(self, td):
        cid = _code(td, "hammer code")
        N = 12
        barrier = threading.Barrier(N)
        kinds = []
        lock = threading.Lock()

        def writer(i):
            barrier.wait()
            try:
                _save(td, cid, f"body-{i}", 0, f"w{i}")
                with lock:
                    kinds.append("ok")
            except cs.StaleContentError:
                with lock:
                    kinds.append("stale")

        with ThreadPoolExecutor(max_workers=N) as ex:
            list(ex.map(writer, range(N)))

        assert kinds.count("ok") == 1, kinds
        assert kinds.count("stale") == N - 1
        assert cb_blocks.scope_version(td, "p", code_id=cid) == 1
        # No torn write: exactly one live block, never zero, no dup ordinals.
        live = cb_blocks.list_blocks(td, "p", code_id=cid)
        assert len(live) == 1
        assert len({b["ordinal"] for b in live}) == len(live)

    def test_retry_converges_all_writers_land(self, td):
        cid = _code(td, "converge code")
        N = 10
        done = []
        lock = threading.Lock()

        def writer(i):
            # Each writer keeps rebasing onto the current version until it
            # wins — the optimistic loop a real client would run.
            while True:
                base = cb_blocks.scope_version(td, "p", code_id=cid)
                try:
                    _save(td, cid, f"writer-{i}", base, f"w{i}")
                    with lock:
                        done.append(i)
                    return
                except cs.StaleContentError:
                    continue

        with ThreadPoolExecutor(max_workers=N) as ex:
            list(ex.map(writer, range(N)))

        assert sorted(done) == list(range(N))
        # Every successful save advanced the version by exactly one.
        assert cb_blocks.scope_version(td, "p", code_id=cid) == N
        # And one snapshot per successful save.
        snaps = snapshots.list_snapshots(td, "p", "code", cid)
        assert len(snaps) == N
        # Final live state is well-formed (single definition, unique ordinal).
        live = cb_blocks.list_blocks(td, "p", code_id=cid)
        assert len(live) == 1
        assert len({b["ordinal"] for b in live}) == len(live)


# --------------------------------------------------------------------------
# Snapshot / revision invariants
# --------------------------------------------------------------------------

class TestRevisionInvariants:
    def test_one_snapshot_and_monotonic_content_revision(self, td):
        cid = _code(td, "rev code")
        r1 = _save(td, cid, "one", 0, "a")
        r2 = _save(td, cid, "two", 1, "a")
        r3 = _save(td, cid, "three", 2, "a")
        revs = [r1["content_revision"], r2["content_revision"],
                r3["content_revision"]]
        assert revs == sorted(revs) and len(set(revs)) == 3
        snaps = snapshots.list_snapshots(td, "p", "code", cid)
        assert len(snaps) == 3

    def test_semantic_revision_only_bumps_on_semantic_edit(self, td):
        cid = _code(td, "sem code")
        base_sem = cb_blocks.current_sem_revision(td, "p")
        # definition is a semantic block type -> first save is semantic
        r1 = _save(td, cid, "meaning v1", 0, "a")
        assert r1["semantic"] is True
        assert r1["sem_revision"] > base_sem
        # adding a non-semantic example alongside, keeping the definition,
        # is a cosmetic edit -> sem_revision unchanged
        r2 = cs.save_scope(
            td, project="p", scope_kind="code", scope_id=cid,
            blocks_in=[{"block_type": "definition", "body_md": "meaning v1"},
                       {"block_type": "example", "body_md": "e.g. this"}],
            base_version=1, actor="a")
        assert r2["semantic"] is False
        assert r2["sem_revision"] == r1["sem_revision"]
        # content_revision still advanced (cache-bust on every edit)
        assert r2["content_revision"] > r1["content_revision"]

    def test_minor_override_suppresses_semantic(self, td):
        cid = _code(td, "minor code")
        _save(td, cid, "meaning v1", 0, "a")
        sem_after_first = cb_blocks.current_sem_revision(td, "p")
        r = _save(td, cid, "meaning v2 reworded", 1, "a", minor=True)
        assert r["semantic"] is False
        assert cb_blocks.current_sem_revision(td, "p") == sem_after_first


# --------------------------------------------------------------------------
# Reload round-trip (serialization drift guard at the service layer)
# --------------------------------------------------------------------------

class TestReloadRoundTrip:
    def test_saved_blocks_survive_markdown_round_trip(self, td):
        cid = _code(td, "round code")
        saved = cs.save_scope(
            td, project="p", scope_kind="code", scope_id=cid,
            blocks_in=[
                {"block_type": "definition", "body_md": "the meaning"},
                {"block_type": "use_when", "body_md": "include these"},
                {"block_type": "example", "body_md": "> a quoted example"},
                {"block_type": "custom", "custom_label": "Field Notes",
                 "body_md": "observed in the wild"},
            ],
            base_version=0, actor="a")["blocks"]
        # reload from DB -> serialize -> re-parse; must be a fixed point on
        # the persisted fields.
        reloaded = cb_blocks.list_blocks(td, "p", code_id=cid)
        md = blocks_to_markdown(reloaded)
        reparsed = markdown_to_blocks(md)

        def sig(bl):
            return [(b.get("block_type"), b.get("custom_label") or None,
                     (b.get("body_md") or "").strip()) for b in bl]

        assert sig(reparsed) == sig(saved)


# --------------------------------------------------------------------------
# Proposal-vs-direct race
# --------------------------------------------------------------------------

class TestProposalRace:
    def test_confirm_after_scope_advanced_is_rejected(self, td):
        cid = _code(td, "proposal code")
        # author a proposal against the empty scope (base 0)
        prop = cs.propose_content_edit(
            td, project="p", scope_kind="code", scope_id=cid,
            blocks_in=_def("proposed meaning"), base_version=0, actor="bob")
        assert prop  # a proposal id/record
        # meanwhile a direct edit advances the scope to version 1
        _save(td, cid, "direct meaning", 0, "alice")
        # confirming the now-stale proposal must NOT clobber the newer content
        with pytest.raises(cs.StaleContentError):
            cs.apply_content_proposal(
                td, project="p",
                payload={"scope_kind": "code", "scope_id": cid,
                         "blocks": _def("proposed meaning"),
                         "base_version": 0},
                actor="admin")
        assert cb_blocks.list_blocks(
            td, "p", code_id=cid)[0]["body_md"] == "direct meaning"

    def test_proposal_applies_cleanly_when_scope_unchanged(self, td):
        cid = _code(td, "clean proposal code")
        cs.propose_content_edit(
            td, project="p", scope_kind="code", scope_id=cid,
            blocks_in=_def("proposed meaning"), base_version=0, actor="bob")
        out = cs.apply_content_proposal(
            td, project="p",
            payload={"scope_kind": "code", "scope_id": cid,
                     "blocks": _def("proposed meaning"), "base_version": 0},
            actor="admin")
        assert out["scope_version"] == 1
        assert cb_blocks.list_blocks(
            td, "p", code_id=cid)[0]["body_md"] == "proposed meaning"
