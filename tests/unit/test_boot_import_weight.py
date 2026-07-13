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

import pytest

# Modules that must stay OUT of the boot import graph.
# The AI SDKs are optional extras (pip install potato-annotation[ai]) and are
# registered lazily by potato/ai/ai_endpoint.py — importing any of them at
# boot either crashes a core-only install (they may be absent) or, when
# installed, adds real time and RSS (google.genai alone is ~0.6s).
FORBIDDEN_AT_BOOT = [
    "sentence_transformers", "transformers", "torch",
    "ollama", "openai", "anthropic", "google.genai", "huggingface_hub",
]

# Optional packages a core-only `pip install potato-annotation` does NOT have.
OPTIONAL_PACKAGES = [
    "ollama", "openai", "anthropic", "google", "huggingface_hub",
    "umap", "pyarrow", "authlib", "pdfplumber", "docx", "mammoth",
    "mistune", "openpyxl", "langchain_core",
]


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


# Simulates the packaging bug where potato/ai/ai_cache.py imported the ollama
# endpoint at module level: `pip install potato-annotation` (core, no [ai]
# extra) could not even boot the server, because a core schema (likert.py)
# imports potato.ai -> ai_cache -> ollama_endpoint -> `import ollama`.
_MISSING_PACKAGE_PROLOGUE = """
import importlib.abc, sys

BLOCKED = {blocked!r}

class _Blocker(importlib.abc.MetaPathFinder):
    # Raising from find_spec simulates an absent package for plain imports
    # (the common failure mode). Modules probing availability via
    # importlib.util.find_spec (e.g. diversity_manager) are exercised by the
    # dedicated probe test above, not this one.
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError("No module named " + repr(fullname))
        return None

sys.meta_path.insert(0, _Blocker())
for _m in list(sys.modules):
    if _m.split(".")[0] in BLOCKED:
        del sys.modules[_m]
"""


@pytest.mark.parametrize("target", ["potato.flask_server", "potato.routes",
                                    "potato.simulator", "potato.preview_cli"])
def test_boot_imports_survive_missing_optional_packages(target):
    """Core entry points must import cleanly with ALL optional extras absent."""
    blocked = OPTIONAL_PACKAGES
    code = (_MISSING_PACKAGE_PROLOGUE.format(blocked=blocked)
            + f"import {target}; print('BOOT_OK')")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0 and "BOOT_OK" in result.stdout, (
        f"importing {target} with optional packages {blocked} missing failed "
        f"— an optional dependency leaked into the core import graph:\n"
        f"{result.stderr[-3000:]}")


def test_missing_sdk_gives_install_hint_not_unknown_type():
    """With the SDK absent, selecting the endpoint must explain how to fix it."""
    code = _MISSING_PACKAGE_PROLOGUE.format(blocked=["ollama"]) + (
        "from potato.ai.ai_endpoint import AIEndpointFactory, AIEndpointConfigError\n"
        "cfg = {'ai_support': {'enabled': True, 'endpoint_type': 'ollama'}}\n"
        "try:\n"
        "    AIEndpointFactory.create_endpoint(cfg)\n"
        "except AIEndpointConfigError as e:\n"
        "    assert 'pip install ollama' in str(e), str(e)\n"
        "    print('HINT_OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0 and "HINT_OK" in result.stdout, result.stderr
