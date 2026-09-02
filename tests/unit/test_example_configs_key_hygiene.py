"""Every shipped example config must use keys the server actually reads.

`validate_unknown_keys` only *warns* about an unrecognized key, so a config can
name a key nothing consumes and still start a server. That makes the failure
invisible in exactly the place it does the most damage — the examples, which are
what people copy. Four such keys shipped before this guard existed:

  * `server_name`, written into every generated project by the importer CLI and
    read by nothing.
  * `html_layout`, in two examples; the key the server reads is `task_layout`,
    and it takes a file path rather than a name.
  * `auto_redirect_delay` / `auto_redirect_on_completion`, allowlisted under
    `login` but read at top level, so the allowlist pointed at a placement where
    they silently do nothing.
  * `codebook.distiller`, the reverse case — a key the code honors that the
    allowlist did not know, so a correct config got told it would be ignored.

A warning nobody sees is not a guard, so this turns the warning into a failure.
"""

import glob
import logging
import os
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from potato.server_utils.config_module import validate_yaml_structure

REPO_ROOT = Path(__file__).resolve().parents[2]


def _example_configs():
    return sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "config.yaml"), recursive=True))


class _WarningCollector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_examples_exist():
    """A silent zero-config sweep would make every test below vacuous."""
    assert len(_example_configs()) > 100, (
        "Expected the repo's example configs to be discoverable; found "
        f"{len(_example_configs())}. Did the examples/ layout change?"
    )


def test_no_example_config_uses_an_unrecognized_key():
    logger = logging.getLogger("potato.server_utils.config_module")
    handler = _WarningCollector()
    logger.addHandler(handler)
    offenders = []
    try:
        for path in _example_configs():
            with open(path, encoding="utf-8") as handle:
                config = yaml.safe_load(handle)
            if not isinstance(config, dict):
                continue
            handler.messages.clear()
            directory = os.path.dirname(os.path.abspath(path))
            try:
                validate_yaml_structure(
                    config, project_dir=directory, config_file_dir=directory
                )
            except Exception:
                # Validation errors are a different guard's business; this one
                # is only about key hygiene.
                pass
            for message in handler.messages:
                if "Unrecognized config key" in message:
                    offenders.append(
                        f"{os.path.relpath(path, REPO_ROOT)}: {message}"
                    )
    finally:
        logger.removeHandler(handler)

    assert not offenders, (
        "Example configs name keys the server does not recognize:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither the key is dead and belongs out of the example, or it is "
        "real and belongs in KNOWN_CONFIG_KEYS — at the nesting level the code "
        "actually reads it from."
    )


def test_every_example_config_validates():
    failures = []
    for path in _example_configs():
        with open(path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        if not isinstance(config, dict):
            continue
        directory = os.path.dirname(os.path.abspath(path))
        try:
            validate_yaml_structure(
                config, project_dir=directory, config_file_dir=directory
            )
        except Exception as exc:
            failures.append(f"{os.path.relpath(path, REPO_ROOT)}: {type(exc).__name__}: {exc}")
    assert not failures, "Example configs fail server validation:\n  " + "\n  ".join(failures)


class TestKnownKeyPlacement:
    """Keys must be allowlisted where the code reads them."""

    def test_auto_redirect_keys_are_top_level(self):
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        for key in ("auto_redirect_on_completion", "auto_redirect_delay"):
            assert key in KNOWN_CONFIG_KEYS, (
                f"{key} is read at top level by routes.py and the crowd "
                "providers, so it must be allowlisted at top level."
            )
            assert key not in KNOWN_CONFIG_KEYS.get("login", set()), (
                f"{key} is allowlisted under `login`, but nothing reads it "
                "there — that placement validates clean and then does nothing."
            )

    def test_codebook_distiller_is_allowlisted(self):
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        codebook = KNOWN_CONFIG_KEYS.get("codebook")
        assert isinstance(codebook, dict) and "distiller" in codebook, (
            "codebook.distiller is read by DistillerConfig.from_config, so a "
            "config that sets it must not be warned that it will be ignored."
        )

    def test_importer_generates_only_recognized_keys(self):
        """A generated project should not start life with a dead key in it."""
        from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

        import inspect

        from potato.importers import cli

        source = inspect.getsource(cli._build_config)
        assert '"server_name"' not in source, (
            "The importer writes `server_name` into every generated config, but "
            "nothing reads it — every imported project then warns on startup."
        )
