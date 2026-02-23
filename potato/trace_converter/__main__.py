"""
Allow running trace converter as a module:
    python -m potato.trace_converter --input traces.json --input-format react --output data.jsonl
"""

import sys
from .cli import main

sys.exit(main())
