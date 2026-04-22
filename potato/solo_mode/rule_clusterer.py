"""
Rule Clusterer for Solo Mode

Clusters edge case rules by semantic similarity, then aggregates each cluster
into a summary category using an LLM. Follows the Co-DETECT pipeline:
embed -> cluster -> aggregate -> merge redundant categories.

Uses the same embedding approach as DiversityManager (sentence-transformers
with TF-IDF fallback).
"""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .edge_case_rules import EdgeCaseCategory, EdgeCaseRule

logger = logging.getLogger(__name__)

# Guarded imports
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    from sklearn.cluster import KMeans
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    _SENTENCE_TRANSFORMERS_AVAILABLE = False
    np = None
    KMeans = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


AGGREGATION_PROMPT_TEMPLATE = """You are analyzing a cluster of edge case rules discovered during annotation.
Each rule describes a situation where the annotator was uncertain about the correct label.

Your task: Synthesize these individual rules into ONE concise summary rule that captures
the common pattern across all rules in this cluster.

Individual rules:
{rules_text}

Respond with JSON:
{{
    "summary_rule": "<A single concise rule in 'When <condition> -> <action>' format>"
}}
"""

MERGE_PROMPT_TEMPLATE = """You are reviewing edge case categories for redundancy.
Determine if any of these categories are semantically redundant and should be merged.

Categories:
{categories_text}

Respond with JSON:
{{
    "merge_groups": [
        {{
            "merged_summary": "<Combined rule text>",
            "category_ids": ["<id1>", "<id2>"]
        }}
    ]
}}

If no categories should be merged, respond with:
{{"merge_groups": []}}
"""


class RuleClusterer:
    """Clusters edge case rules and aggregates them into categories.

    Pipeline: embed -> cluster -> aggregate -> merge
    """

    def __init__(
        self,
        app_config: Dict[str, Any],
        solo_config: Any,
    ):
        """Initialize the rule clusterer.

        Args:
            app_config: Full application configuration
            solo_config: SoloModeConfig instance
        """
        self.app_config = app_config
        self.solo_config = solo_config
        self._model = None
        self._endpoint = None

    def _get_embedding_model(self) -> Optional[Any]:
        """Get or create the sentence-transformer model."""
        if not _SENTENCE_TRANSFORMERS_AVAILABLE:
            return None
        if self._model is None:
            model_name = getattr(
                self.solo_config.embedding, 'model_name', 'all-MiniLM-L6-v2'
            )
            try:
                self._model = SentenceTransformer(model_name)
            except Exception as e:
                logger.warning(f"Could not load sentence-transformer model: {e}")
                return None
        return self._model

    def _get_revision_endpoint(self) -> Optional[Any]:
        """Get or create an AI endpoint for aggregation/merging."""
        if self._endpoint is not None:
            return self._endpoint

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            models = self.solo_config.revision_models or self.solo_config.labeling_models
            for model_config in models:
                try:
                    endpoint_config = {
                        'ai_support': {
                            'enabled': True,
                            'endpoint_type': model_config.endpoint_type,
                            'ai_config': {
                                'model': model_config.model,
                                'max_tokens': model_config.max_tokens,
                                'temperature': 0.3,
                            }
                        }
                    }
                    if model_config.api_key:
                        endpoint_config['ai_support']['ai_config']['api_key'] = model_config.api_key
                    if model_config.base_url:
                        endpoint_config['ai_support']['ai_config']['base_url'] = model_config.base_url

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        return endpoint
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Could not create revision endpoint: {e}")

        return None

    def embed_rules(self, rules: List[EdgeCaseRule]) -> Optional[Any]:
        """Compute embeddings for rule texts.

        Args:
            rules: List of edge case rules to embed

        Returns:
            Numpy array of embeddings, or None if embedding fails
        """
        texts = [r.rule_text for r in rules]

        # Try sentence-transformers first
        model = self._get_embedding_model()
        if model is not None:
            try:
                embeddings = model.encode(texts, show_progress_bar=False)
                return embeddings
            except Exception as e:
                logger.warning(f"Sentence-transformer embedding failed: {e}")

        # Fallback to TF-IDF
        return self._tfidf_embed(texts)

    def _tfidf_embed(self, texts: List[str]) -> Optional[Any]:
        """Fallback TF-IDF embedding."""
        if not _SKLEARN_AVAILABLE:
            logger.warning(
                "Neither sentence-transformers nor sklearn available for embedding"
            )
            return None

        try:
            vectorizer = TfidfVectorizer(max_features=256, stop_words='english')
            embeddings = vectorizer.fit_transform(texts).toarray()
            return embeddings
        except Exception as e:
            logger.warning(f"TF-IDF embedding failed: {e}")
            return None

    def project_to_2d(
        self,
        rules: List[EdgeCaseRule],
    ) -> List[Tuple[float, float]]:
        """Project rule embeddings to 2D coordinates for visualization.

        Uses PCA (or first 2 dimensions as fallback) to reduce
        high-dimensional embeddings to plottable 2D points.

        Args:
            rules: Rules to project

        Returns:
            List of (x, y) tuples, one per rule
        """
        if not rules:
            return []

        embeddings = self.embed_rules(rules)

        if embeddings is None:
            return [(0.0, 0.0)] * len(rules)

        try:
            import numpy as _np
            emb_array = _np.array(embeddings)
        except (ImportError, Exception):
            # Raw fallback: first 2 dimensions
            result = []
            for e in embeddings:
                row = list(e) if hasattr(e, '__iter__') else [0.0]
                x = float(row[0]) if len(row) > 0 else 0.0
                y = float(row[1]) if len(row) > 1 else 0.0
                result.append((x, y))
            return result

        if emb_array.shape[0] < 2:
            return [(float(emb_array[0, 0]) if emb_array.shape[1] > 0 else 0.0,
                     float(emb_array[0, 1]) if emb_array.shape[1] > 1 else 0.0)]

        # Try PCA
        try:
            from sklearn.decomposition import PCA

            n_components = min(2, emb_array.shape[0], emb_array.shape[1])
            pca = PCA(n_components=n_components)
            coords = pca.fit_transform(emb_array)

            result = []
            for c in coords:
                x = float(c[0])
                y = float(c[1]) if n_components > 1 else 0.0
                result.append((x, y))
            return result

        except ImportError:
            pass

        # Fallback: first 2 dimensions
        result = []
        for i in range(emb_array.shape[0]):
            x = float(emb_array[i, 0]) if emb_array.shape[1] > 0 else 0.0
            y = float(emb_array[i, 1]) if emb_array.shape[1] > 1 else 0.0
            result.append((x, y))
        return result

    def cluster_rules(
        self,
        rules: List[EdgeCaseRule],
        embeddings: Any,
    ) -> Dict[int, List[EdgeCaseRule]]:
        """Cluster rules using size-constrained K-Means.

        Args:
            rules: Rules to cluster
            embeddings: Precomputed embeddings (numpy array)

        Returns:
            Dict mapping cluster_id to list of rules in that cluster
        """
        if embeddings is None or len(rules) == 0:
            return {0: rules}

        if not _SENTENCE_TRANSFORMERS_AVAILABLE and np is None:
            try:
                import numpy as _np
            except ImportError:
                return {0: rules}

        _np = np
        if _np is None:
            import numpy as _np

        target_size = self.solo_config.edge_case_rules.target_cluster_size
        n_clusters = max(1, len(rules) // target_size + 1)

        # Cap clusters at number of rules
        n_clusters = min(n_clusters, len(rules))

        if n_clusters <= 1:
            return {0: rules}

        try:
            from sklearn.cluster import KMeans as _KMeans

            kmeans = _KMeans(
                n_clusters=n_clusters,
                random_state=42,
                n_init=10,
            )
            labels = kmeans.fit_predict(embeddings)

            # Build cluster dict
            clusters: Dict[int, List[EdgeCaseRule]] = {}
            for rule, label in zip(rules, labels):
                cluster_id = int(label)
                if cluster_id not in clusters:
                    clusters[cluster_id] = []
                clusters[cluster_id].append(rule)

            # Redistribute oversized/undersized clusters
            clusters = self._rebalance_clusters(clusters, target_size)

            return clusters

        except Exception as e:
            logger.warning(f"Clustering failed: {e}")
            return {0: rules}

    def _rebalance_clusters(
        self,
        clusters: Dict[int, List[EdgeCaseRule]],
        target_size: int,
    ) -> Dict[int, List[EdgeCaseRule]]:
        """Redistribute items from oversized to undersized clusters.

        Ensures clusters stay within [target_size/2, target_size*2] range
        when possible.
        """
        max_size = target_size * 2
        min_size = max(1, target_size // 2)

        # Collect overflow items
        overflow = []
        for cid, members in list(clusters.items()):
            if len(members) > max_size:
                overflow.extend(members[max_size:])
                clusters[cid] = members[:max_size]

        # Distribute overflow to undersized clusters
        for cid in list(clusters.keys()):
            if not overflow:
                break
            deficit = min_size - len(clusters[cid])
            if deficit > 0:
                to_add = overflow[:deficit]
                clusters[cid].extend(to_add)
                overflow = overflow[deficit:]

        # If still overflow, create new clusters
        if overflow:
            new_id = max(clusters.keys()) + 1
            while overflow:
                batch = overflow[:target_size]
                overflow = overflow[target_size:]
                clusters[new_id] = batch
                new_id += 1

        return clusters

    def aggregate_cluster(
        self,
        cluster_rules: List[EdgeCaseRule],
    ) -> Optional[str]:
        """Synthesize a summary rule from a cluster of similar rules.

        Uses the revision model to produce a concise summary.

        Args:
            cluster_rules: Rules in a single cluster

        Returns:
            Summary rule text, or None if aggregation fails
        """
        if not cluster_rules:
            return None

        # If only one rule, use it directly
        if len(cluster_rules) == 1:
            return cluster_rules[0].rule_text

        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            # Fallback: use the first rule as representative
            return cluster_rules[0].rule_text

        rules_text = "\n".join(
            f"- {r.rule_text}" for r in cluster_rules
        )
        prompt = AGGREGATION_PROMPT_TEMPLATE.format(rules_text=rules_text)

        try:
            response = endpoint.query(prompt)
            response_data = self._parse_json(response)
            summary = response_data.get('summary_rule', '')
            if summary:
                return summary
        except Exception as e:
            logger.warning(f"Cluster aggregation failed: {e}")

        # Fallback
        return cluster_rules[0].rule_text

    def merge_categories(
        self,
        categories: List[EdgeCaseCategory],
    ) -> List[EdgeCaseCategory]:
        """Detect and merge redundant categories.

        Uses embedding similarity to find near-duplicates, then
        uses the LLM to merge them.

        Args:
            categories: List of categories to check for redundancy

        Returns:
            Deduplicated list of categories
        """
        if len(categories) <= 1:
            return categories

        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return categories

        categories_text = "\n".join(
            f"- ID: {c.id} | Rule: {c.summary_rule}"
            for c in categories
        )
        prompt = MERGE_PROMPT_TEMPLATE.format(categories_text=categories_text)

        try:
            response = endpoint.query(prompt)
            response_data = self._parse_json(response)
            merge_groups = response_data.get('merge_groups', [])

            if not merge_groups:
                return categories

            # Build category lookup
            cat_map = {c.id: c for c in categories}
            merged_ids = set()

            result = []
            for group in merge_groups:
                group_ids = group.get('category_ids', [])
                merged_summary = group.get('merged_summary', '')
                if len(group_ids) < 2 or not merged_summary:
                    continue

                # Combine member rules from all categories in group
                combined_members = []
                for cid in group_ids:
                    if cid in cat_map:
                        combined_members.extend(cat_map[cid].member_rule_ids)
                        merged_ids.add(cid)

                # Create merged category
                new_cat = EdgeCaseCategory(
                    id=f"cat_{uuid.uuid4().hex[:8]}",
                    summary_rule=merged_summary,
                    member_rule_ids=combined_members,
                )
                result.append(new_cat)

            # Add categories that weren't merged
            for c in categories:
                if c.id not in merged_ids:
                    result.append(c)

            return result

        except Exception as e:
            logger.warning(f"Category merging failed: {e}")
            return categories

    def run_full_pipeline(
        self,
        rules: List[EdgeCaseRule],
    ) -> List[EdgeCaseCategory]:
        """Run the complete clustering pipeline: embed -> cluster -> aggregate -> merge.

        Args:
            rules: Unclustered edge case rules

        Returns:
            List of EdgeCaseCategory objects
        """
        if not rules:
            return []

        logger.info(f"Starting rule clustering pipeline with {len(rules)} rules")

        # Step 1: Embed
        embeddings = self.embed_rules(rules)

        # Step 2: Cluster
        clusters = self.cluster_rules(rules, embeddings)
        logger.info(f"Formed {len(clusters)} clusters")

        # Step 3: Aggregate each cluster into a category
        categories = []
        for cluster_id, cluster_rules in clusters.items():
            summary = self.aggregate_cluster(cluster_rules)
            if summary:
                cat = EdgeCaseCategory(
                    id=f"cat_{uuid.uuid4().hex[:8]}",
                    summary_rule=summary,
                    member_rule_ids=[r.id for r in cluster_rules],
                )
                categories.append(cat)

        # Step 4: Merge redundant categories
        if len(categories) > 1:
            categories = self.merge_categories(categories)

        logger.info(f"Pipeline complete: {len(categories)} categories")
        return categories

    def _parse_json(self, response: Any) -> Dict[str, Any]:
        """Parse JSON from an LLM response."""
        if isinstance(response, dict):
            return response
        if hasattr(response, 'model_dump'):
            return response.model_dump()

        content = str(response).strip()

        # Extract from markdown code blocks
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if match:
            content = match.group(1).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}
