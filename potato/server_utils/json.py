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