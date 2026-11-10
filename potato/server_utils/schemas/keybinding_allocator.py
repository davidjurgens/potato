"""
Keybinding Allocator

Centralized allocation of non-conflicting keyboard shortcuts across all
annotation schemas. When multiple schemas use sequential_key_binding: true,
this module assigns keys from separate pools so they don't overlap.

Key pools (QWERTY layout):
  Pool 0: 1 2 3 4 5 6 7 8 9 0   (number row)
  Pool 1: q w e r t y u i o p   (top letter row)
  Pool 2: a s d f g h j k l     (home row)

Schemas that self-manage keys (pairwise, bws, triage) pre-claim the keys they
bind, as do explicit per-label key_value settings in any schema. Explicit keys
are always honored; a key bound by two schemas is logged, because only one of
them responds to it.
"""

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

KEY_POOLS = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
]

# Schema types that manage their own keybindings internally
SELF_MANAGED_TYPES = {'pairwise', 'bws', 'triage'}


def _get_label_name(label_data):
    """Extract the label name from a label entry (string or dict)."""
    if isinstance(label_data, str):
        return label_data
    if isinstance(label_data, Mapping):
        return label_data.get("name", "")
    return str(label_data)


def _get_explicit_key(label_data):
    """Extract explicit key_value from a label entry, or None."""
    if isinstance(label_data, Mapping):
        kv = label_data.get("key_value")
        if kv is not None:
            return str(kv).lower()
    return None


def _hardcoded_keys(scheme):
    """
    The keys a self-managed schema binds, read from the schema's own module so
    the two cannot disagree. Lowercase, as label shortcuts are matched.
    """
    ann_type = scheme.get("annotation_type", "")
    if ann_type == "pairwise":
        # Only binary mode binds keys (pairwise.py); scale and multi_dimension
        # have none, and 0 is the tie button's.
        if (scheme.get("mode", "binary") != "binary"
                or not scheme.get("sequential_key_binding", True)):
            return []
        return ["1", "2", "0"] if scheme.get("allow_tie", False) else ["1", "2"]
    if ann_type == "bws":
        if not scheme.get("sequential_key_binding", True):
            return []
        from .bws import bws_keys
        best, worst = bws_keys(scheme.get("tuple_size", 4))
        return best + worst
    if ann_type == "triage":
        from .triage import DEFAULT_KEYBINDINGS
        return [str(scheme.get(f"{action}_key", default)).lower()
                for action, default in DEFAULT_KEYBINDINGS.items()]
    return []


def _labels_for_allocation(scheme):
    """
    A likert has no ``labels``; its points are named "1".."size", which is what
    likert.py looks up in ``_allocated_keys``. Without this a sequential likert
    was allocated nothing and fell back to 1..size whatever else held them.
    """
    if scheme.get("annotation_type") == "likert" and not scheme.get("labels"):
        size = scheme.get("size")
        if isinstance(size, int) and 0 < size <= 10:
            return [str(i) for i in range(1, size + 1)]
        return []
    return scheme.get("labels", []) or []


def _needs_allocation(scheme):
    """Check if a schema needs keybinding allocation."""
    ann_type = scheme.get("annotation_type", "")
    if ann_type in SELF_MANAGED_TYPES:
        return False

    strategy = scheme.get("keybinding_strategy", "")
    if strategy == "none":
        return False

    # Explicit sequential_key_binding
    if scheme.get("sequential_key_binding"):
        return True

    # keybinding_strategy set to sequential or mnemonic
    if strategy in ("sequential", "mnemonic"):
        return True

    return False


def _assign_mnemonic_keys(labels, used_keys):
    """
    Assign mnemonic keys based on first available letter of each label name.
    Falls back to next available letter if the preferred one is taken.

    Returns list of (label_name, key) tuples.
    """
    # All available mnemonic letters
    all_letters = list('abcdefghijklmnopqrstuvwxyz')
    available = [c for c in all_letters if c not in used_keys]

    assignments = []
    for label_data in labels:
        label_name = _get_label_name(label_data)
        explicit = _get_explicit_key(label_data)
        if explicit:
            assignments.append((label_name, explicit))
            continue

        # Try each character of the label name
        assigned = False
        for char in label_name.lower():
            if char.isalpha() and char in available:
                assignments.append((label_name, char))
                available.remove(char)
                assigned = True
                break

        if not assigned:
            # Fall back to next available letter
            if available:
                key = available.pop(0)
                assignments.append((label_name, key))
                logger.warning(
                    f"No mnemonic match for '{label_name}', "
                    f"assigned fallback key '{key}'"
                )
            else:
                assignments.append((label_name, None))
                logger.warning(
                    f"No keys available for label '{label_name}'"
                )

    return assignments


def allocate_keybindings(annotation_schemes):
    """
    Pre-allocate non-conflicting keys across all annotation schemas.

    Args:
        annotation_schemes: List of annotation scheme dicts from config.

    Returns:
        dict: {schema_name: [{"label": str, "key": str|None}, ...]}
              Only schemas that need allocation are included.
    """
    # Steps 1-2: claim every key already bound on the page, by any schema:
    # explicit key_value on any label (a schema that is not allocated still
    # binds it), and the keys self-managed schemas hard-code.
    globally_used = set()
    owners = {}

    for scheme in annotation_schemes:
        name = scheme.get("name", "")
        claimed = [(_get_explicit_key(label_data), _get_label_name(label_data))
                   for label_data in (scheme.get("labels") or [])]
        claimed += [(key, None) for key in _hardcoded_keys(scheme)]
        for key, label in claimed:
            if not key:
                continue
            globally_used.add(key)
            owners.setdefault(key, {}).setdefault(name, label)

    for key, by_schema in owners.items():
        if len(by_schema) > 1:
            names = ", ".join(f"'{s}'" + (f" (label '{l}')" if l else "")
                              for s, l in by_schema.items())
            logger.warning(
                f"Key '{key}' is bound by more than one schema: {names}. Only one "
                f"of them responds to it; set a different key_value or turn off "
                f"sequential_key_binding on one.")

    # Step 3: Build available pools (excluding globally used keys)
    available_pools = []
    for pool in KEY_POOLS:
        available = [k for k in pool if k not in globally_used]
        available_pools.append(available)

    # Step 4: Allocate keys to schemas that need them
    allocation = {}
    next_pool_idx = 0

    for scheme in annotation_schemes:
        if not _needs_allocation(scheme):
            continue

        name = scheme.get("name", "")
        labels = _labels_for_allocation(scheme)
        strategy = scheme.get("keybinding_strategy", "sequential")

        if strategy == "mnemonic":
            # Mnemonic allocation uses label name letters
            assignments = _assign_mnemonic_keys(labels, globally_used)
            result = []
            for label_name, key in assignments:
                result.append({"label": label_name, "key": key})
                if key:
                    globally_used.add(key)
            allocation[name] = result
            continue

        # Sequential allocation from pools
        # Count how many keys we need (subtract explicit ones)
        needed = 0
        for label_data in labels:
            if _get_explicit_key(label_data) is None:
                needed += 1

        # Find a pool with enough capacity
        assigned_pool = None
        for pool_idx in range(next_pool_idx, len(available_pools)):
            if len(available_pools[pool_idx]) >= needed:
                assigned_pool = pool_idx
                break

        if assigned_pool is None:
            # Try earlier pools too (in case first schema used mnemonic)
            for pool_idx in range(len(available_pools)):
                if len(available_pools[pool_idx]) >= needed:
                    assigned_pool = pool_idx
                    break

        if assigned_pool is None:
            # Not enough keys in any single pool — assign what we can
            logger.warning(
                f"Schema '{name}' has {needed} labels needing keys "
                f"but no single pool has enough capacity. "
                f"Some labels will not have keybindings."
            )
            # Use the pool with the most remaining keys
            assigned_pool = max(
                range(len(available_pools)),
                key=lambda i: len(available_pools[i])
            )

        pool_keys = available_pools[assigned_pool]
        key_iter = iter(pool_keys)

        result = []
        consumed = []
        for label_data in labels:
            label_name = _get_label_name(label_data)
            explicit = _get_explicit_key(label_data)
            if explicit:
                result.append({"label": label_name, "key": explicit})
            else:
                key = next(key_iter, None)
                if key:
                    result.append({"label": label_name, "key": key})
                    consumed.append(key)
                    globally_used.add(key)
                else:
                    result.append({"label": label_name, "key": None})

        # Remove consumed keys from the pool
        available_pools[assigned_pool] = [
            k for k in available_pools[assigned_pool] if k not in consumed
        ]

        allocation[name] = result

        # Advance to next pool for the next schema
        if assigned_pool == next_pool_idx:
            next_pool_idx = assigned_pool + 1

    return allocation
