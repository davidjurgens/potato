"""
Per-Cohort Schema Assignment

Lets different annotator cohorts receive different (or subset) annotation
schemes, reusing the existing batch-assignment cohort machinery. The global
``annotation_schemes`` list stays as the default/fallback, so configs without
``scheme_sets`` or per-group ``schemes`` behave exactly as before.

Config shape
------------
    annotation_schemes: [ ... ]          # global default / fallback
    scheme_sets:                         # optional, named reusable sets
      minimal: [sentiment]               # references global scheme names
    batch_assignment:
      groups:
        - {name: cohortA, annotators: [alice], data_file: a.csv, schemes: minimal}
        - {name: cohortB, annotators: [bob],   data_file: b.csv, schemes: [sentiment, topic]}
        - {name: cohortC, data_file: c.csv}    # no schemes -> global fallback

A group's ``schemes`` binding may be a scheme-set name, a list of global scheme
names (a subset), or a list of inline scheme dicts (or a mix of names + dicts).

A user's cohort is resolved via the ItemStateManager's batch-group membership
(explicit ``groups[].annotators`` or the auto-assign pin map), so cohorts are
declared once and drive both item assignment and schema selection.
"""

import copy
import logging
import re
import threading

logger = logging.getLogger(__name__)


def _slugify(name):
    """Stable filesystem-safe slug for a cohort name (used in layout/site names)."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name)).strip("-").lower()
    return slug or "cohort"


class CohortSchemeResolver:
    """Resolves the annotation-scheme list a given user/cohort should see."""

    def __init__(self, config):
        self.config = config or {}
        self._global_schemes = self.config.get("annotation_schemes") or []
        self._global_by_name = {
            s.get("name"): s
            for s in self._global_schemes
            if isinstance(s, dict) and s.get("name")
        }

        # Named reusable scheme sets -> resolved scheme lists.
        self._scheme_sets = {}
        for name, members in (self.config.get("scheme_sets") or {}).items():
            self._scheme_sets[name] = self._resolve_binding(members)

        # Per-cohort resolved scheme lists, keyed by group name.
        self._cohort_schemes = {}
        batch = self.config.get("batch_assignment")
        if isinstance(batch, dict):
            for idx, group in enumerate(batch.get("groups") or []):
                if not isinstance(group, dict):
                    continue
                name = group.get("name") or f"group_{idx}"
                if "schemes" in group and group["schemes"] is not None:
                    self._cohort_schemes[name] = self._resolve_binding(group["schemes"])

    # ------------------------------------------------------------------
    # Binding resolution (str scheme-set name | list of names/inline dicts)
    # ------------------------------------------------------------------
    def _resolve_binding(self, binding):
        """Normalize a ``schemes`` binding into a concrete list of scheme dicts."""
        if binding is None:
            return list(self._global_schemes)
        if isinstance(binding, str):
            if binding in self._scheme_sets:
                return list(self._scheme_sets[binding])
            if binding in self._global_by_name:
                return [self._global_by_name[binding]]
            logger.warning("scheme binding '%s' did not resolve; using global", binding)
            return list(self._global_schemes)

        resolved = []
        for member in binding or []:
            if isinstance(member, str):
                scheme = self._global_by_name.get(member)
                if scheme is not None:
                    resolved.append(scheme)
                else:
                    logger.warning("scheme name '%s' not in annotation_schemes; skipped", member)
            elif isinstance(member, dict):
                resolved.append(member)
        return resolved or list(self._global_schemes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def has_cohort_schemes(self):
        """True if any cohort binds its own scheme set (feature is in use)."""
        return bool(self._cohort_schemes)

    def get_cohort_for_user(self, username):
        """Return the user's cohort/group name, or None if unassigned.

        Delegates to the ItemStateManager, which owns batch-group membership
        (explicit config groups and auto-assign pins).
        """
        if not username:
            return None
        try:
            from potato.item_state_management import get_item_state_manager
            ism = get_item_state_manager()
            if ism is None:
                return None
            return ism.get_group_name_for_user(username)
        except Exception as e:
            logger.debug("cohort lookup failed for %s: %s", username, e)
            return None

    def get_schemes_for_cohort(self, cohort_name):
        """Scheme list bound to a cohort, or the global list as fallback."""
        if cohort_name and cohort_name in self._cohort_schemes:
            return self._cohort_schemes[cohort_name]
        return list(self._global_schemes)

    def get_schemes_for_user(self, username):
        """Scheme list the given user should see (cohort set or global)."""
        if not self._cohort_schemes:
            return list(self._global_schemes)
        cohort = self.get_cohort_for_user(username)
        return self.get_schemes_for_cohort(cohort)

    def all_cohort_scheme_sets(self):
        """Mapping of cohort name -> resolved scheme list (cohorts w/ bindings)."""
        return dict(self._cohort_schemes)

    def union_of_all_schemes(self):
        """Union of global + every cohort's schemes, deduped by scheme name.

        Used for the adjudication view, where an adjudicator reviews all cohorts.
        Preserves the global order first, then appends any cohort-only schemes.
        """
        seen = set()
        union = []
        for scheme in self._global_schemes:
            name = scheme.get("name") if isinstance(scheme, dict) else None
            key = name or id(scheme)
            if key not in seen:
                seen.add(key)
                union.append(scheme)
        for schemes in self._cohort_schemes.values():
            for scheme in schemes:
                name = scheme.get("name") if isinstance(scheme, dict) else None
                key = name or id(scheme)
                if key not in seen:
                    seen.add(key)
                    union.append(scheme)
        return union

    def scheme_names_for_user(self, username):
        """Set of scheme names the user is allowed to submit (for validation)."""
        return {
            s.get("name")
            for s in self.get_schemes_for_user(username)
            if isinstance(s, dict) and s.get("name")
        }

    def layout_name_for_cohort(self, cohort_name):
        """Stable slug used as the layout/site suffix for a cohort."""
        return _slugify(cohort_name)

    def deep_copy_cohort_schemes(self):
        """Deep-copied {cohort_name: schemes} for independent layout baking.

        Layout generation mutates scheme dicts in place (annotation_id,
        keybinding allocation); cohorts must not share dict identity with the
        global list or with each other.
        """
        return {
            name: copy.deepcopy(schemes)
            for name, schemes in self._cohort_schemes.items()
        }


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------
_COHORT_RESOLVER = None
_COHORT_LOCK = threading.Lock()


def init_cohort_scheme_resolver(config):
    """Initialize (or reinitialize) the singleton CohortSchemeResolver."""
    global _COHORT_RESOLVER
    with _COHORT_LOCK:
        _COHORT_RESOLVER = CohortSchemeResolver(config)
    return _COHORT_RESOLVER


def get_cohort_scheme_resolver():
    """Get the singleton resolver, lazily building it from the app config."""
    global _COHORT_RESOLVER
    if _COHORT_RESOLVER is None:
        with _COHORT_LOCK:
            if _COHORT_RESOLVER is None:
                try:
                    from potato.flask_server import config as _config
                except Exception:
                    _config = {}
                _COHORT_RESOLVER = CohortSchemeResolver(_config)
    return _COHORT_RESOLVER


def clear_cohort_scheme_resolver():
    """Clear the singleton (for testing)."""
    global _COHORT_RESOLVER
    with _COHORT_LOCK:
        _COHORT_RESOLVER = None
