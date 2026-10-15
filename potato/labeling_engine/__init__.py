"""
The labeling engine: machines label, humans calibrate and certify.

Every machine output (an LLM, a vision model, a decision model, a trained
classifier, a labeling function, a jury) is a prediction tied to the exact
version of the source that produced it. Human labels the engine relies on come
from requests in a ledger that records why each was asked for and how likely
the item was to be chosen, which is what makes the accuracy estimates and the
guarantees on accepted labels valid. See ``plans/llm-labeling-engine-v2.md``.

This package must stay light at import time: no model endpoints, SDKs or torch.
Sources import their backends when a run builds them, and
``tests/unit/test_boot_import_weight.py`` checks that.
"""
