"""Survey Instruments Library - load standard validated questionnaires.

This module provides access to a library of validated survey instruments
(PHQ-9, TIPI, PANAS, etc.) for use in prestudy and poststudy phases.

Usage in config.yaml:
    phases:
      poststudy:
        type: poststudy
        instrument: "phq-9"

Or multiple instruments:
    phases:
      poststudy:
        type: poststudy
        instruments:
          - "phq-9"
          - "gad-7"
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

INSTRUMENTS_DIR = Path(__file__).parent / "instruments"
REGISTRY_FILE = Path(__file__).parent / "registry.json"

_registry_cache: Optional[Dict] = None
_instruments_cache: Dict[str, Dict] = {}


def get_registry() -> Dict:
    """Load the instrument registry (cached).

    Returns:
        Dict containing instrument metadata and category mappings.
    """
    global _registry_cache
    if _registry_cache is None:
        with open(REGISTRY_FILE, encoding='utf-8') as f:
            _registry_cache = json.load(f)
    return _registry_cache


def get_instrument(instrument_id: str) -> Dict:
    """Load full instrument definition by ID.

    Args:
        instrument_id: The instrument identifier (e.g., "phq-9", "tipi").

    Returns:
        Dict containing full instrument definition including questions.

    Raises:
        ValueError: If instrument_id is not found in registry.
    """
    if instrument_id not in _instruments_cache:
        registry = get_registry()
        if instrument_id not in registry["instruments"]:
            available = sorted(registry["instruments"].keys())
            raise ValueError(
                f"Unknown instrument: '{instrument_id}'. "
                f"Available instruments: {available}"
            )

        filename = registry["instruments"][instrument_id]["file"]
        with open(INSTRUMENTS_DIR / filename, encoding='utf-8') as f:
            _instruments_cache[instrument_id] = json.load(f)
    return _instruments_cache[instrument_id]


def get_instrument_questions(instrument_id: str) -> List[Dict]:
    """Get annotation scheme questions for an instrument.

    Args:
        instrument_id: The instrument identifier.

    Returns:
        List of annotation scheme dicts ready for use in phases.
    """
    return get_instrument(instrument_id)["questions"]


def list_instruments(category: Optional[str] = None) -> List[Dict]:
    """List available instruments with metadata.

    Args:
        category: Optional category filter (e.g., "personality", "mental_health").

    Returns:
        List of dicts with instrument id and metadata.
    """
    registry = get_registry()
    instruments = registry["instruments"]

    if category:
        category_ids = registry.get("categories", {}).get(category, [])
        instruments = {k: v for k, v in instruments.items() if k in category_ids}

    return [{"id": k, **v} for k, v in sorted(instruments.items())]


def get_categories() -> Dict[str, List[str]]:
    """Get all instrument categories and their instrument IDs.

    Returns:
        Dict mapping category names to lists of instrument IDs.
    """
    return get_registry().get("categories", {})


def clear_cache():
    """Clear caches (for testing)."""
    global _registry_cache, _instruments_cache
    _registry_cache = None
    _instruments_cache = {}
