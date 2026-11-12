"""LexTALE-style vocabulary tests: a radio scheme with a ``lextale`` block.

The block names the item field holding the word/nonword key; the key is kept
off the page (see ``private_item_fields``) and scored by the ``lextale``
export (potato/export/lextale_exporter.py).
"""

from typing import List


def private_item_fields(config: dict) -> List[str]:
    """Item fields holding a vocabulary test's answer key."""
    out = []
    for scheme in (config or {}).get("annotation_schemes") or []:
        block = scheme.get("lextale") if isinstance(scheme, dict) else None
        if isinstance(block, dict) and block.get("answer_field"):
            out.append(str(block["answer_field"]))
    return out
