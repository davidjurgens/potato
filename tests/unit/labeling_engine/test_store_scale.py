"""
The store at the design scale: one million predictions in one study.

Run by hand (about 10 s on a laptop; writes ~150 MB under tmp_path):

    POTATO_ENGINE_SCALE=1 pytest tests/unit/labeling_engine/test_store_scale.py -s
"""

import os
import time

import pytest

from potato.labeling_engine.model import Prediction, SourceVersion
from potato.labeling_engine.store import EngineStore
from potato.persistence import clear_db_cache

pytestmark = pytest.mark.skipif(
    os.environ.get("POTATO_ENGINE_SCALE") != "1",
    reason="set POTATO_ENGINE_SCALE=1 to run the 1M-row check")

N = 1_000_000


@pytest.mark.timeout(600)
def test_one_million_predictions(tmp_path):
    clear_db_cache()
    store = EngineStore(str(tmp_path))
    sv = store.register_source_version(
        SourceVersion(source_id="s", kind="fixture"))

    t0 = time.time()
    batch = []
    for k in range(N):
        batch.append(Prediction(f"i{k}", "label", sv, k % 3,
                                raw_conf=(k % 100) / 100))
        if len(batch) == 50_000:
            store.add_predictions(batch)
            batch = []
    store.add_predictions(batch)
    insert_s = time.time() - t0

    t0 = time.time()
    some = store.current_predictions("label", sv, item_ids=[f"i{k}" for k in range(0, N, 1000)])
    lookup_s = time.time() - t0

    t0 = time.time()
    n_high = store.conn.execute(
        "SELECT COUNT(*) FROM prediction WHERE source_version_id = ? AND schema_name = ?"
        " AND raw_conf >= 0.9", (sv, "label")).fetchone()[0]
    agg_s = time.time() - t0

    print(f"\ninsert {N:,}: {insert_s:.1f}s; 1,000 keyed lookups: {lookup_s:.2f}s; "
          f"aggregate: {agg_s:.2f}s")
    assert len(some) == 1000
    assert n_high == N // 10
    # Budgets for a laptop: the runner commits per chunk, so insert speed
    # bounds throughput; the dashboard and planner use keyed lookups and
    # aggregates, never a Python scan.
    assert insert_s < 240
    assert lookup_s < 5
    assert agg_s < 10
    clear_db_cache()
