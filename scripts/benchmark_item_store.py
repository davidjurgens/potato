"""
Measure what the paged item store actually costs and saves.

The claim in ``potato/item_store.py`` is that the payload is the whole of the
per-item memory cost and that paging it out trades RAM for a per-access query.
This measures both halves, on the two item shapes the earlier Wave 7.1
measurement used, so the module's documentation cannot drift from reality.

    python scripts/benchmark_item_store.py [--items 100000]
"""

import argparse
import gc
import os
import shutil
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from potato.item_state_management import ItemStateManager  # noqa: E402

SHAPES = {
    "vision": lambda i: {"id": f"img_{i}",
                         "image_url": f"https://example.invalid/images/{i:08d}.jpg",
                         "split": "train"},
    # ~540 unique characters, matching the Wave 7.1 text figure.
    "text": lambda i: {"id": f"doc_{i}",
                       "text": f"{i:06d} " + ("lorem ipsum dolor sit amet " * 20)},
}


def build(config, shape, count):
    """
    Returns steady-state resident bytes, not peak.

    Peak folds in every transient allocation the build makes — JSON encoding
    buffers, sqlite page buffers — which are freed immediately and are not what
    a long-running server holds. Reporting peak would credit the in-memory
    store for garbage and understate the difference.
    """
    gc.collect()
    tracemalloc.start()
    manager = ItemStateManager(config)
    start = time.perf_counter()
    for index in range(count):
        manager.add_item(f"item_{index}", SHAPES[shape](index))
    build_seconds = time.perf_counter() - start
    gc.collect()
    resident, _peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return manager, resident, build_seconds


def measure(manager, count):
    """A serving read (one item) and a full report pass (every item)."""
    start = time.perf_counter()
    for index in range(0, count, max(1, count // 1000)):
        manager.get_item(f"item_{index}").get_data()
    serve_seconds = time.perf_counter() - start

    start = time.perf_counter()
    total = 0
    for _iid, item in manager.iter_items():
        total += len(item.get_data())
    scan_seconds = time.perf_counter() - start
    return serve_seconds, scan_seconds, total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=100_000)
    parser.add_argument("--cache-size", type=int, default=2048)
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="potato-itemstore-")
    try:
        print(f"{args.items:,} items, paged cache {args.cache_size:,}\n")
        header = (f"{'shape':8} {'backend':8} {'resident MB':>11} {'bytes/item':>11} "
                  f"{'build s':>8} {'serve s':>8} {'scan s':>8}")
        print(header)
        print("-" * len(header))
        for shape in SHAPES:
            for backend in ("memory", "paged"):
                config = {}
                if backend == "paged":
                    config = {"item_store": {
                        "backend": "paged", "cache_size": args.cache_size,
                        "path": os.path.join(workdir, f"{shape}.sqlite")}}
                manager, resident, build_seconds = build(config, shape, args.items)
                serve, scan, _ = measure(manager, args.items)
                print(f"{shape:8} {backend:8} {resident / 1e6:9.1f} "
                      f"{resident / args.items:11.0f} {build_seconds:8.2f} "
                      f"{serve:8.3f} {scan:8.2f}")
                del manager
                gc.collect()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
