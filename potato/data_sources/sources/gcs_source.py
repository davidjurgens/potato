"""
Google Cloud Storage data source.

Configuration::

    type: gcs
    bucket: my-annotation-data
    key: datasets/items.jsonl        # one object, or:
    prefix: incoming/                # every data file under the prefix
    credentials_file: sa.json        # optional: a service-account key file
    project: my-project              # optional
    anonymous: false                 # true for a public bucket
    live_ingestion: {enabled: true}  # prefix mode: pick up new objects

Without ``credentials_file`` the client uses Application Default Credentials
(``gcloud auth application-default login``, ``GOOGLE_APPLICATION_CREDENTIALS``,
or the attached service account on GCP). Needs ``pip install
"potato-annotation[gcs]"``.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

from potato.data_sources.base import SourceConfig
from potato.data_sources.sources.object_store import ObjectInfo, ObjectStoreSource

logger = logging.getLogger(__name__)


class GCSSource(ObjectStoreSource):
    """Data source for Google Cloud Storage buckets."""

    _HAS_SDK = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        if cls._HAS_SDK is None:
            try:
                from google.cloud import storage  # noqa: F401
                cls._HAS_SDK = True
            except ImportError:
                cls._HAS_SDK = False
        return cls._HAS_SDK

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        raw = config.config
        self._credentials_file = raw.get("credentials_file")
        self._project = raw.get("project")
        self._anonymous = bool(raw.get("anonymous"))
        self._client = None

    def validate_config(self) -> List[str]:
        errors = super().validate_config()
        if self._credentials_file and self._anonymous:
            errors.append("a gcs source takes 'credentials_file' or 'anonymous: true', not both")
        if self._credentials_file and not os.path.isfile(self._credentials_file):
            errors.append(f"credentials_file not found: {self._credentials_file}")
        return errors

    def is_available(self) -> bool:
        if not self._check_dependencies():
            logger.warning('google-cloud-storage is not installed. Install with: '
                           'pip install "potato-annotation[gcs]"')
            return False
        return True

    def _get_client(self):
        if self._client is None:
            from google.cloud import storage
            if self._anonymous:
                self._client = storage.Client.create_anonymous_client()
            elif self._credentials_file:
                self._client = storage.Client.from_service_account_json(
                    self._credentials_file, project=self._project)
            else:
                self._client = storage.Client(project=self._project)
        return self._client

    def _uri(self, key: str) -> str:
        return f"gs://{self._bucket}/{key}"

    def _list_objects(self, prefix: str, start_after: Optional[str] = None) -> List[ObjectInfo]:
        # start_offset is inclusive; the base class drops the key itself.
        options = {"prefix": prefix or None}
        if start_after:
            options["start_offset"] = start_after
        return [ObjectInfo(blob.name, blob.updated, int(blob.size or 0))
                for blob in self._get_client().list_blobs(self._bucket, **options)
                if not blob.name.endswith("/")]

    def _read_object(self, key: str) -> Tuple[bytes, str]:
        blob = self._get_client().bucket(self._bucket).get_blob(key)
        if blob is None:
            raise ValueError(f"Object not found: {self._uri(key)}")
        return blob.download_as_bytes(), blob.content_type or ""

    def get_status(self):
        status = super().get_status()
        status["project"] = self._project
        return status

    def close(self) -> None:
        super().close()
        self._client = None
