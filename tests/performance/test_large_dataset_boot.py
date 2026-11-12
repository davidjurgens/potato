"""Large-dataset boot / lookup benchmark (Track D).

Backs the documented scaling claims and guards against regressions:
  * loading tens of thousands of items completes within a generous CI bound,
  * item lookup is O(1) (a hash-indexed OrderedDict, not a list scan),
  * (optional) resident memory stays within a documented ceiling.

The item count and RSS ceiling are env-tunable so the test stays fast in CI but
can reproduce the release-note figures locally:

    POTATO_BENCH_N=50000 POTATO_BENCH_RSS=1 pytest tests/performance -q

Cross-referenced from docs/deployment/scaling.md.
"""

import os
import time

import pytest

from tests.helpers.test_utils import create_test_directory, cleanup_test_directory
from potato.item_state_management import init_item_state_manager


N_ITEMS = int(os.environ.get("POTATO_BENCH_N", "20000"))
LOAD_BUDGET_S = float(os.environ.get("POTATO_BENCH_LOAD_S", "60"))
RSS_CEILING_MB = float(os.environ.get("POTATO_BENCH_RSS_MB", "1200"))


def _reset_item_manager():
    import potato.item_state_management
    potato.item_state_management.ITEM_STATE_MANAGER = None


@pytest.fixture(scope="module")
def large_manager():
    _reset_item_manager()
    test_dir = create_test_directory("large_dataset_boot")
    config = {
        "task_dir": test_dir,
        "output_annotation_dir": test_dir,
        "max_annotations_per_item": -1,
        "item_properties": {"id_key": "id", "text_key": "text"},
    }
    ism = init_item_state_manager(config)
    items = {
        str(i): {"id": str(i), "text": f"synthetic annotation item number {i}"}
        for i in range(N_ITEMS)
    }
    start = time.perf_counter()
    ism.add_items(items)
    elapsed = time.perf_counter() - start
    yield ism, elapsed
    _reset_item_manager()
    cleanup_test_directory(test_dir)


def test_load_completes_within_budget(large_manager):
    ism, elapsed = large_manager
    assert len(ism.instance_id_to_instance) == N_ITEMS
    assert elapsed < LOAD_BUDGET_S, (
        f"Loading {N_ITEMS} items took {elapsed:.1f}s (budget {LOAD_BUDGET_S}s)"
    )


def test_lookup_is_constant_time(large_manager):
    ism, _ = large_manager
    # Sample lookups spread across the dataset; O(1) dict access means the
    # per-lookup cost does not grow with position in the dataset.
    probe_ids = [str(i) for i in range(0, N_ITEMS, max(1, N_ITEMS // 1000))]
    start = time.perf_counter()
    for pid in probe_ids:
        item = ism.get_item(pid)
        assert item is not None
    per_lookup_us = (time.perf_counter() - start) / len(probe_ids) * 1e6
    # A hash lookup over 20k+ items should be well under 100µs each; a linear
    # scan would blow far past this. Generous bound to avoid CI flakiness.
    assert per_lookup_us < 100, f"{per_lookup_us:.1f}µs/lookup suggests non-O(1) access"


def test_first_and_last_ids_equally_fast(large_manager):
    ism, _ = large_manager
    # If lookup were a list scan, the last id would be dramatically slower than
    # the first. With a dict they are indistinguishable.
    def _time_lookup(pid, reps=2000):
        start = time.perf_counter()
        for _ in range(reps):
            ism.get_item(pid)
        return time.perf_counter() - start

    first = _time_lookup("0")
    last = _time_lookup(str(N_ITEMS - 1))
    # Allow generous slack; the point is "same order of magnitude", not linear.
    assert last < first * 10 + 0.05


@pytest.mark.skipif(
    os.environ.get("POTATO_BENCH_RSS") != "1",
    reason="RSS ceiling check is opt-in (POTATO_BENCH_RSS=1); CI memory varies.",
)
def test_rss_within_ceiling(large_manager):
    ism, _ = large_manager
    try:
        import psutil
    except ImportError:
        pytest.skip("psutil not installed")
    rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    assert rss_mb < RSS_CEILING_MB, f"RSS {rss_mb:.0f}MB exceeds {RSS_CEILING_MB}MB"
