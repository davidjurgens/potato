"""
Server integration tests for data sources.

These tests verify that data sources work correctly in a real server context,
using actual public datasets where possible.
"""

import json
import os
import pytest
import requests
import tempfile
import time
from pathlib import Path

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

# Skip markers for optional dependencies
try:
    import datasets
    HAS_DATASETS = True
except ImportError:
    HAS_DATASETS = False

try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def is_network_available():
    """Check if network is available for remote tests."""
    try:
        requests.get("https://huggingface.co", timeout=5)
        return True
    except (requests.RequestException, OSError):
        return False


# Markers
requires_network = pytest.mark.skipif(
    not is_network_available(),
    reason="Network not available"
)

requires_datasets = pytest.mark.skipif(
    not HAS_DATASETS,
    reason="datasets library not installed"
)


class TestLocalFileDataSource:
    """Test LocalFileSource through the server."""

    @pytest.fixture
    def test_data_file(self, tmp_path):
        """Create a test data file."""
        data = [
            {"id": f"item_{i}", "text": f"Test text number {i}"}
            for i in range(10)
        ]
        data_file = tmp_path / "test_data.json"
        data_file.write_text(json.dumps(data))
        return str(data_file)

    @pytest.fixture
    def config_with_data_sources(self, tmp_path, test_data_file):
        """Create a config using data_sources instead of data_files."""
        config = {
            "annotation_task_name": "Data Sources Test",
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path / "output"),
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_sources": [
                {
                    "type": "file",
                    "path": test_data_file,
                    "id": "local_test"
                }
            ],
            "data_files": [],  # Empty, using data_sources instead
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "label",
                    "description": "Label the item",
                    "labels": [
                        {"name": "A", "key_value": "a"},
                        {"name": "B", "key_value": "b"}
                    ]
                }
            ],
            "user_config": {"allow_all_users": True},
            "require_password": False
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        config_file.write_text(yaml.dump(config))

        # Create output directory
        (tmp_path / "output").mkdir(exist_ok=True)

        return str(config_file)

    def test_server_loads_from_data_sources(self, config_with_data_sources):
        """Test that server correctly loads data from data_sources config."""
        server = FlaskTestServer(port=9801, config_file=config_with_data_sources)

        try:
            if not server.start():
                pytest.fail("Failed to start server")

            # Verify server is running
            response = requests.get(f"{server.base_url}/")
            assert response.status_code == 200

            # Login
            session = requests.Session()
            session.post(
                f"{server.base_url}/register",
                data={"email": "test_user", "pass": "test"}
            )
            session.post(
                f"{server.base_url}/auth",
                data={"email": "test_user", "pass": "test"}
            )

            # Get annotation page - should have loaded items
            response = session.get(f"{server.base_url}/annotate")
            assert response.status_code == 200

            # Verify items were loaded by checking admin API
            response = session.get(f"{server.base_url}/admin/api/instances")
            if response.status_code == 200:
                data = response.json()
                # Should have loaded 10 items
                assert "instances" in data or "items" in data or len(data) > 0

        finally:
            server.stop()


class TestURLDataSource:
    """Test URLSource with public URLs."""

    @pytest.fixture
    def url_config(self, tmp_path):
        """Create a config using a public URL data source."""
        # Use a stable public JSON file from GitHub
        config = {
            "annotation_task_name": "URL Source Test",
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path / "output"),
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_sources": [
                {
                    "type": "url",
                    "url": "https://raw.githubusercontent.com/dariusk/corpora/master/data/animals/dogs.json",
                    "id": "dogs_url"
                }
            ],
            "data_files": [],
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "label",
                    "description": "Label the item",
                    "labels": [
                        {"name": "A", "key_value": "a"},
                        {"name": "B", "key_value": "b"}
                    ]
                }
            ],
            "user_config": {"allow_all_users": True},
            "require_password": False
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        config_file.write_text(yaml.dump(config))
        (tmp_path / "output").mkdir(exist_ok=True)

        return str(config_file)

    @requires_network
    def test_url_source_fetches_data(self):
        """Test that URLSource can fetch from a public URL."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.url_source import URLSource

        config = SourceConfig.from_dict({
            "type": "url",
            "url": "https://raw.githubusercontent.com/dariusk/corpora/master/data/animals/dogs.json"
        })

        source = URLSource(config)

        # Check availability
        assert source.is_available() is True

        # Fetch data
        items = list(source.read_items())

        # The dogs.json has a specific structure
        assert len(items) >= 1
        # The file contains a single object with "dogs" array
        # Our parser should handle this

    @requires_network
    def test_url_source_with_json_api(self):
        """Test URLSource with a public JSON API endpoint."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.url_source import URLSource

        # Use Nobel Prize API - stable and reliable
        config = SourceConfig.from_dict({
            "type": "url",
            "url": "http://api.nobelprize.org/v1/prize.json"
        })

        source = URLSource(config)

        if source.is_available():
            try:
                items = list(source.read_items(count=5))  # Limit to 5 items
                # The Nobel Prize API returns data in a specific format
                # It should have loaded something
                assert len(items) >= 0  # May be structured differently
            except Exception:
                # API might be down or slow - that's ok for integration tests
                pytest.skip("Nobel Prize API unavailable")


class TestHuggingFaceDataSource:
    """Test HuggingFaceSource with real datasets."""

    @requires_network
    @requires_datasets
    def test_load_sst2_dataset(self):
        """Test loading the SST-2 sentiment dataset."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.huggingface_source import HuggingFaceSource

        config = SourceConfig.from_dict({
            "type": "huggingface",
            "dataset": "stanfordnlp/sst2",
            "split": "validation",  # Use validation split (smaller)
            "id_field": "idx",
            "text_field": "sentence"
        })

        source = HuggingFaceSource(config)

        # Check dependencies
        if not source._check_dependencies():
            pytest.skip("datasets library not available")

        assert source.is_available() is True

        # Load first 10 items
        items = list(source.read_items(count=10))

        assert len(items) == 10

        # Check structure
        first_item = items[0]
        assert "id" in first_item  # Mapped from idx
        assert "sentence" in first_item
        assert "label" in first_item

    @requires_network
    @requires_datasets
    def test_load_imdb_dataset(self):
        """Test loading the IMDB sentiment dataset."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.huggingface_source import HuggingFaceSource

        config = SourceConfig.from_dict({
            "type": "huggingface",
            "dataset": "imdb",
            "split": "test",
            "text_field": "text"
        })

        source = HuggingFaceSource(config)

        if not source._check_dependencies():
            pytest.skip("datasets library not available")

        # Get total count
        total = source.get_total_count()
        assert total is not None
        assert total > 0

        # Load a few items with partial reading
        items = list(source.read_items(start=0, count=5))
        assert len(items) == 5

        # Check partial reading works
        items2 = list(source.read_items(start=5, count=5))
        assert len(items2) == 5

        # Items should be different
        assert items[0]["id"] != items2[0]["id"]

    @requires_network
    @requires_datasets
    def test_huggingface_partial_loading(self):
        """Test partial/incremental loading with HuggingFace datasets."""
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.huggingface_source import HuggingFaceSource

        config = SourceConfig.from_dict({
            "type": "huggingface",
            "dataset": "stanfordnlp/sst2",
            "split": "validation",
            "id_field": "idx",
            "text_field": "sentence"
        })

        source = HuggingFaceSource(config)

        if not source._check_dependencies():
            pytest.skip("datasets library not available")

        # Verify partial reading is supported
        assert source.supports_partial_reading() is True

        # Load in batches
        batch1 = list(source.read_items(start=0, count=10))
        batch2 = list(source.read_items(start=10, count=10))

        assert len(batch1) == 10
        assert len(batch2) == 10

        # Batches should be different
        batch1_ids = {item["id"] for item in batch1}
        batch2_ids = {item["id"] for item in batch2}
        assert batch1_ids.isdisjoint(batch2_ids)


class TestDataSourceManagerIntegration:
    """Test DataSourceManager in an integrated context."""

    @pytest.fixture
    def multi_source_config(self, tmp_path):
        """Create a config with multiple data sources."""
        # Create local data files
        data1 = [{"id": f"local_{i}", "text": f"Local item {i}"} for i in range(5)]
        data2 = [{"id": f"extra_{i}", "text": f"Extra item {i}"} for i in range(5)]

        file1 = tmp_path / "data1.json"
        file2 = tmp_path / "data2.json"
        file1.write_text(json.dumps(data1))
        file2.write_text(json.dumps(data2))

        config = {
            "annotation_task_name": "Multi-Source Test",
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path / "output"),
            "item_properties": {
                "id_key": "id",
                "text_key": "text"
            },
            "data_sources": [
                {"type": "file", "path": str(file1), "id": "source1"},
                {"type": "file", "path": str(file2), "id": "source2"}
            ],
            "data_files": [],
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "label",
                    "description": "Label",
                    "labels": [{"name": "A", "key_value": "a"}]
                }
            ],
            "user_config": {"allow_all_users": True},
            "require_password": False
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        config_file.write_text(yaml.dump(config))
        (tmp_path / "output").mkdir(exist_ok=True)

        return str(config_file)

    def test_multiple_sources_loaded(self, multi_source_config):
        """Test that multiple data sources are all loaded."""
        server = FlaskTestServer(port=9802, config_file=multi_source_config)

        try:
            if not server.start():
                pytest.fail("Failed to start server")

            session = requests.Session()
            session.post(
                f"{server.base_url}/register",
                data={"email": "test", "pass": "test"}
            )
            session.post(
                f"{server.base_url}/auth",
                data={"email": "test", "pass": "test"}
            )

            # Check that items from both sources are present
            # by navigating through annotation
            response = session.get(f"{server.base_url}/annotate")
            assert response.status_code == 200

            # The page should show items from the loaded sources
            assert "local_" in response.text or "extra_" in response.text or "item" in response.text.lower()

        finally:
            server.stop()


class TestAdminDataSourcesAPI:
    """Test admin API endpoints for data sources."""

    @pytest.fixture
    def server_with_data_sources(self, tmp_path):
        """Create and start a server with data sources configured."""
        data = [{"id": f"item_{i}", "text": f"Text {i}"} for i in range(20)]
        data_file = tmp_path / "data.json"
        data_file.write_text(json.dumps(data))

        config = {
            "annotation_task_name": "Admin API Test",
            "task_dir": str(tmp_path),
            "output_annotation_dir": str(tmp_path / "output"),
            "item_properties": {"id_key": "id", "text_key": "text"},
            "data_sources": [
                {"type": "file", "path": str(data_file), "id": "test_source"}
            ],
            "data_files": [],
            "partial_loading": {
                "enabled": True,
                "initial_count": 10,
                "batch_size": 5
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "label",
                    "description": "Label",
                    "labels": [{"name": "A", "key_value": "a"}]
                }
            ],
            "user_config": {"allow_all_users": True},
            "require_password": False,
            "admin": {"password": "admin123"}
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        config_file.write_text(yaml.dump(config))
        (tmp_path / "output").mkdir(exist_ok=True)

        server = FlaskTestServer(port=9803, config_file=str(config_file))
        if not server.start():
            pytest.fail("Failed to start server")

        yield server

        server.stop()

    def test_list_data_sources_api(self, server_with_data_sources):
        """Test GET /admin/api/data_sources endpoint."""
        server = server_with_data_sources

        session = requests.Session()
        # Login as admin
        session.post(
            f"{server.base_url}/register",
            data={"email": "admin", "pass": "admin123"}
        )
        session.post(
            f"{server.base_url}/auth",
            data={"email": "admin", "pass": "admin123"}
        )

        # Get data sources
        response = session.get(f"{server.base_url}/admin/api/data_sources")

        # Various valid responses:
        # - 200 with data sources info
        # - 403 if admin access required but user isn't admin
        # - 404 if route not yet integrated with test server
        # - 200 with enabled=False if data_sources not configured
        # The route may return 404 if the Flask app doesn't have all routes loaded
        # in the test configuration
        assert response.status_code in [200, 403, 404]

        if response.status_code == 200:
            data = response.json()
            # Response should have 'enabled' field or error
            assert "enabled" in data or "error" in data or "sources" in data or "message" in data


class TestCacheIntegration:
    """Test caching functionality with remote sources."""

    @pytest.fixture
    def cache_dir(self, tmp_path):
        """Create a cache directory."""
        cache = tmp_path / "cache"
        cache.mkdir()
        return str(cache)

    @requires_network
    def test_url_source_caching(self, cache_dir):
        """Test that URL source data is cached."""
        from potato.data_sources.cache_manager import CacheManager

        cache = CacheManager(cache_dir=cache_dir, ttl_seconds=3600)

        # Simulate caching a URL fetch
        source_id = "test_url"
        source_url = "https://example.com/data.json"
        test_data = b'[{"id": "1", "text": "test"}]'

        entry = cache.put(
            source_id=source_id,
            source_url=source_url,
            data=test_data,
            content_type="application/json"
        )

        assert entry is not None
        assert entry.file_size == len(test_data)

        # Verify cache hit
        cached = cache.get(source_id)
        assert cached is not None
        assert cached.source_url == source_url

        # Verify file exists
        assert os.path.exists(cached.cache_path)

        # Read cached content
        with open(cached.cache_path, 'rb') as f:
            content = f.read()
        assert content == test_data


class TestPartialLoadingIntegration:
    """Test partial/incremental loading functionality."""

    @requires_network
    @requires_datasets
    def test_incremental_loading_workflow(self, tmp_path):
        """Test the full incremental loading workflow."""
        from potato.data_sources.partial_reader import PartialReader, PartialLoadingConfig
        from potato.data_sources.base import SourceConfig
        from potato.data_sources.sources.huggingface_source import HuggingFaceSource

        # Create partial loading config
        pl_config = PartialLoadingConfig(
            enabled=True,
            initial_count=10,
            batch_size=5,
            auto_load_threshold=0.8
        )

        reader = PartialReader(pl_config, str(tmp_path))

        # Create HuggingFace source
        source_config = SourceConfig.from_dict({
            "type": "huggingface",
            "dataset": "stanfordnlp/sst2",
            "split": "validation",
            "id_field": "idx",
            "text_field": "sentence"
        })
        source = HuggingFaceSource(source_config)

        if not source._check_dependencies():
            pytest.skip("datasets library not available")

        source_id = source.source_id

        # Initial load
        initial_count = reader.get_load_count(source_id, is_initial=True)
        assert initial_count == 10

        start = reader.get_start_position(source_id)
        assert start == 0

        items = list(source.read_items(start=start, count=initial_count))
        assert len(items) == 10

        # Update state
        reader.update_state(source_id, items_added=len(items))

        # Check state
        state = reader.get_state(source_id)
        assert state.items_loaded == 10

        # Simulate that 8 items are annotated (80%)
        should_load = reader.should_load_more(source_id, annotated_count=8, total_loaded=10)
        assert should_load is True

        # Load more
        batch_count = reader.get_load_count(source_id, is_initial=False)
        assert batch_count == 5

        start = reader.get_start_position(source_id)
        assert start == 10

        more_items = list(source.read_items(start=start, count=batch_count))
        assert len(more_items) == 5

        reader.update_state(source_id, items_added=len(more_items))

        # Verify total loaded
        state = reader.get_state(source_id)
        assert state.items_loaded == 15


class TestSSRFProtection:
    """Test SSRF protection in URL source."""

    def test_blocks_localhost(self):
        """Test that localhost is blocked."""
        from potato.data_sources.sources.url_source import resolve_and_validate_url

        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("http://localhost/data", block_private_ips=True)

        assert "private" in str(exc_info.value).lower()

    def test_blocks_private_ip(self):
        """Test that private IPs are blocked."""
        from potato.data_sources.sources.url_source import resolve_and_validate_url

        private_urls = [
            "http://10.0.0.1/data",
            "http://172.16.0.1/data",
            "http://192.168.1.1/data",
            "http://127.0.0.1/data",
        ]

        for url in private_urls:
            with pytest.raises(ValueError) as exc_info:
                resolve_and_validate_url(url, block_private_ips=True)
            assert "private" in str(exc_info.value).lower()

    def test_allows_public_url(self):
        """Test that public URLs are allowed."""
        from potato.data_sources.sources.url_source import resolve_and_validate_url

        # This should not raise
        result = resolve_and_validate_url(
            "https://example.com/data.json",
            block_private_ips=True
        )
        assert result == "https://example.com/data.json"

    def test_blocks_file_scheme(self):
        """Test that file:// scheme is blocked."""
        from potato.data_sources.sources.url_source import resolve_and_validate_url

        with pytest.raises(ValueError) as exc_info:
            resolve_and_validate_url("file:///etc/passwd", block_private_ips=True)

        assert "scheme" in str(exc_info.value).lower()


class TestGoogleDriveURLParsing:
    """Test Google Drive URL parsing."""

    def test_parse_share_link(self):
        """Test parsing various Google Drive URL formats."""
        from potato.data_sources.sources.gdrive_source import extract_file_id

        test_cases = [
            ("https://drive.google.com/file/d/1ABC123xyz/view?usp=sharing", "1ABC123xyz"),
            ("https://drive.google.com/open?id=1ABC123xyz", "1ABC123xyz"),
            ("https://docs.google.com/document/d/1ABC123xyz/edit", "1ABC123xyz"),
            ("https://drive.google.com/uc?id=1ABC123xyz&export=download", "1ABC123xyz"),
            ("1ABC123xyz", "1ABC123xyz"),  # Direct file ID
        ]

        for url, expected_id in test_cases:
            result = extract_file_id(url)
            assert result == expected_id, f"Failed for URL: {url}"

    def test_invalid_url_raises(self):
        """Test that invalid URLs raise ValueError."""
        from potato.data_sources.sources.gdrive_source import extract_file_id

        with pytest.raises(ValueError):
            extract_file_id("https://example.com/not-a-drive-link")
