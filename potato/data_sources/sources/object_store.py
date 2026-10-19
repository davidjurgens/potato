"""
Shared base for object-store data sources: S3, Google Cloud Storage, Azure Blob.

A source reads either one object (``key``) or every data file under a prefix
(``prefix``). In prefix mode it can also be polled while the study runs
(``live_ingestion``): each object that appears under the prefix adds its rows
to the item pool.

Live ingestion here is append-only and cursor-based like the database source:

* the cursor is the object's last-modified time (UTC);
* the tie-breaker is ``"<key>\\0<row index>"`` with the index zero-padded, so
  rows sort by (modified, key, index) and a batch that stops in the middle of
  an object resumes at the next row of that object.

An object uploaded again gets a new modified time, so its rows are read again;
the worker's id dedupe drops the ones already in the pool. Changing a row in
place is therefore not picked up -- write new objects instead.

Subclasses implement three methods: :meth:`_list_objects`, :meth:`_read_object`
and :meth:`_uri`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from potato.data_sources.base import DataSource, LiveRow, SourceConfig

logger = logging.getLogger(__name__)

#: Objects under a prefix that are read; anything else (images, READMEs) is skipped.
DATA_EXTENSIONS = (".json", ".jsonl", ".ndjson", ".csv", ".tsv")
_SEP = "\0"


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    modified: datetime
    size: int = 0


def utc(value: Any) -> datetime:
    """A provider timestamp as an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def tiebreak(key: str, index: int, total: Optional[int] = None) -> str:
    """``"<key>\\0<index>"``, plus ``"\\0<rows in the object>"`` in key-ordered listing."""
    mark = f"{key}{_SEP}{index:08d}"
    return mark if total is None else f"{mark}{_SEP}{total:08d}"


def parse_tiebreak(value: Optional[str]) -> Tuple[Optional[str], int, Optional[int]]:
    """``(key, row index, rows in the object or None)``."""
    if not value or _SEP not in str(value):
        return (str(value) if value else None), -1, None
    parts = str(value).split(_SEP)
    try:
        if len(parts) >= 3:
            return _SEP.join(parts[:-2]), int(parts[-2]), int(parts[-1])
        return parts[0], int(parts[1]), None
    except ValueError:
        return _SEP.join(parts[:-1]), -1, None


def split_tiebreak(value: Optional[str]) -> Tuple[Optional[str], int]:
    key, index, _total = parse_tiebreak(value)
    return key, index


class ObjectStoreSource(DataSource):
    """Read one object or a prefix of objects; poll a prefix for new ones."""

    #: The config key naming the bucket (``container`` for Azure).
    BUCKET_KEY = "bucket"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        from potato.data_sources.live_ingestion import LiveIngestionConfig

        raw = config.config
        self._bucket = raw.get(self.BUCKET_KEY, "")
        self._key = raw.get("key", "")
        self._prefix = raw.get("prefix", "")
        self._live = LiveIngestionConfig.from_dict(raw.get("live_ingestion"))
        self._cached_data: Optional[List[Dict[str, Any]]] = None

    # -- what subclasses provide ---------------------------------------------

    def _list_objects(self, prefix: str, start_after: Optional[str] = None) -> List[ObjectInfo]:
        """Objects under ``prefix``; with ``start_after``, only keys sorting after it."""
        raise NotImplementedError

    def _read_object(self, key: str) -> Tuple[bytes, str]:
        """``(content, content_type)``."""
        raise NotImplementedError

    def _uri(self, key: str) -> str:
        raise NotImplementedError

    # -- shared --------------------------------------------------------------

    def get_source_id(self) -> str:
        return self._source_id

    @property
    def live_config(self):
        """The parsed ``live_ingestion`` block for this source."""
        return self._live

    def validate_config(self) -> List[str]:
        errors = []
        kind = getattr(self.source_type, "value", self.source_type)  # enum or plain string
        if not self._bucket:
            errors.append(f"'{self.BUCKET_KEY}' is required for a {kind} source")
        if not self._key and not self._prefix:
            errors.append(f"a {kind} source needs 'key' (one object) or 'prefix' (every "
                          f"data file under it)")
        if self._key and self._prefix:
            errors.append(f"a {kind} source takes 'key' or 'prefix', not both")
        if self._live.enabled:
            if not self._prefix:
                errors.append("live_ingestion needs 'prefix': new rows arrive as new objects "
                              "under it")
            errors.extend(f"live_ingestion.{e}" for e in self._live.validate())
        return errors

    def _parse(self, key: str, content: bytes, content_type: str = "") -> List[Dict[str, Any]]:
        from potato.data_sources.parsing import format_for, parse_records
        fmt = format_for(key[:-len(".ndjson")] + ".jsonl" if key.endswith(".ndjson") else key)
        if fmt is None:
            if "ndjson" in content_type or "json" in content_type:
                fmt = "jsonl"
            elif "tab-separated" in content_type:
                fmt = "tsv"
            elif "csv" in content_type:
                fmt = "csv"
        text = content.decode("utf-8-sig")
        records = parse_records(text, fmt, self._uri(key))
        if not records and fmt is None:
            raise ValueError(f"Could not parse content from {self._uri(key)}")
        return records

    def _data_objects(self, start_after: Optional[str] = None) -> List[ObjectInfo]:
        listed = (self._list_objects(self._prefix, start_after=start_after)
                  if start_after is not None else self._list_objects(self._prefix))
        return [o for o in listed if o.key.lower().endswith(DATA_EXTENSIONS)
                and (start_after is None or o.key > start_after)]

    def _fetch_data(self) -> List[Dict[str, Any]]:
        if self._key:
            content, content_type = self._read_object(self._key)
            return self._parse(self._key, content, content_type)
        items: List[Dict[str, Any]] = []
        for obj in sorted(self._data_objects(), key=lambda o: o.key):
            content, content_type = self._read_object(obj.key)
            items.extend(self._parse(obj.key, content, content_type))
        return items

    def read_items(self, start: int = 0, count: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        if self._cached_data is None:
            self._cached_data = self._fetch_data()
        items = self._cached_data[start:]
        if count is not None:
            items = items[:count]
        yield from items

    def get_total_count(self) -> Optional[int]:
        if self._cached_data is None:
            try:
                self._cached_data = self._fetch_data()
            except Exception as e:  # noqa: BLE001 - reported, not raised
                logger.error("Error fetching %s: %s", self._source_id, e)
                return None
        return len(self._cached_data)

    def supports_partial_reading(self) -> bool:
        return True

    def refresh(self) -> bool:
        self._cached_data = None
        return True

    # -- live ----------------------------------------------------------------

    def supports_live_ingestion(self) -> bool:
        return bool(self._live.enabled and self._prefix)

    def read_since(self, cursor: Optional[Any] = None, tiebreaker: Optional[str] = None,
                   limit: Optional[int] = None) -> Iterator[LiveRow]:
        """Rows of objects under the prefix ordered after ``(cursor, tiebreaker)``."""
        if not self.supports_live_ingestion():
            raise RuntimeError(f"Source {self.source_id} does not have live_ingestion "
                               f"enabled with a prefix")
        batch = int(limit or self._live.batch_size)
        if self._live.listing == "after_last_key":
            yield from self._read_since_by_key(cursor, tiebreaker, batch)
            return
        try:
            after = utc(cursor) if cursor is not None else None
        except ValueError:
            # A key cursor left by after_last_key listing: start from the
            # beginning once; the id dedupe drops what the pool has.
            after = None
            tiebreaker = None
        after_key, after_index, after_total = parse_tiebreak(tiebreaker)
        horizon = None
        if self._live.safety_lag_seconds > 0:
            from datetime import timedelta
            horizon = datetime.now(timezone.utc) - timedelta(seconds=self._live.safety_lag_seconds)

        objects = sorted(self._data_objects(), key=lambda o: (utc(o.modified), o.key))
        produced = 0
        for obj in objects:
            modified = utc(obj.modified)
            if horizon is not None and modified > horizon:
                break
            if after is not None:
                if modified < after:
                    continue
                if modified == after:
                    if after_key is None or obj.key < after_key:
                        continue
                    if obj.key == after_key and after_total is not None \
                            and after_index + 1 >= after_total:
                        continue  # read to its end (a key-ordered cursor)
            first = after_index + 1 if (after is not None and modified == after
                                        and obj.key == after_key) else 0
            content, content_type = self._read_object(obj.key)
            rows = self._parse(obj.key, content, content_type)
            for index in range(first, len(rows)):
                item = rows[index]
                mark = tiebreak(obj.key, index)
                yield LiveRow(item=item, cursor_value=modified, row_id=mark, tiebreak_value=mark)
                produced += 1
                if produced >= batch:
                    return

    def _read_since_by_key(self, cursor: Optional[Any], tiebreaker: Optional[str],
                           batch: int) -> Iterator[LiveRow]:
        """Key-ordered polling: list only the keys after the last one read.

        For buckets whose new objects always sort after the old ones (keys
        that start with a timestamp or a sequence number). An object written
        under a key that sorts earlier is never seen. The tie-breaker carries
        the object's row count, so an object read to its end is not fetched
        again, and one a batch stopped inside is resumed at its next row.

        The cursor is the object's KEY, not its modified time, so the worker's
        cursor comparisons follow key order. A cursor with no tie-breaker (an
        ``initial_cursor``) means "start after this key". A time cursor left by
        the full listing mode is ignored: the next poll lists the prefix from
        the start once, and the id dedupe drops what is already in the pool.
        """
        after_key, after_index, total = parse_tiebreak(tiebreaker)
        if after_key is None and isinstance(cursor, str) and cursor:
            after_key, after_index, total = cursor, 0, 1  # that key counts as read
        horizon = None
        if self._live.safety_lag_seconds > 0:
            from datetime import timedelta
            horizon = datetime.now(timezone.utc) - timedelta(seconds=self._live.safety_lag_seconds)

        pending: List[Tuple[ObjectInfo, int]] = []
        if after_key is not None and (total is None or after_index + 1 < total):
            # A batch stopped inside this object, or an older cursor without a
            # row count: read it again from the next row.
            same = [o for o in self._list_objects(after_key) if o.key == after_key]
            if same:
                pending.append((same[0], after_index + 1))
        pending.extend((o, 0) for o in sorted(self._data_objects(start_after=after_key),
                                              key=lambda o: o.key))
        produced = 0
        for obj, first in pending:
            modified = utc(obj.modified)
            if horizon is not None and modified > horizon:
                break  # keys after it may be older, but must not be read past it
            content, content_type = self._read_object(obj.key)
            rows = self._parse(obj.key, content, content_type)
            for index in range(first, len(rows)):
                mark = tiebreak(obj.key, index, len(rows))
                yield LiveRow(item=rows[index], cursor_value=obj.key, row_id=tiebreak(obj.key, index),
                              tiebreak_value=mark)
                produced += 1
                if produced >= batch:
                    return

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update({self.BUCKET_KEY: self._bucket, "key": self._key, "prefix": self._prefix,
                       "cached": self._cached_data is not None,
                       "live": self.supports_live_ingestion()})
        return status

    def close(self) -> None:
        self._cached_data = None
