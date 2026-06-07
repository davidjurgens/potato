"""
F-051: guard against eager heavy-ML imports at server boot.

`import potato.flask_server` must NOT pull in sentence_transformers, transformers,
or torch. Those libraries cost ~4s of import time and several hundred MB of RSS,
and they are only needed by opt-in features (diversity ordering, active learning,
embedding similarity). Importing them eagerly slowed boot for EVERY deployment —
including trivial radio-only tasks that never touch an embedding model.

The regression that this guards: `diversity_manager.py` did a module-level
`from sentence_transformers import SentenceTransformer` inside a try/except (the
except only fires when the package is ABSENT), and `flask_server.py` had a dead
`from sklearn.pipeline import Pipeline`. Both are now lazy / removed.

Run in a fresh subprocess so the assertion sees a clean sys.modules (the pytest
process itself may have imported these libraries already).
"""

import subprocess
import sys

# Modules that must stay OUT of the boot import graph.
FORBIDDEN_AT_BOOT = ["sentence_transformers", "transformers", "torch"]


def test_flask_server_import_does_not_load_heavy_ml():
    code = (
        "import sys; import potato.flask_server; "
        "import json; "
        "print(json.dumps([m for m in "
        f"{FORBIDDEN_AT_BOOT!r} if m in sys.modules]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"importing potato.flask_server failed:\n{result.stderr}")
    leaked = result.stdout.strip().splitlines()[-1]
    import json
    loaded = json.loads(leaked)
    assert loaded == [], (
        f"potato.flask_server eagerly imported heavy ML libs at boot: {loaded}. "
        f"These must be lazily imported at point-of-use (see F-051).")


def test_diversity_availability_probe_does_not_load_torch():
    """Importing diversity_manager probes availability via find_spec, not import."""
    code = (
        "import sys; import potato.diversity_manager as d; "
        "import json; "
        "print(json.dumps({'available': bool(d._SENTENCE_TRANSFORMERS_AVAILABLE), "
        "'torch': 'torch' in sys.modules}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    import json
    info = json.loads(result.stdout.strip().splitlines()[-1])
    # torch must NOT be loaded merely by importing the module / probing availability
    assert info["torch"] is False, (
        "importing potato.diversity_manager eagerly loaded torch (F-051)")
