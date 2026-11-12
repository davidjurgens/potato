"""
Azure Blob Storage data source.

Configuration::

    type: azure_blob
    container: annotation-data
    key: datasets/items.jsonl                    # one blob, or:
    prefix: incoming/                            # every data file under it
    connection_string: "${AZURE_STORAGE_CONNECTION_STRING}"
    # or: account_url: https://myaccount.blob.core.windows.net
    #     credential: "${AZURE_STORAGE_SAS_TOKEN}"   # SAS token or account key;
    #                                                # omit for a public container
    live_ingestion: {enabled: true}              # prefix mode: pick up new blobs

Needs ``pip install "potato-annotation[azure]"``.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from potato.data_sources.base import SourceConfig
from potato.data_sources.sources.object_store import ObjectInfo, ObjectStoreSource

logger = logging.getLogger(__name__)


def _blocked_host(url: str, what: str) -> List[str]:
    """The same SSRF guard the S3 source applies to endpoint_url."""
    errors = []
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return [f"Invalid {what} scheme '{parsed.scheme}'. Only http/https allowed."]
    host = parsed.hostname
    if not host:
        return errors
    try:
        for info in socket.getaddrinfo(host, None):
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if ip.is_loopback or ip.is_link_local:
                errors.append(f"{what} host '{host}' resolves to blocked IP {ip}. Loopback "
                              f"and link-local addresses are not allowed.")
                break
    except socket.gaierror:
        pass  # unresolvable now; the connection will fail and say so
    return errors


def _endpoint_of(connection_string: str) -> Optional[str]:
    parts = dict(p.split("=", 1) for p in connection_string.split(";") if "=" in p)
    if parts.get("BlobEndpoint"):
        return parts["BlobEndpoint"]
    if parts.get("AccountName"):
        protocol = parts.get("DefaultEndpointsProtocol", "https")
        suffix = parts.get("EndpointSuffix", "core.windows.net")
        return f"{protocol}://{parts['AccountName']}.blob.{suffix}"
    return None


class AzureBlobSource(ObjectStoreSource):
    """Data source for Azure Blob Storage containers."""

    BUCKET_KEY = "container"
    _HAS_SDK = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        if cls._HAS_SDK is None:
            try:
                from azure.storage.blob import BlobServiceClient  # noqa: F401
                cls._HAS_SDK = True
            except ImportError:
                cls._HAS_SDK = False
        return cls._HAS_SDK

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        raw = config.config
        self._connection_string = raw.get("connection_string")
        self._account_url = raw.get("account_url")
        self._credential = raw.get("credential")
        self._container_client = None

    def validate_config(self) -> List[str]:
        errors = super().validate_config()
        if not self._connection_string and not self._account_url:
            errors.append("an azure_blob source needs 'connection_string' or 'account_url'")
        if self._connection_string and self._account_url:
            errors.append("an azure_blob source takes 'connection_string' or 'account_url', "
                          "not both")
        if self._account_url:
            errors.extend(_blocked_host(self._account_url, "account_url"))
        elif self._connection_string:
            endpoint = _endpoint_of(self._connection_string)
            if endpoint:
                errors.extend(_blocked_host(endpoint, "connection_string BlobEndpoint"))
        return errors

    def is_available(self) -> bool:
        if not self._check_dependencies():
            logger.warning('azure-storage-blob is not installed. Install with: '
                           'pip install "potato-annotation[azure]"')
            return False
        return True

    def _container(self):
        if self._container_client is None:
            from azure.storage.blob import BlobServiceClient
            if self._connection_string:
                service = BlobServiceClient.from_connection_string(self._connection_string)
            else:
                service = BlobServiceClient(account_url=self._account_url,
                                            credential=self._credential or None)
            self._container_client = service.get_container_client(self._bucket)
        return self._container_client

    def _uri(self, key: str) -> str:
        return f"azure://{self._bucket}/{key}"

    def _list_objects(self, prefix: str, start_after: Optional[str] = None) -> List[ObjectInfo]:
        # Azure's listing cannot start after a key; config validation keeps
        # key-ordered listing off this source, and the base class filters.
        return [ObjectInfo(blob.name, blob.last_modified, int(blob.size or 0))
                for blob in self._container().list_blobs(name_starts_with=prefix or None)
                if not blob.name.endswith("/")]

    def _read_object(self, key: str) -> Tuple[bytes, str]:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            downloader = self._container().download_blob(key)
        except ResourceNotFoundError:
            raise ValueError(f"Blob not found: {self._uri(key)}")
        settings = getattr(downloader.properties, "content_settings", None)
        return downloader.readall(), (getattr(settings, "content_type", "") or "")

    def close(self) -> None:
        super().close()
        self._container_client = None
