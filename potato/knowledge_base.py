"""
Knowledge Base Client Module

This module provides clients for querying external knowledge bases to support
entity linking in span annotations. Supported knowledge bases include:

- Wikidata: Open knowledge graph with millions of entities
- UMLS: Unified Medical Language System (requires API key)
- Custom REST APIs: Generic interface for custom knowledge bases

Usage:
    from potato.knowledge_base import get_kb_client, KnowledgeBaseConfig

    # Configure and get a client
    config = KnowledgeBaseConfig(
        name="wikidata",
        kb_type="wikidata",
        language="en"
    )
    client = get_kb_client(config)

    # Search for entities
    results = client.search("Einstein", limit=10)

    # Get entity details
    entity = client.get_entity("Q937")
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging
import json

logger = logging.getLogger(__name__)

# Try to import requests, but make it optional
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests library not available. KB clients will not function.")


@dataclass
class KnowledgeBaseConfig:
    """
    Configuration for a knowledge base client.

    Attributes:
        name: Unique identifier for this KB configuration
        kb_type: Type of knowledge base ("wikidata", "umls", "rest")
        api_key: Optional API key for authenticated services
        base_url: Base URL for REST APIs
        language: Language code for results (default: "en")
        timeout: Request timeout in seconds
        extra_params: Additional parameters for the API
    """
    name: str
    kb_type: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    language: str = "en"
    timeout: int = 10
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KBEntity:
    """
    Represents an entity from a knowledge base.

    Attributes:
        entity_id: Unique identifier in the KB (e.g., "Q937" for Wikidata)
        kb_source: Name of the knowledge base (e.g., "wikidata", "umls")
        label: Human-readable label/name
        description: Short description of the entity
        aliases: Alternative names for the entity
        entity_type: Type/class of the entity (if available)
        url: URL to the entity page in the KB
        extra_data: Additional data from the KB
    """
    entity_id: str
    kb_source: str
    label: str
    description: str = ""
    aliases: List[str] = field(default_factory=list)
    entity_type: Optional[str] = None
    url: Optional[str] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "entity_id": self.entity_id,
            "kb_source": self.kb_source,
            "label": self.label,
            "description": self.description,
            "aliases": self.aliases,
            "entity_type": self.entity_type,
            "url": self.url,
            "extra_data": self.extra_data
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KBEntity":
        """Create entity from dictionary."""
        return cls(
            entity_id=data.get("entity_id", ""),
            kb_source=data.get("kb_source", ""),
            label=data.get("label", ""),
            description=data.get("description", ""),
            aliases=data.get("aliases", []),
            entity_type=data.get("entity_type"),
            url=data.get("url"),
            extra_data=data.get("extra_data", {})
        )


class KnowledgeBaseClient(ABC):
    """
    Abstract base class for knowledge base clients.

    Subclasses must implement search() and get_entity() methods.
    """

    def __init__(self, config: KnowledgeBaseConfig):
        """
        Initialize the KB client with configuration.

        Args:
            config: KnowledgeBaseConfig with connection settings
        """
        self.config = config
        self.name = config.name

    @abstractmethod
    def search(self, query: str, limit: int = 10, entity_type: Optional[str] = None) -> List[KBEntity]:
        """
        Search the knowledge base for entities matching the query.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            entity_type: Optional filter for entity type

        Returns:
            List of KBEntity objects matching the query
        """
        pass

    @abstractmethod
    def get_entity(self, entity_id: str) -> Optional[KBEntity]:
        """
        Get detailed information about a specific entity.

        Args:
            entity_id: The unique identifier for the entity

        Returns:
            KBEntity object if found, None otherwise
        """
        pass

    def is_available(self) -> bool:
        """
        Check if the KB service is available.

        Returns:
            True if the service can be reached, False otherwise
        """
        return REQUESTS_AVAILABLE


class WikidataClient(KnowledgeBaseClient):
    """
    Client for querying Wikidata, the free knowledge base.

    Wikidata provides millions of entities across all domains with
    multilingual labels, descriptions, and structured data.

    API documentation: https://www.wikidata.org/w/api.php
    """

    WIKIDATA_API = "https://www.wikidata.org/w/api.php"
    WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/"

    def search(self, query: str, limit: int = 10, entity_type: Optional[str] = None) -> List[KBEntity]:
        """
        Search Wikidata for entities matching the query.

        Args:
            query: Search query string
            limit: Maximum number of results (max 50)
            entity_type: Optional Wikidata item type (e.g., "Q5" for humans)

        Returns:
            List of KBEntity objects
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for Wikidata search")
            return []

        if not query or not query.strip():
            return []

        params = {
            "action": "wbsearchentities",
            "format": "json",
            "language": self.config.language,
            "uselang": self.config.language,
            "search": query.strip(),
            "limit": min(limit, 50),  # Wikidata max is 50
            "type": "item"
        }

        try:
            response = requests.get(
                self.WIKIDATA_API,
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("search", []):
                entity = KBEntity(
                    entity_id=item.get("id", ""),
                    kb_source="wikidata",
                    label=item.get("label", ""),
                    description=item.get("description", ""),
                    aliases=item.get("aliases", []),
                    url=f"{self.WIKIDATA_ENTITY_URL}{item.get('id', '')}"
                )
                results.append(entity)

            # Filter by entity_type if specified (requires additional API call)
            if entity_type and results:
                results = self._filter_by_type(results, entity_type)

            return results

        except requests.RequestException as e:
            logger.error(f"Wikidata search error: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Wikidata JSON parse error: {e}")
            return []

    def _filter_by_type(self, entities: List[KBEntity], entity_type: str) -> List[KBEntity]:
        """
        Filter entities by their instance_of (P31) property.

        Args:
            entities: List of entities to filter
            entity_type: Wikidata item ID for the type (e.g., "Q5" for human)

        Returns:
            Filtered list of entities
        """
        if not entities:
            return []

        # Get entity IDs
        entity_ids = [e.entity_id for e in entities]

        # Query for P31 (instance of) claims
        params = {
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(entity_ids),
            "props": "claims",
            "languages": self.config.language
        }

        try:
            response = requests.get(
                self.WIKIDATA_API,
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Build set of matching entity IDs
            matching_ids = set()
            for eid, entity_data in data.get("entities", {}).items():
                claims = entity_data.get("claims", {})
                p31_claims = claims.get("P31", [])

                for claim in p31_claims:
                    mainsnak = claim.get("mainsnak", {})
                    datavalue = mainsnak.get("datavalue", {})
                    value = datavalue.get("value", {})
                    if value.get("id") == entity_type:
                        matching_ids.add(eid)
                        break

            # Filter entities
            return [e for e in entities if e.entity_id in matching_ids]

        except requests.RequestException as e:
            logger.warning(f"Wikidata type filter error: {e}")
            return entities  # Return unfiltered on error

    def get_entity(self, entity_id: str) -> Optional[KBEntity]:
        """
        Get detailed information about a Wikidata entity.

        Args:
            entity_id: Wikidata item ID (e.g., "Q937")

        Returns:
            KBEntity with full details, or None if not found
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for Wikidata get_entity")
            return None

        if not entity_id:
            return None

        params = {
            "action": "wbgetentities",
            "format": "json",
            "ids": entity_id,
            "props": "labels|descriptions|aliases|claims|sitelinks",
            "languages": self.config.language
        }

        try:
            response = requests.get(
                self.WIKIDATA_API,
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            entities = data.get("entities", {})
            if entity_id not in entities or "missing" in entities.get(entity_id, {}):
                return None

            entity_data = entities[entity_id]

            # Extract label
            labels = entity_data.get("labels", {})
            label = labels.get(self.config.language, {}).get("value", entity_id)

            # Extract description
            descriptions = entity_data.get("descriptions", {})
            description = descriptions.get(self.config.language, {}).get("value", "")

            # Extract aliases
            aliases_data = entity_data.get("aliases", {})
            aliases = [a.get("value", "") for a in aliases_data.get(self.config.language, [])]

            # Extract type from P31 (instance of)
            entity_type = None
            claims = entity_data.get("claims", {})
            p31_claims = claims.get("P31", [])
            if p31_claims:
                first_claim = p31_claims[0]
                mainsnak = first_claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                value = datavalue.get("value", {})
                entity_type = value.get("id")

            # Get Wikipedia URL if available
            sitelinks = entity_data.get("sitelinks", {})
            wiki_key = f"{self.config.language}wiki"
            url = None
            if wiki_key in sitelinks:
                wiki_title = sitelinks[wiki_key].get("title", "")
                if wiki_title:
                    url = f"https://{self.config.language}.wikipedia.org/wiki/{wiki_title.replace(' ', '_')}"

            if not url:
                url = f"{self.WIKIDATA_ENTITY_URL}{entity_id}"

            return KBEntity(
                entity_id=entity_id,
                kb_source="wikidata",
                label=label,
                description=description,
                aliases=aliases,
                entity_type=entity_type,
                url=url,
                extra_data={
                    "claims_count": len(claims),
                    "sitelinks_count": len(sitelinks)
                }
            )

        except requests.RequestException as e:
            logger.error(f"Wikidata get_entity error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Wikidata JSON parse error: {e}")
            return None


class UMLSClient(KnowledgeBaseClient):
    """
    Client for querying UMLS (Unified Medical Language System).

    UMLS is a comprehensive medical terminology database maintained by
    the National Library of Medicine. Requires an API key.

    API documentation: https://documentation.uts.nlm.nih.gov/rest/home.html
    """

    UMLS_API = "https://uts-ws.nlm.nih.gov/rest"

    def __init__(self, config: KnowledgeBaseConfig):
        super().__init__(config)
        if not config.api_key:
            logger.warning("UMLS client initialized without API key. Searches will fail.")

    def search(self, query: str, limit: int = 10, entity_type: Optional[str] = None) -> List[KBEntity]:
        """
        Search UMLS for concepts matching the query.

        Args:
            query: Search query string
            limit: Maximum number of results
            entity_type: Optional semantic type filter (e.g., "Disease or Syndrome")

        Returns:
            List of KBEntity objects
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for UMLS search")
            return []

        if not self.config.api_key:
            logger.error("UMLS API key required")
            return []

        if not query or not query.strip():
            return []

        params = {
            "apiKey": self.config.api_key,
            "string": query.strip(),
            "pageSize": min(limit, 50),
            "returnIdType": "code"
        }

        if entity_type:
            params["sabs"] = entity_type

        try:
            response = requests.get(
                f"{self.UMLS_API}/search/current",
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            results = []
            result_data = data.get("result", {})
            for item in result_data.get("results", []):
                cui = item.get("ui", "")
                entity = KBEntity(
                    entity_id=cui,
                    kb_source="umls",
                    label=item.get("name", ""),
                    description=item.get("rootSource", ""),
                    url=f"https://uts.nlm.nih.gov/uts/umls/concept/{cui}",
                    extra_data={
                        "root_source": item.get("rootSource", ""),
                        "uri": item.get("uri", "")
                    }
                )
                results.append(entity)

            return results

        except requests.RequestException as e:
            logger.error(f"UMLS search error: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"UMLS JSON parse error: {e}")
            return []

    def get_entity(self, entity_id: str) -> Optional[KBEntity]:
        """
        Get detailed information about a UMLS concept.

        Args:
            entity_id: UMLS CUI (Concept Unique Identifier)

        Returns:
            KBEntity with concept details, or None if not found
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for UMLS get_entity")
            return None

        if not self.config.api_key:
            logger.error("UMLS API key required")
            return None

        if not entity_id:
            return None

        try:
            # Get concept info
            response = requests.get(
                f"{self.UMLS_API}/content/current/CUI/{entity_id}",
                params={"apiKey": self.config.api_key},
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            result = data.get("result", {})
            if not result:
                return None

            # Get semantic types
            semantic_types = []
            for st in result.get("semanticTypes", []):
                semantic_types.append(st.get("name", ""))

            # Get definitions
            definitions_url = result.get("definitions", "")
            description = ""
            if definitions_url:
                try:
                    def_response = requests.get(
                        definitions_url,
                        params={"apiKey": self.config.api_key},
                        timeout=self.config.timeout
                    )
                    def_response.raise_for_status()
                    def_data = def_response.json()
                    defs = def_data.get("result", [])
                    if defs:
                        description = defs[0].get("value", "")
                except requests.RequestException:
                    pass

            return KBEntity(
                entity_id=entity_id,
                kb_source="umls",
                label=result.get("name", ""),
                description=description,
                entity_type=semantic_types[0] if semantic_types else None,
                url=f"https://uts.nlm.nih.gov/uts/umls/concept/{entity_id}",
                extra_data={
                    "semantic_types": semantic_types,
                    "atom_count": result.get("atomCount", 0),
                    "relation_count": result.get("relationCount", 0)
                }
            )

        except requests.RequestException as e:
            logger.error(f"UMLS get_entity error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"UMLS JSON parse error: {e}")
            return None


class RESTClient(KnowledgeBaseClient):
    """
    Generic REST API client for custom knowledge bases.

    Supports configurable endpoints for search and entity lookup.
    Expected response format can be customized via configuration.

    Configuration example:
        KnowledgeBaseConfig(
            name="my_kb",
            kb_type="rest",
            base_url="https://api.example.com",
            extra_params={
                "search_endpoint": "/search",
                "entity_endpoint": "/entity/{entity_id}",
                "search_query_param": "q",
                "results_path": "data.results",
                "entity_id_field": "id",
                "label_field": "name",
                "description_field": "description"
            }
        )
    """

    def __init__(self, config: KnowledgeBaseConfig):
        super().__init__(config)
        if not config.base_url:
            raise ValueError("REST client requires base_url in configuration")

        # Default field mappings
        self.search_endpoint = config.extra_params.get("search_endpoint", "/search")
        self.entity_endpoint = config.extra_params.get("entity_endpoint", "/entity/{entity_id}")
        self.search_query_param = config.extra_params.get("search_query_param", "q")
        self.results_path = config.extra_params.get("results_path", "results")
        self.entity_id_field = config.extra_params.get("entity_id_field", "id")
        self.label_field = config.extra_params.get("label_field", "label")
        self.description_field = config.extra_params.get("description_field", "description")
        self.aliases_field = config.extra_params.get("aliases_field", "aliases")
        self.type_field = config.extra_params.get("type_field", "type")
        self.url_field = config.extra_params.get("url_field", "url")

    def _get_nested_value(self, data: Dict, path: str) -> Any:
        """
        Get a nested value from a dictionary using dot notation.

        Args:
            data: Dictionary to search
            path: Dot-separated path (e.g., "data.results")

        Returns:
            Value at the path, or None if not found
        """
        parts = path.split(".")
        value = data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value

    def search(self, query: str, limit: int = 10, entity_type: Optional[str] = None) -> List[KBEntity]:
        """
        Search the REST API for entities.

        Args:
            query: Search query string
            limit: Maximum number of results
            entity_type: Optional entity type filter

        Returns:
            List of KBEntity objects
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for REST search")
            return []

        if not query or not query.strip():
            return []

        url = f"{self.config.base_url.rstrip('/')}{self.search_endpoint}"
        params = {
            self.search_query_param: query.strip(),
            "limit": limit
        }

        if entity_type:
            params["type"] = entity_type

        if self.config.api_key:
            params["api_key"] = self.config.api_key

        # Add any extra parameters
        for key, value in self.config.extra_params.items():
            if key.startswith("param_"):
                params[key[6:]] = value

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Extract results using configured path
            results_data = self._get_nested_value(data, self.results_path)
            if not results_data or not isinstance(results_data, list):
                return []

            results = []
            for item in results_data[:limit]:
                entity = KBEntity(
                    entity_id=str(item.get(self.entity_id_field, "")),
                    kb_source=self.config.name,
                    label=item.get(self.label_field, ""),
                    description=item.get(self.description_field, ""),
                    aliases=item.get(self.aliases_field, []) or [],
                    entity_type=item.get(self.type_field),
                    url=item.get(self.url_field)
                )
                results.append(entity)

            return results

        except requests.RequestException as e:
            logger.error(f"REST search error: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"REST JSON parse error: {e}")
            return []

    def get_entity(self, entity_id: str) -> Optional[KBEntity]:
        """
        Get entity details from the REST API.

        Args:
            entity_id: Entity identifier

        Returns:
            KBEntity if found, None otherwise
        """
        if not REQUESTS_AVAILABLE:
            logger.error("requests library not available for REST get_entity")
            return None

        if not entity_id:
            return None

        endpoint = self.entity_endpoint.replace("{entity_id}", entity_id)
        url = f"{self.config.base_url.rstrip('/')}{endpoint}"

        params = {}
        if self.config.api_key:
            params["api_key"] = self.config.api_key

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            item = response.json()

            return KBEntity(
                entity_id=str(item.get(self.entity_id_field, entity_id)),
                kb_source=self.config.name,
                label=item.get(self.label_field, ""),
                description=item.get(self.description_field, ""),
                aliases=item.get(self.aliases_field, []) or [],
                entity_type=item.get(self.type_field),
                url=item.get(self.url_field)
            )

        except requests.RequestException as e:
            logger.error(f"REST get_entity error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"REST JSON parse error: {e}")
            return None


# Registry of available KB clients
KB_CLIENT_REGISTRY: Dict[str, type] = {
    "wikidata": WikidataClient,
    "umls": UMLSClient,
    "rest": RESTClient
}


def get_kb_client(config: KnowledgeBaseConfig) -> KnowledgeBaseClient:
    """
    Factory function to create a KB client based on configuration.

    Args:
        config: KnowledgeBaseConfig specifying the KB type and settings

    Returns:
        KnowledgeBaseClient instance

    Raises:
        ValueError: If kb_type is not supported
    """
    kb_type = config.kb_type.lower()
    if kb_type not in KB_CLIENT_REGISTRY:
        supported = ", ".join(KB_CLIENT_REGISTRY.keys())
        raise ValueError(f"Unsupported KB type '{kb_type}'. Supported types: {supported}")

    client_class = KB_CLIENT_REGISTRY[kb_type]
    return client_class(config)


def register_kb_client(kb_type: str, client_class: type):
    """
    Register a custom KB client class.

    Args:
        kb_type: Type identifier for the client
        client_class: KnowledgeBaseClient subclass
    """
    if not issubclass(client_class, KnowledgeBaseClient):
        raise TypeError("client_class must be a subclass of KnowledgeBaseClient")
    KB_CLIENT_REGISTRY[kb_type.lower()] = client_class


# KB manager for handling multiple configured knowledge bases
class KnowledgeBaseManager:
    """
    Manager for multiple knowledge base configurations.

    Maintains a registry of configured KBs and provides unified
    search across multiple sources.
    """

    def __init__(self):
        self._clients: Dict[str, KnowledgeBaseClient] = {}
        self._configs: Dict[str, KnowledgeBaseConfig] = {}

    def configure_from_yaml(self, kb_config: Dict[str, Any]) -> None:
        """
        Configure knowledge bases from YAML configuration.

        Expected format:
            entity_linking:
              enabled: true
              knowledge_bases:
                - name: "wikidata"
                  type: "wikidata"
                  language: "en"
                - name: "umls"
                  type: "umls"
                  api_key: "${UMLS_API_KEY}"

        Args:
            kb_config: Dictionary from YAML configuration
        """
        if not kb_config.get("enabled", False):
            return

        for kb in kb_config.get("knowledge_bases", []):
            config = KnowledgeBaseConfig(
                name=kb.get("name", ""),
                kb_type=kb.get("type", ""),
                api_key=kb.get("api_key"),
                base_url=kb.get("base_url"),
                language=kb.get("language", "en"),
                timeout=kb.get("timeout", 10),
                extra_params=kb.get("extra_params", {})
            )

            try:
                client = get_kb_client(config)
                self._clients[config.name] = client
                self._configs[config.name] = config
                logger.info(f"Configured KB client: {config.name} ({config.kb_type})")
            except Exception as e:
                logger.error(f"Failed to configure KB '{config.name}': {e}")

    def add_client(self, name: str, client: KnowledgeBaseClient) -> None:
        """Add a pre-configured client."""
        self._clients[name] = client

    def get_client(self, name: str) -> Optional[KnowledgeBaseClient]:
        """Get a configured KB client by name."""
        return self._clients.get(name)

    def get_config(self, name: str) -> Optional[KnowledgeBaseConfig]:
        """Get KB configuration by name."""
        return self._configs.get(name)

    def list_clients(self) -> List[str]:
        """List names of all configured KB clients."""
        return list(self._clients.keys())

    def search_all(self, query: str, limit: int = 10) -> Dict[str, List[KBEntity]]:
        """
        Search all configured knowledge bases.

        Args:
            query: Search query
            limit: Max results per KB

        Returns:
            Dictionary mapping KB name to list of results
        """
        results = {}
        for name, client in self._clients.items():
            try:
                results[name] = client.search(query, limit=limit)
            except Exception as e:
                logger.error(f"Search failed for KB '{name}': {e}")
                results[name] = []
        return results

    def search(self, query: str, kb_name: str, limit: int = 10) -> List[KBEntity]:
        """
        Search a specific knowledge base.

        Args:
            query: Search query
            kb_name: Name of the KB to search
            limit: Max results

        Returns:
            List of KBEntity results
        """
        client = self.get_client(kb_name)
        if not client:
            logger.warning(f"KB '{kb_name}' not configured")
            return []

        try:
            return client.search(query, limit=limit)
        except Exception as e:
            logger.error(f"Search failed for KB '{kb_name}': {e}")
            return []


# Global KB manager instance
_kb_manager: Optional[KnowledgeBaseManager] = None


def get_kb_manager() -> KnowledgeBaseManager:
    """Get or create the global KB manager."""
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager


def init_kb_manager(config: Dict[str, Any]) -> KnowledgeBaseManager:
    """
    Initialize the KB manager from configuration.

    Args:
        config: Full application config dictionary

    Returns:
        Configured KnowledgeBaseManager
    """
    global _kb_manager
    _kb_manager = KnowledgeBaseManager()

    # Look for entity_linking config in annotation_schemes
    for scheme in config.get("annotation_schemes", []):
        if scheme.get("annotation_type") == "span":
            entity_linking = scheme.get("entity_linking", {})
            if entity_linking:
                _kb_manager.configure_from_yaml(entity_linking)

    return _kb_manager
