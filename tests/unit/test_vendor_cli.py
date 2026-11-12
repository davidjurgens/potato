"""`potato vendor fetch` when there is nothing to fetch (audit 96 L9)."""

from potato import vendoring
from potato.vendoring import cli


def test_fetch_all_with_no_bundles_is_a_no_op(monkeypatch, capsys):
    monkeypatch.setattr(vendoring, "all_bundles", lambda: [])
    assert cli.main(["fetch", "--all"]) == 0
    assert "Nothing to fetch" in capsys.readouterr().out


def test_fetch_for_a_config_that_needs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_required_for_config", lambda path: [])
    assert cli.main(["fetch", "--for-config", "config.yaml"]) == 0
    assert "needs no bundles" in capsys.readouterr().out


def test_fetch_with_no_arguments_still_asks_for_one(capsys):
    assert cli.main(["fetch"]) == 2


# ---------------------------------------------------------------------------
# Pre-release defects: usage text, gitignore, and where the bundle check runs
# ---------------------------------------------------------------------------

import os
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_usage_text_names_only_bundles_that_exist():
    """The module usage once said `potato vendor fetch osweb mol-star`; neither
    is a bundle (the only one is `molstar`)."""
    lines = [ln.strip() for ln in (cli.__doc__ or "").splitlines()
             if ln.strip().startswith("potato vendor fetch ")]
    named = [tok for ln in lines for tok in ln.split()[3:] if not tok.startswith("-")
             and "/" not in tok]
    assert named, "the usage text should show fetching a bundle by name"
    for name in named:
        assert vendoring.get(name) is not None, f"usage names unknown bundle {name!r}"


def test_fetch_help_names_a_registered_bundle(capsys):
    with pytest.raises(SystemExit):
        cli.main(["fetch", "--help"])
    out = capsys.readouterr().out
    assert "molstar" in out and vendoring.get("molstar") is not None


@pytest.mark.skipif(shutil.which("git") is None
                    or not os.path.isdir(os.path.join(REPO, ".git")),
                    reason="needs a git checkout")
def test_default_vendor_dir_is_gitignored(monkeypatch):
    monkeypatch.delenv("POTATO_VENDOR_DIR", raising=False)
    target = vendoring.vendor_dir() / "molstar-5.12.0" / "molstar.js"
    rel = os.path.relpath(str(target), REPO)
    assert not rel.startswith(".."), rel
    result = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=REPO)
    assert result.returncode == 0, f"{rel} is not gitignored"


def test_check_installed_names_the_fetch_command(monkeypatch):
    from potato.server_utils.config_module import ConfigValidationError
    from potato.vendoring.requirements import check_installed
    from tests.helpers.test_utils import create_test_directory
    monkeypatch.setenv("POTATO_VENDOR_DIR", create_test_directory("vendor_cli_empty_dir"))
    needs = {"instance_display": {"fields": [
        {"key": "s", "type": "protein_structure", "engine": "molstar"}]}}
    with pytest.raises(ConfigValidationError, match=r"`potato vendor fetch molstar`"):
        check_installed(needs)
    # A config that needs no bundle is untouched.
    assert check_installed({"instance_display": {"fields": [
        {"key": "s", "type": "protein_structure"}]}}) is None
    assert check_installed({}) is None


def test_no_runtime_adapter_declares_a_bundle():
    """Boot and `potato validate` check bundles only through the viewer
    displays (config_module._validate_viewer_displays); nothing checks
    runtime-adapter bundles. If an adapter starts declaring one, wire
    vendoring.requirements.check_installed (or an equivalent) into config
    validation, then update this test."""
    from potato.runtimes.base import RuntimeAdapter
    from potato.runtimes.registry import get_adapter, runtime_kinds
    for kind in runtime_kinds():
        adapter = get_adapter(kind)
        assert type(adapter).required_bundles is RuntimeAdapter.required_bundles, (
            f"runtime '{kind}' declares bundles that boot never checks")
