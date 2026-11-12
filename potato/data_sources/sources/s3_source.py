"""
Amazon S3 data source.

Data loading from Amazon S3 buckets,
supporting various authentication methods.
"""

import ipaddress
import json
import logging
import socket
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlparse

from potato.data_sources.base import SourceConfig
from potato.data_sources.sources.object_store import ObjectInfo, ObjectStoreSource

logger = logging.getLogger(__name__)


class S3Source(ObjectStoreSource):
    """
    Data source for Amazon S3 buckets.

    Supports loading data from S3 with multiple authentication options:
    - AWS credentials file (~/.aws/credentials)
    - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - Explicit credentials in config
    - S3-compatible storage (MinIO, etc.)

    Configuration:
        type: s3
        bucket: "my-annotation-data"       # Required
        key: "datasets/items.jsonl"        # One object, or:
        prefix: "incoming/"                # every data file under the prefix
        region: "us-east-1"                # Optional, default us-east-1
        live_ingestion: {enabled: true}    # prefix mode: pick up new objects

        # Optional: explicit credentials (prefer env vars)
        access_key_id: "${AWS_ACCESS_KEY_ID}"
        secret_access_key: "${AWS_SECRET_ACCESS_KEY}"

        # Optional: for S3-compatible storage
        endpoint_url: "https://minio.example.com"

    Supported formats: JSON, JSONL, CSV, TSV
    """

    # Check for optional dependencies
    _HAS_BOTO3 = None

    @classmethod
    def _check_dependencies(cls) -> bool:
        """Check if boto3 is available."""
        if cls._HAS_BOTO3 is None:
            try:
                import boto3
                cls._HAS_BOTO3 = True
            except ImportError:
                cls._HAS_BOTO3 = False
        return cls._HAS_BOTO3

    def __init__(self, config: SourceConfig):
        """Initialize the S3 source."""
        super().__init__(config)

        self._region = config.config.get("region", "us-east-1")
        self._access_key_id = config.config.get("access_key_id")
        self._secret_access_key = config.config.get("secret_access_key")
        self._endpoint_url = config.config.get("endpoint_url")
        self._client = None

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = super().validate_config()

        # Check that both access key and secret are provided together
        if self._access_key_id and not self._secret_access_key:
            errors.append(
                "'secret_access_key' is required when 'access_key_id' is provided"
            )
        if self._secret_access_key and not self._access_key_id:
            errors.append(
                "'access_key_id' is required when 'secret_access_key' is provided"
            )

        # SSRF protection: validate endpoint_url does not point to private IPs
        if self._endpoint_url:
            try:
                parsed = urlparse(self._endpoint_url)
                if parsed.scheme not in ('http', 'https'):
                    errors.append(
                        f"Invalid endpoint_url scheme '{parsed.scheme}'. "
                        f"Only http/https allowed."
                    )
                hostname = parsed.hostname
                if hostname:
                    try:
                        addr_info = socket.getaddrinfo(hostname, None)
                        for info in addr_info:
                            ip_str = info[4][0]
                            try:
                                ip = ipaddress.ip_address(ip_str)
                                if ip.is_loopback or ip.is_link_local:
                                    errors.append(
                                        f"endpoint_url host '{hostname}' resolves "
                                        f"to blocked IP {ip_str}. Loopback and "
                                        f"link-local addresses are not allowed."
                                    )
                            except ValueError:
                                pass
                    except socket.gaierror:
                        # Can't resolve at validation time — will fail at connect
                        pass
            except Exception as e:
                errors.append(f"Invalid endpoint_url: {e}")

        return errors

    def is_available(self) -> bool:
        """Check if the source is available."""
        if not self._check_dependencies():
            logger.warning(
                "boto3 not installed. Install with: pip install boto3"
            )
            return False

        return True

    def _get_client(self):
        """Get or create the S3 client."""
        if self._client:
            return self._client

        import boto3

        # Build client configuration
        client_kwargs = {
            'region_name': self._region,
        }

        if self._endpoint_url:
            client_kwargs['endpoint_url'] = self._endpoint_url

        if self._access_key_id and self._secret_access_key:
            client_kwargs['aws_access_key_id'] = self._access_key_id
            client_kwargs['aws_secret_access_key'] = self._secret_access_key

        self._client = boto3.client('s3', **client_kwargs)
        return self._client

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    def _list_objects(self, prefix: str, start_after: Optional[str] = None) -> List[ObjectInfo]:
        client = self._get_client()
        objects: List[ObjectInfo] = []
        params = {"Bucket": self._bucket, "Prefix": prefix}
        if start_after:
            params["StartAfter"] = start_after  # S3 lists keys in UTF-8 binary order
        try:
            for page in client.get_paginator("list_objects_v2").paginate(**params):
                for entry in page.get("Contents", []) or []:
                    if entry["Key"].endswith("/"):
                        continue  # a "folder" placeholder
                    objects.append(ObjectInfo(entry["Key"], entry["LastModified"],
                                              int(entry.get("Size") or 0)))
        except client.exceptions.NoSuchBucket:
            raise ValueError(f"Bucket not found: {self._bucket}")
        return objects

    def _read_object(self, key: str):
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self._bucket, Key=key)
        except client.exceptions.NoSuchKey:
            raise ValueError(f"Object not found: {self._uri(key)}")
        except client.exceptions.NoSuchBucket:
            raise ValueError(f"Bucket not found: {self._bucket}")
        content = response["Body"].read()
        logger.debug("Downloaded %s (%d bytes)", self._uri(key), len(content))
        return content, response.get("ContentType", "")

    def _fetch_data(self) -> List[Dict[str, Any]]:
        try:
            return super()._fetch_data()
        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(f"S3 error: {e}")

    def _parse_content(self, text: str, content_type: str = "") -> List[Dict[str, Any]]:
        """Parse one object's text (kept for callers of the old interface)."""
        return self._parse(self._key or "data", text.encode("utf-8"), content_type)

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["region"] = self._region
        status["endpoint_url"] = self._endpoint_url
        return status

    def close(self) -> None:
        """Close the source."""
        super().close()
        self._client = None
