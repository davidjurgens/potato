"""
Allow running the annotation importers as a module:
    python -m potato.importers --input instances.json --output-dir project/
"""

import sys
from .cli import main

sys.exit(main())
