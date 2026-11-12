"""Backup sink: an S3 bucket, or anything that speaks the S3 API.

``endpoint_url`` points it at Cloudflare R2, Backblaze B2, MinIO and the like.
Layout under ``prefix``::

    <prefix>/annotations/<path inside the output directory>
    <prefix>/_databases/project.sqlite

Credentials come from the sink's ``access_key_id`` / ``secret_access_key``,
then ``POTATO_S3_ACCESS_KEY_ID`` / ``POTATO_S3_SECRET_ACCESS_KEY``, then
boto3's own chain (instance role, ``AWS_*`` variables, profile). Use a key
scoped to the one bucket: it sits in the server's environment.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

from potato.server_utils.backup import (
    REMOTE_DB_DIR,
    output_dir,
    restorable,
    safe_join,
    snapshot_dir,
)

logger = logging.getLogger(__name__)

ANNOTATIONS_DIR = "annotations"


class S3Sink:
    def __init__(self, spec: Dict[str, Any], config: Dict[str, Any]):
        self.spec = spec
        self.config = config
        self.bucket = spec.get("bucket")
        self.prefix = str(spec.get("prefix") or "").strip("/")
        self._client = None
        # rel key -> (size, mtime_ns) at the last successful upload, so a cycle
        # only sends what changed.
        self._sent: Dict[str, Tuple[int, int]] = {}
        self._lock = threading.Lock()

    def describe(self) -> str:
        where = f"s3://{self.bucket or '(no bucket)'}"
        return f"{where}/{self.prefix}" if self.prefix else where

    def _key(self, *parts: str) -> str:
        return "/".join(p for p in (self.prefix, *parts) if p)

    def client(self):
        if self._client is None:
            import boto3

            key_id = (self.spec.get("access_key_id")
                      or os.environ.get("POTATO_S3_ACCESS_KEY_ID"))
            secret = (self.spec.get("secret_access_key")
                      or os.environ.get("POTATO_S3_SECRET_ACCESS_KEY"))
            kwargs: Dict[str, Any] = {}
            if self.spec.get("region"):
                kwargs["region_name"] = self.spec["region"]
            if self.spec.get("endpoint_url"):
                kwargs["endpoint_url"] = self.spec["endpoint_url"]
            if key_id and secret:
                kwargs["aws_access_key_id"] = key_id
                kwargs["aws_secret_access_key"] = secret
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _check(self) -> bool:
        if not self.bucket:
            logger.error("An s3 backup sink has no bucket; annotations will NOT "
                         "be backed up there")
            return False
        try:
            import boto3  # noqa: F401
        except ImportError:
            logger.error("The s3 backup is configured but boto3 is not installed, "
                         "so annotations will NOT be backed up. Install with: "
                         "pip install 'potato-annotation[hosting]'")
            return False
        return True

    def start(self, schedule_minutes: float) -> bool:
        if not self._check():
            return False
        # Fail at boot, where the log is read, rather than on the first cycle.
        # The first upload waits for the snapshot loop, so a large task does
        # not hold up the server's start.
        self.client().head_bucket(Bucket=self.bucket)
        logger.info("Backup: %s -> %s every %s minute(s)",
                    output_dir(self.config), self.describe(), schedule_minutes)
        return True

    def tick(self) -> None:
        with self._lock:
            self._sync(output_dir(self.config), ANNOTATIONS_DIR)
            self._sync(snapshot_dir(self.config), REMOTE_DB_DIR)

    flush = tick

    def stop(self) -> None:
        """Nothing runs between ticks."""

    def _sync(self, root: str, remote_dir: str) -> int:
        if not os.path.isdir(root):
            return 0
        sent = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if filename.endswith(".partial"):
                    continue
                path = os.path.join(dirpath, filename)
                relative = os.path.relpath(path, root).replace(os.sep, "/")
                key = self._key(remote_dir, relative)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                fingerprint = (stat.st_size, stat.st_mtime_ns)
                if self._sent.get(key) == fingerprint:
                    continue
                self.client().upload_file(path, self.bucket, key)
                self._sent[key] = fingerprint
                sent += 1
        return sent

    def restore(self, out_dir: str, snap_dir: str) -> int:
        if not self._check():
            return 0
        client = self.client()
        restored = 0
        base = self._key("")
        base = f"{base}/" if base else ""
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=base):
            for item in page.get("Contents", []) or []:
                key = item["Key"]
                relative = key[len(base):]
                target = _target_for(relative, out_dir, snap_dir)
                if target is None:
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                client.download_file(self.bucket, key, target)
                if not target.endswith(".gitkeep"):
                    restored += 1
        return restored


def _target_for(relative: str, out_dir: str, snap_dir: str) -> Optional[str]:
    parts = relative.split("/")
    if len(parts) < 2 or not parts[-1] or not restorable(relative):
        return None
    if parts[0] == ANNOTATIONS_DIR:
        return safe_join(out_dir, parts[1:])
    if parts[0] == REMOTE_DB_DIR:
        return safe_join(snap_dir, parts[1:])
    return None
