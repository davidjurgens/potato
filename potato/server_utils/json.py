"""
filename: json.py
date: 10/16/2024
author: Tristan Hilbert (aka TFlexSoom)
desc: Json encoding utilities for the potato tool
"""

import dataclasses
import json
from typing import Any

class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)

def easy_json(obj: Any):
    return json.dumps(obj, cls=EnhancedJSONEncoder)


def script_safe_json(obj: Any) -> str:
    """JSON text that is safe to place inside an inline ``<script>`` element.

    ``json.dumps`` leaves ``<``, ``>`` and ``&`` alone, so a string value that
    holds ``</script>`` closes the element early and the rest of the value is
    parsed as markup. Writing them as ``\\u003c`` / ``\\u003e`` / ``\\u0026``
    keeps the text inert to the HTML parser, and JSON.parse (or the JS engine,
    in an executable script) reads them back as the same characters. U+2028
    and U+2029 are escaped as well: JSON allows them raw, older JS engines
    treat them as line terminators inside a string literal.
    """
    return (easy_json(obj)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))