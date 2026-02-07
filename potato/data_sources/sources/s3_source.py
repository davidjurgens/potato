"""
Amazon S3 data source.

This module provides data loading from Amazon S3 buckets,
supporting various authentication methods.
"""

import json
import logging
from typing import Any, Dict, Iterator, List, Optional

from potato.data_sources.base import DataSource, SourceConfig

logger = logging.getLogger(__name__)


class S3Source(DataSource):
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
        key: "datasets/items.jsonl"        # Required
        region: "us-east-1"                # Optional, default us-east-1

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

        self._bucket = config.config.get("bucket", "")
        self._key = config.config.get("key", "")
        self._region = config.config.get("region", "us-east-1")
        self._access_key_id = config.config.get("access_key_id")
        self._secret_access_key = config.config.get("secret_access_key")
        self._endpoint_url = config.config.get("endpoint_url")

        self._cached_data: Optional[List[Dict]] = None
        self._client = None

    def get_source_id(self) -> str:
        """Get unique identifier."""
        return self._source_id

    def validate_config(self) -> List[str]:
        """Validate source configuration."""
        errors = []

        if not self._bucket:
            errors.append("'bucket' is required for S3 source")

        if not self._key:
            errors.append("'key' is required for S3 source")

        # Check that both access key and secret are provided together
        if self._access_key_id and not self._secret_access_key:
            errors.append(
                "'secret_access_key' is required when 'access_key_id' is provided"
            )
        if self._secret_access_key and not self._access_key_id:
            errors.append(
                "'access_key_id' is required when 'secret_access_key' is provided"
            )

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

    def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch and parse data from S3."""
        client = self._get_client()

        try:
            response = client.get_object(Bucket=self._bucket, Key=self._key)
            content = response['Body'].read()
            content_type = response.get('ContentType', '')

            logger.debug(
                f"Downloaded s3://{self._bucket}/{self._key} "
                f"({len(content)} bytes, {content_type})"
            )

            # Decode and parse
            text = content.decode('utf-8')
            return self._parse_content(text, content_type)

        except client.exceptions.NoSuchKey:
            raise ValueError(
                f"Object not found: s3://{self._bucket}/{self._key}"
            )
        except client.exceptions.NoSuchBucket:
            raise ValueError(f"Bucket not found: {self._bucket}")
        except Exception as e:
            raise RuntimeError(f"S3 error: {e}")

    def _parse_content(
        self,
        text: str,
        content_type: str = ""
    ) -> List[Dict[str, Any]]:
        """Parse file content based on content type or key extension."""
        key_lower = self._key.lower()

        # Determine format
        is_json = 'json' in content_type or key_lower.endswith('.json')
        is_jsonl = 'ndjson' in content_type or key_lower.endswith('.jsonl')
        is_csv = 'csv' in content_type or key_lower.endswith('.csv')
        is_tsv = 'tab' in content_type or key_lower.endswith('.tsv')

        # Try JSON array first
        if is_json or is_jsonl:
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
            except json.JSONDecodeError:
                pass

        # Try JSONL
        if is_jsonl or is_json:
            items = []
            for line in text.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, list):
                        items.extend(item)
                    else:
                        items.append(item)
                except json.JSONDecodeError:
                    pass

            if items:
                return items

        # Try CSV/TSV
        if is_csv or is_tsv:
            import csv
            from io import StringIO

            delimiter = '\t' if is_tsv else ','
            reader = csv.DictReader(StringIO(text), delimiter=delimiter)
            return [dict(row) for row in reader]

        # Auto-detect: try JSON, then JSONL, then CSV
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        # Try JSONL
        items = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, list):
                    items.extend(item)
                else:
                    items.append(item)
            except json.JSONDecodeError:
                pass

        if items:
            return items

        # Try CSV as last resort
        import csv
        from io import StringIO

        try:
            reader = csv.DictReader(StringIO(text))
            items = [dict(row) for row in reader]
            if items:
                return items
        except Exception:
            pass

        raise ValueError(
            f"Could not parse content from s3://{self._bucket}/{self._key}"
        )

    def read_items(
        self,
        start: int = 0,
        count: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Read items from S3."""
        if self._cached_data is None:
            self._cached_data = self._fetch_data()

        items = self._cached_data[start:]
        if count is not None:
            items = items[:count]

        yield from items

    def get_total_count(self) -> Optional[int]:
        """Get total number of items."""
        if self._cached_data is None:
            try:
                self._cached_data = self._fetch_data()
            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                return None

        return len(self._cached_data)

    def supports_partial_reading(self) -> bool:
        """Partial reading is supported after initial fetch."""
        return True

    def refresh(self) -> bool:
        """Refresh by clearing cached data."""
        self._cached_data = None
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get source status."""
        status = super().get_status()
        status["bucket"] = self._bucket
        status["key"] = self._key
        status["region"] = self._region
        status["endpoint_url"] = self._endpoint_url
        status["cached"] = self._cached_data is not None
        return status

    def close(self) -> None:
        """Close the source."""
        self._client = None
        self._cached_data = None
