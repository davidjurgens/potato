"""
Where item payloads live.

``ItemStateManager`` used to *be* an ``OrderedDict`` of every item, and roughly
sixty call sites reached into that dict by name. This module is the seam that
was missing: one narrow protocol the manager delegates to, so the question "are
all the payloads in RAM?" has an answer other than "yes, always".

## What the measurement says, so nobody turns this on for the wrong reason

Steady-state resident bytes per item, 50k items, from
``scripts/benchmark_item_store.py``:

| Item shape | memory | paged | 1M items, memory | 1M items, paged |
|---|---|---|---|---|
| vision (`image_url` + two fields) | 932 B | 675 B | 0.93 GB | 0.68 GB |
| text (~540 unique chars) | 1430 B | 695 B | 1.43 GB | 0.70 GB |

**Paging saves 28% on vision items and 51% on text, not an order of
magnitude**, and that is the finding rather than a disappointment: once the
payload is gone, what remains is the resident ``Item`` and the manager's own id
bookkeeping, and those do not page. Anyone hoping to hold 50M items in 2 GB
should read that table before configuring anything.

The costs, same benchmark: building the corpus takes ~2.5× as long, a full
scan ~6×, and a single item read goes from ~1 µs to ~6 µs — irrelevant against
a request, and the reason ``iter_items`` batches.

So :class:`MemoryItemStore` stays the default, and :class:`PagedItemStore` is
opt-in. It earns its keep where half a gigabyte matters — Open-Images scale is
about 9M items, so ~8.4 GB resident against ~6.1 GB paged — and buys a slower
server and nothing else below a million.

The measurement also paid for itself elsewhere: it showed that three
unconditionally-constructed empty dicts on every ``Item`` were half the cost of
a paged item, which is why they are now created on first use. That change took
**every** deployment's vision items from 1124 to 932 bytes, default backend and
no config, which is a larger absolute win than this module's.

## Only the payload is paged, and this is not a detail

An ``Item`` is a payload plus mutable state: ``metadata`` (the overlap
sampler's sample flag, the automation engine's ``triage_priority``, adaptive
boost's ``required_annotations``, the triage scorer's fields), ``labels`` and
``span_annotations``. That state is written *through the object* —
``item.add_metadata(...)`` at ``overlap_sampler.py:82`` mutates the instance the
store handed out, and expects it to stick.

So a store that evicted whole ``Item`` objects and rebuilt them on demand would
silently discard every one of those writes, and the failure would surface as a
sampling flag that stopped working under memory pressure — intermittent,
load-dependent, and effectively undebuggable. Instead:

- the ``Item`` object itself is always resident, and its identity is stable, so
  a caller who holds one and mutates it is writing to the real thing;
- only ``item_data`` — the immutable payload, and the whole of the measured
  cost — is evictable.

A resident ``Item`` with no payload is small: an id and three usually-empty
dicts, about 400 bytes against the 657–1183 the payload costs.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: How many payloads a paged store keeps materialized. 2048 vision items is
#: ~1.3 MB, and the working set of a serving request is one item plus whatever
#: an admin report is iterating, so the cache exists to make *iteration* cheap
#: rather than to hold the corpus.
DEFAULT_CACHE_SIZE = 2048

#: Rows per round trip when iterating. Large enough that a million-item report
#: is not a million queries; small enough that a batch is not the corpus.
ITER_BATCH = 512


class ItemStore:
    """
    The protocol ``ItemStateManager`` talks to.

    Deliberately narrow. Every method here corresponds to an access pattern
    that existed against the raw dict; nothing was added speculatively, and
    anything a backend cannot do cheaply (arbitrary ``.values()``, membership
    over payloads) is absent so that it cannot be written by accident.
    """

    def __len__(self) -> int:
        raise NotImplementedError

    def __contains__(self, item_id: str) -> bool:
        raise NotImplementedError

    def ids(self) -> List[str]:
        """Every id, in insertion order."""
        raise NotImplementedError

    def get(self, item_id: str):
        """The ``Item``, or None. Same object every time — see the module note."""
        raise NotImplementedError

    def put(self, item_id: str, item) -> None:
        raise NotImplementedError

    def pop(self, item_id: str):
        raise NotImplementedError

    def iter_items(self) -> Iterator[Tuple[str, Any]]:
        """
        ``(id, Item)`` pairs, in order, without materializing the corpus.

        This is the seam that makes paging possible at all: ``.items()`` on a
        dict builds the whole list first, so every admin loop written against
        it was a hard floor on memory no backend could lower.
        """
        raise NotImplementedError

    def reorder(self, ids) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    # -- payload hooks, used by Item's lazy accessor --------------------------

    def load_payload(self, item_id: str):
        """The item's data dict. In-memory stores never need this."""
        raise NotImplementedError

    def store_payload(self, item_id: str, payload) -> None:
        raise NotImplementedError

    @property
    def pages_payloads(self) -> bool:
        """True when ``item_data`` may be absent and must be faulted in."""
        return False


class MemoryItemStore(ItemStore):
    """
    Every item resident. The default, and what Potato has always done.

    A thin wrapper rather than a rewrite: the point is that the manager stops
    depending on the container being a dict, not that the dict was wrong.
    """

    def __init__(self):
        self._items: "OrderedDict[str, Any]" = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def ids(self) -> List[str]:
        return list(self._items.keys())

    def get(self, item_id: str):
        return self._items.get(item_id)

    def put(self, item_id: str, item) -> None:
        self._items[item_id] = item

    def pop(self, item_id: str):
        return self._items.pop(item_id, None)

    def iter_items(self) -> Iterator[Tuple[str, Any]]:
        # A copy of the *keys*, not of the items: callers iterate while
        # background ingestion adds items, and mutating an OrderedDict during
        # iteration raises. Copying keys is cheap; copying items is the cost
        # this whole module exists to avoid.
        for item_id in list(self._items.keys()):
            item = self._items.get(item_id)
            if item is not None:
                yield item_id, item

    def reorder(self, ids) -> None:
        for item_id in ids:
            if item_id in self._items:
                self._items.move_to_end(item_id)

    def clear(self) -> None:
        self._items.clear()

    def as_mapping(self) -> "OrderedDict[str, Any]":
        """
        The underlying dict, for the deprecated ``instance_id_to_instance``.

        Present so the compatibility property is honest about being a view of
        real state rather than a rebuilt copy that would silently drop writes.
        """
        return self._items


class PagedItemStore(ItemStore):
    """
    Payloads on disk, ``Item`` objects and an LRU of payloads in memory.

    The backing file is a **cache**, not project state: it is rebuilt from the
    data files on every boot and can be deleted at any time. It therefore lives
    beside the output directory as ``.item_cache.sqlite`` rather than in
    ``project.sqlite``, which holds things that cannot be regenerated and gets
    backed up accordingly.
    """

    def __init__(self, path: str, cache_size: int = DEFAULT_CACHE_SIZE):
        self.path = path
        self.cache_size = max(1, int(cache_size))
        self._items: "OrderedDict[str, Any]" = OrderedDict()
        self._payloads: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.RLock()
        self._connections: Dict[int, sqlite3.Connection] = {}
        self._init_db()

    # -- database ------------------------------------------------------------

    def _init_db(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        # A stale cache from a previous run describes a corpus that may no
        # longer exist. Rebuilding is cheap next to serving a payload that
        # belongs to a deleted item.
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError as exc:
                logger.warning("Could not clear the item cache at %s: %s",
                               self.path, exc)
        connection = self._connect()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS payloads ("
            " item_id TEXT PRIMARY KEY, position INTEGER, payload TEXT)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS payloads_position ON payloads(position)")
        connection.commit()

    def _connect(self) -> sqlite3.Connection:
        """
        One connection per thread.

        sqlite3 objects are not safe to share across threads, and Potato serves
        from several — the assignment path, the directory watcher, background
        workers. A single connection guarded by a lock would serialize every
        payload read behind every other one.
        """
        key = threading.get_ident()
        connection = self._connections.get(key)
        if connection is None:
            connection = sqlite3.connect(self.path, check_same_thread=False)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=OFF")  # a cache; a lost
            # write costs a rebuild, and durability here buys nothing.
            self._connections[key] = connection
        return connection

    # -- protocol ------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def ids(self) -> List[str]:
        return list(self._items.keys())

    def get(self, item_id: str):
        return self._items.get(item_id)

    def put(self, item_id: str, item) -> None:
        with self._lock:
            position = len(self._items)
            self._items[item_id] = item
            payload = item.__dict__.get("_item_data")
            self.store_payload(item_id, payload, position=position)
            # Detach the payload from the object: from here it is reached
            # through the lazy accessor, which is what makes eviction possible.
            item.__dict__["_item_data"] = None
            item.__dict__["_store"] = self

    def pop(self, item_id: str):
        with self._lock:
            item = self._items.pop(item_id, None)
            self._payloads.pop(item_id, None)
            connection = self._connect()
            connection.execute("DELETE FROM payloads WHERE item_id = ?",
                               (item_id,))
            connection.commit()
            return item

    def iter_items(self) -> Iterator[Tuple[str, Any]]:
        """
        Warm the cache a batch at a time, so a full pass is O(batch) resident.

        The payloads are pre-loaded rather than faulted in one query per item
        because a million-item report otherwise becomes a million round trips —
        the same mistake as materializing, spread out over time.
        """
        ids = self.ids()
        for start in range(0, len(ids), ITER_BATCH):
            batch = ids[start:start + ITER_BATCH]
            self._warm(batch)
            for item_id in batch:
                item = self._items.get(item_id)
                if item is not None:
                    yield item_id, item

    def reorder(self, ids) -> None:
        with self._lock:
            for item_id in ids:
                if item_id in self._items:
                    self._items.move_to_end(item_id)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._payloads.clear()
            connection = self._connect()
            connection.execute("DELETE FROM payloads")
            connection.commit()

    @property
    def pages_payloads(self) -> bool:
        return True

    # -- payloads ------------------------------------------------------------

    def load_payload(self, item_id: str):
        with self._lock:
            if item_id in self._payloads:
                self._payloads.move_to_end(item_id)
                return self._payloads[item_id]
        row = self._connect().execute(
            "SELECT payload FROM payloads WHERE item_id = ?",
            (item_id,)).fetchone()
        payload = json.loads(row[0]) if row and row[0] is not None else None
        with self._lock:
            self._remember(item_id, payload)
        return payload

    def store_payload(self, item_id: str, payload,
                      position: Optional[int] = None) -> None:
        encoded = None if payload is None else json.dumps(payload)
        connection = self._connect()
        if position is None:
            connection.execute(
                "UPDATE payloads SET payload = ? WHERE item_id = ?",
                (encoded, item_id))
        else:
            connection.execute(
                "INSERT OR REPLACE INTO payloads (item_id, position, payload) "
                "VALUES (?, ?, ?)", (item_id, position, encoded))
        connection.commit()
        with self._lock:
            self._remember(item_id, payload)

    def _warm(self, item_ids) -> None:
        missing = [i for i in item_ids if i not in self._payloads]
        if not missing:
            return
        placeholders = ",".join("?" * len(missing))
        rows = self._connect().execute(
            f"SELECT item_id, payload FROM payloads WHERE item_id IN ({placeholders})",
            missing).fetchall()
        with self._lock:
            for item_id, encoded in rows:
                self._remember(item_id,
                               json.loads(encoded) if encoded is not None else None)

    def _remember(self, item_id: str, payload) -> None:
        """Caller holds the lock."""
        self._payloads[item_id] = payload
        self._payloads.move_to_end(item_id)
        while len(self._payloads) > self.cache_size:
            self._payloads.popitem(last=False)

    def as_mapping(self):
        """
        The resident ``Item`` objects.

        Payload access through this mapping still faults in per item, so the
        deprecated ``instance_id_to_instance`` keeps working under a paged
        store — slowly, which is the correct incentive.
        """
        return self._items


def build_store(config: Optional[Dict[str, Any]] = None) -> ItemStore:
    """
    The store a project's config asks for.

    Defaults to memory. ``item_store.backend: paged`` opts in; anything else is
    a warning and the default, because falling back to a working server beats
    refusing to start over a performance setting.
    """
    settings = ((config or {}).get("item_store") or {})
    backend = str(settings.get("backend") or "memory").lower()
    if backend in ("memory", "", "default"):
        return MemoryItemStore()
    if backend == "paged":
        path = settings.get("path")
        if not path:
            output = (config or {}).get("output_annotation_dir") or "."
            path = os.path.join(output, ".item_cache.sqlite")
        store = PagedItemStore(path,
                               cache_size=int(settings.get("cache_size")
                                              or DEFAULT_CACHE_SIZE))
        logger.info("Item payloads are paged to %s (cache %d items)",
                    path, store.cache_size)
        return store
    logger.warning("Unknown item_store.backend %r; using the in-memory store.",
                   backend)
    return MemoryItemStore()
