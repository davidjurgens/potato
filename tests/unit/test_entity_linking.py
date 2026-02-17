"""
Unit tests for the entity linking module.

Tests cover:
- KnowledgeBaseConfig dataclass
- KBEntity dataclass and serialization
- WikidataClient search and entity retrieval (with mocked API)
- UMLSClient search and entity retrieval (with mocked API)
- RESTClient with configurable endpoints
- KnowledgeBaseManager configuration and search
- SpanAnnotation KB field integration
"""

import pytest
from unittest.mock import patch, MagicMock
import json


class TestKnowledgeBaseConfig:
    """Test KnowledgeBaseConfig dataclass."""

    def test_config_creation(self):
        """Test basic config creation."""
        from potato.knowledge_base import KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="wikidata",
            kb_type="wikidata",
            language="en"
        )

        assert config.name == "wikidata"
        assert config.kb_type == "wikidata"
        assert config.language == "en"
        assert config.api_key is None
        assert config.timeout == 10

    def test_config_with_api_key(self):
        """Test config with API key."""
        from potato.knowledge_base import KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="umls",
            kb_type="umls",
            api_key="test-api-key",
            timeout=30
        )

        assert config.api_key == "test-api-key"
        assert config.timeout == 30

    def test_config_with_extra_params(self):
        """Test config with extra parameters."""
        from potato.knowledge_base import KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="custom",
            kb_type="rest",
            base_url="https://api.example.com",
            extra_params={"search_endpoint": "/search"}
        )

        assert config.base_url == "https://api.example.com"
        assert config.extra_params["search_endpoint"] == "/search"


class TestKBEntity:
    """Test KBEntity dataclass."""

    def test_entity_creation(self):
        """Test basic entity creation."""
        from potato.knowledge_base import KBEntity

        entity = KBEntity(
            entity_id="Q937",
            kb_source="wikidata",
            label="Albert Einstein",
            description="German-born theoretical physicist"
        )

        assert entity.entity_id == "Q937"
        assert entity.kb_source == "wikidata"
        assert entity.label == "Albert Einstein"
        assert entity.description == "German-born theoretical physicist"

    def test_entity_to_dict(self):
        """Test entity serialization to dictionary."""
        from potato.knowledge_base import KBEntity

        entity = KBEntity(
            entity_id="Q937",
            kb_source="wikidata",
            label="Albert Einstein",
            description="Physicist",
            aliases=["Einstein", "A. Einstein"],
            entity_type="Q5",
            url="https://www.wikidata.org/wiki/Q937"
        )

        d = entity.to_dict()

        assert d["entity_id"] == "Q937"
        assert d["kb_source"] == "wikidata"
        assert d["label"] == "Albert Einstein"
        assert d["aliases"] == ["Einstein", "A. Einstein"]
        assert d["entity_type"] == "Q5"
        assert d["url"] == "https://www.wikidata.org/wiki/Q937"

    def test_entity_from_dict(self):
        """Test entity creation from dictionary."""
        from potato.knowledge_base import KBEntity

        data = {
            "entity_id": "Q937",
            "kb_source": "wikidata",
            "label": "Albert Einstein",
            "description": "Physicist",
            "aliases": ["Einstein"]
        }

        entity = KBEntity.from_dict(data)

        assert entity.entity_id == "Q937"
        assert entity.label == "Albert Einstein"
        assert entity.aliases == ["Einstein"]


class TestWikidataClient:
    """Test WikidataClient with mocked API responses."""

    @pytest.fixture
    def wikidata_client(self):
        """Create a WikidataClient instance."""
        from potato.knowledge_base import WikidataClient, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="wikidata",
            kb_type="wikidata",
            language="en"
        )
        return WikidataClient(config)

    @patch('potato.knowledge_base.requests.get')
    def test_search(self, mock_get, wikidata_client):
        """Test Wikidata search functionality."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "search": [
                {
                    "id": "Q937",
                    "label": "Albert Einstein",
                    "description": "German-born theoretical physicist",
                    "aliases": ["Einstein"]
                },
                {
                    "id": "Q5585",
                    "label": "Einstein (crater)",
                    "description": "Lunar crater"
                }
            ]
        }
        mock_get.return_value = mock_response

        results = wikidata_client.search("Einstein", limit=5)

        assert len(results) == 2
        assert results[0].entity_id == "Q937"
        assert results[0].label == "Albert Einstein"
        assert results[0].kb_source == "wikidata"
        assert "wikidata.org" in results[0].url

    @patch('potato.knowledge_base.requests.get')
    def test_search_empty_query(self, mock_get, wikidata_client):
        """Test search with empty query returns empty list."""
        results = wikidata_client.search("")
        assert results == []
        mock_get.assert_not_called()

    @patch('potato.knowledge_base.requests.get')
    def test_search_api_error(self, mock_get, wikidata_client):
        """Test search handles API errors gracefully."""
        import requests as requests_lib
        mock_get.side_effect = requests_lib.RequestException("API error")

        results = wikidata_client.search("Einstein")

        assert results == []

    @patch('potato.knowledge_base.requests.get')
    def test_get_entity(self, mock_get, wikidata_client):
        """Test getting entity details."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "entities": {
                "Q937": {
                    "labels": {"en": {"value": "Albert Einstein"}},
                    "descriptions": {"en": {"value": "German-born theoretical physicist"}},
                    "aliases": {"en": [{"value": "Einstein"}]},
                    "claims": {
                        "P31": [{
                            "mainsnak": {
                                "datavalue": {"value": {"id": "Q5"}}
                            }
                        }]
                    },
                    "sitelinks": {
                        "enwiki": {"title": "Albert Einstein"}
                    }
                }
            }
        }
        mock_get.return_value = mock_response

        entity = wikidata_client.get_entity("Q937")

        assert entity is not None
        assert entity.entity_id == "Q937"
        assert entity.label == "Albert Einstein"
        assert entity.entity_type == "Q5"
        assert "Einstein" in entity.aliases
        assert "wikipedia.org" in entity.url

    @patch('potato.knowledge_base.requests.get')
    def test_get_entity_not_found(self, mock_get, wikidata_client):
        """Test getting non-existent entity returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "entities": {
                "Q999999999": {"missing": ""}
            }
        }
        mock_get.return_value = mock_response

        entity = wikidata_client.get_entity("Q999999999")

        assert entity is None


class TestUMLSClient:
    """Test UMLSClient with mocked API responses."""

    @pytest.fixture
    def umls_client(self):
        """Create a UMLSClient instance."""
        from potato.knowledge_base import UMLSClient, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="umls",
            kb_type="umls",
            api_key="test-api-key"
        )
        return UMLSClient(config)

    def test_no_api_key_warning(self):
        """Test that client without API key logs warning."""
        from potato.knowledge_base import UMLSClient, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="umls",
            kb_type="umls"
        )

        # Should not raise, but logs warning
        client = UMLSClient(config)
        assert client.config.api_key is None

    @patch('potato.knowledge_base.requests.get')
    def test_search(self, mock_get, umls_client):
        """Test UMLS search functionality."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "results": [
                    {
                        "ui": "C0011849",
                        "name": "Diabetes Mellitus",
                        "rootSource": "SNOMEDCT_US"
                    }
                ]
            }
        }
        mock_get.return_value = mock_response

        results = umls_client.search("diabetes")

        assert len(results) == 1
        assert results[0].entity_id == "C0011849"
        assert results[0].label == "Diabetes Mellitus"
        assert results[0].kb_source == "umls"

    def test_search_without_api_key(self):
        """Test search without API key returns empty."""
        from potato.knowledge_base import UMLSClient, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="umls",
            kb_type="umls"
        )
        client = UMLSClient(config)

        results = client.search("diabetes")
        assert results == []


class TestRESTClient:
    """Test RESTClient with configurable endpoints."""

    @pytest.fixture
    def rest_client(self):
        """Create a RESTClient instance."""
        from potato.knowledge_base import RESTClient, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="custom_kb",
            kb_type="rest",
            base_url="https://api.example.com",
            extra_params={
                "search_endpoint": "/search",
                "entity_endpoint": "/entity/{entity_id}",
                "results_path": "data.items",
                "entity_id_field": "uid",
                "label_field": "name"
            }
        )
        return RESTClient(config)

    def test_no_base_url_raises(self):
        """Test that client without base_url raises error."""
        from potato.knowledge_base import RESTClient, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(
            name="bad",
            kb_type="rest"
        )

        with pytest.raises(ValueError, match="base_url"):
            RESTClient(config)

    @patch('potato.knowledge_base.requests.get')
    def test_search(self, mock_get, rest_client):
        """Test REST client search."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "items": [
                    {"uid": "123", "name": "Test Entity"}
                ]
            }
        }
        mock_get.return_value = mock_response

        results = rest_client.search("test")

        assert len(results) == 1
        assert results[0].entity_id == "123"
        assert results[0].label == "Test Entity"
        assert results[0].kb_source == "custom_kb"


class TestKnowledgeBaseManager:
    """Test KnowledgeBaseManager for managing multiple KBs."""

    def test_configure_from_yaml(self):
        """Test configuring manager from YAML-style dict."""
        from potato.knowledge_base import KnowledgeBaseManager

        manager = KnowledgeBaseManager()
        manager.configure_from_yaml({
            "enabled": True,
            "knowledge_bases": [
                {
                    "name": "wikidata",
                    "type": "wikidata",
                    "language": "en"
                }
            ]
        })

        assert "wikidata" in manager.list_clients()
        assert manager.get_client("wikidata") is not None

    def test_configure_disabled(self):
        """Test that disabled config doesn't add clients."""
        from potato.knowledge_base import KnowledgeBaseManager

        manager = KnowledgeBaseManager()
        manager.configure_from_yaml({
            "enabled": False,
            "knowledge_bases": [
                {"name": "wikidata", "type": "wikidata"}
            ]
        })

        assert manager.list_clients() == []

    def test_get_nonexistent_client(self):
        """Test getting non-existent client returns None."""
        from potato.knowledge_base import KnowledgeBaseManager

        manager = KnowledgeBaseManager()

        assert manager.get_client("nonexistent") is None

    @patch('potato.knowledge_base.WikidataClient.search')
    def test_search(self, mock_search):
        """Test manager search functionality."""
        from potato.knowledge_base import KnowledgeBaseManager, KBEntity

        mock_search.return_value = [
            KBEntity(entity_id="Q1", kb_source="wikidata", label="Test")
        ]

        manager = KnowledgeBaseManager()
        manager.configure_from_yaml({
            "enabled": True,
            "knowledge_bases": [
                {"name": "wikidata", "type": "wikidata"}
            ]
        })

        results = manager.search("test", "wikidata")

        assert len(results) == 1
        assert results[0].entity_id == "Q1"


class TestGetKBClient:
    """Test the get_kb_client factory function."""

    def test_get_wikidata_client(self):
        """Test getting Wikidata client."""
        from potato.knowledge_base import get_kb_client, KnowledgeBaseConfig, WikidataClient

        config = KnowledgeBaseConfig(name="wd", kb_type="wikidata")
        client = get_kb_client(config)

        assert isinstance(client, WikidataClient)

    def test_get_umls_client(self):
        """Test getting UMLS client."""
        from potato.knowledge_base import get_kb_client, KnowledgeBaseConfig, UMLSClient

        config = KnowledgeBaseConfig(name="umls", kb_type="umls", api_key="key")
        client = get_kb_client(config)

        assert isinstance(client, UMLSClient)

    def test_get_rest_client(self):
        """Test getting REST client."""
        from potato.knowledge_base import get_kb_client, KnowledgeBaseConfig, RESTClient

        config = KnowledgeBaseConfig(
            name="custom",
            kb_type="rest",
            base_url="https://api.example.com"
        )
        client = get_kb_client(config)

        assert isinstance(client, RESTClient)

    def test_invalid_kb_type(self):
        """Test that invalid KB type raises error."""
        from potato.knowledge_base import get_kb_client, KnowledgeBaseConfig

        config = KnowledgeBaseConfig(name="bad", kb_type="invalid_type")

        with pytest.raises(ValueError, match="Unsupported KB type"):
            get_kb_client(config)


class TestSpanAnnotationKBFields:
    """Test SpanAnnotation with KB entity linking fields."""

    def test_span_with_kb_fields(self):
        """Test creating span with KB fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15,
            kb_id="Q937",
            kb_source="wikidata",
            kb_label="Albert Einstein"
        )

        assert span.kb_id == "Q937"
        assert span.kb_source == "wikidata"
        assert span.kb_label == "Albert Einstein"
        assert span.has_entity_link() is True

    def test_span_without_kb_fields(self):
        """Test span without KB fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15
        )

        assert span.kb_id is None
        assert span.kb_source is None
        assert span.has_entity_link() is False

    def test_set_entity_link(self):
        """Test setting entity link on existing span."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15
        )

        assert span.has_entity_link() is False

        span.set_entity_link("Q937", "wikidata", "Albert Einstein")

        assert span.has_entity_link() is True
        assert span.kb_id == "Q937"
        assert span.kb_source == "wikidata"
        assert span.kb_label == "Albert Einstein"

    def test_clear_entity_link(self):
        """Test clearing entity link."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15,
            kb_id="Q937",
            kb_source="wikidata"
        )

        span.clear_entity_link()

        assert span.has_entity_link() is False
        assert span.kb_id is None
        assert span.kb_source is None

    def test_to_dict_includes_kb_fields(self):
        """Test that to_dict includes KB fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15,
            kb_id="Q937",
            kb_source="wikidata",
            kb_label="Albert Einstein"
        )

        d = span.to_dict()

        assert d["kb_id"] == "Q937"
        assert d["kb_source"] == "wikidata"
        assert d["kb_label"] == "Albert Einstein"

    def test_to_dict_omits_none_kb_fields(self):
        """Test that to_dict omits None KB fields."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15
        )

        d = span.to_dict()

        assert "kb_id" not in d
        assert "kb_source" not in d
        assert "kb_label" not in d

    def test_str_includes_kb_info(self):
        """Test that __str__ includes KB info."""
        from potato.item_state_management import SpanAnnotation

        span = SpanAnnotation(
            schema="ner",
            name="PERSON",
            title="Person",
            start=0,
            end=15,
            kb_id="Q937",
            kb_source="wikidata"
        )

        s = str(span)

        assert "kb:wikidata:Q937" in s


class TestEntityLinkingSchemaConfig:
    """Test entity linking configuration in span schema."""

    def test_schema_with_entity_linking(self):
        """Test span schema with entity linking enabled."""
        from potato.server_utils.schemas.span import _generate_span_layout_internal

        scheme = {
            "name": "ner",
            "description": "Named Entity Recognition",
            "labels": ["PERSON", "ORG"],
            "annotation_id": "ner_1",
            "entity_linking": {
                "enabled": True,
                "knowledge_bases": [
                    {"name": "wikidata", "type": "wikidata"}
                ],
                "auto_search": True,
                "required": False
            }
        }

        html, keybindings = _generate_span_layout_internal(scheme)

        assert "data-entity-linking" in html
        assert "entity-linking-hint" in html
        # Check that entity linking config is present (JSON serialized)
        assert "enabled" in html

    def test_schema_without_entity_linking(self):
        """Test span schema without entity linking."""
        from potato.server_utils.schemas.span import _generate_span_layout_internal

        scheme = {
            "name": "ner",
            "description": "Named Entity Recognition",
            "labels": ["PERSON", "ORG"],
            "annotation_id": "ner_1"
        }

        html, keybindings = _generate_span_layout_internal(scheme)

        assert "data-entity-linking" not in html
        assert "entity-linking-hint" not in html
