"""`potato --version` answers, in every way anyone runs Potato.

It used to exit 2 with an argparse usage block, because `mode` and
`config_file` are both required positionals. That reads as a broken install
rather than a missing flag, and it made `potato --version || pip install
potato-annotation` always take the install branch, dropping a released wheel on
top of an editable checkout.

These drive the CLI as a subprocess. The whole point of the change is what
happens before `arguments()` runs, and a test that imported `main` and called
it would be testing something else.
"""

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SERVER = os.path.join(REPO_ROOT, "potato", "flask_server.py")


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, SERVER, *args],
        capture_output=True, text=True, timeout=120,
        cwd=cwd or REPO_ROOT)


class TestTheFlagAnswers:
    @pytest.mark.parametrize("flag", ["--version", "-V", "version"])
    def test_it_exits_zero_and_names_potato(self, flag):
        result = run_cli(flag)
        assert result.returncode == 0, (
            f"`potato {flag}` exited {result.returncode}. "
            f"stderr: {result.stderr[-800:]}")
        assert result.stdout.startswith("potato "), result.stdout[:200]

    def test_it_does_not_demand_a_config_file(self):
        # The failure this replaced: argparse refusing before anything ran.
        result = run_cli("--version")
        assert "usage:" not in result.stderr
        assert "config_file" not in result.stderr

    def test_it_reports_a_real_version_not_a_placeholder(self):
        from potato.version_info import UNKNOWN_VERSION

        version = run_cli("--version").stdout.split()[1]
        assert version != UNKNOWN_VERSION
        # A version is dotted digits, not a word. Asserting the shape rather
        # than the value so a release does not break this.
        assert version[0].isdigit() and "." in version, version

    def test_it_names_the_commit_when_run_from_a_checkout(self):
        # The number alone cannot identify a build: one release covers hundreds
        # of commits, and the people who most need to report a version are
        # somewhere between two of them.
        from potato.version_info import commit_info

        info = commit_info()
        if info is None:
            pytest.skip("not running from a git checkout")
        assert info["commit"] in run_cli("--version").stdout


class TestSourceVersionInBothInvocationModes:
    """`python potato/flask_server.py` puts `potato/` itself on sys.path, so
    `potato` resolves to a namespace package with no `__init__.py` and
    `from potato import __version__` raises. That is the documented way to run
    from source, so it has to work -- which means every subprocess test in this
    file is exercising the file-reading fallback, not the import.
    """

    def test_the_import_route_really_does_fail_in_that_mode(self):
        # If this ever stops being true the fallback stops being covered by the
        # tests above, and they would keep passing while testing the easy path.
        probe = subprocess.run(
            [sys.executable, "-c",
             "from potato import __version__; print(__version__)"],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.join(REPO_ROOT, "potato"))
        assert probe.returncode != 0, (
            "`from potato import __version__` now succeeds with potato/ on "
            "sys.path, so the subprocess tests here no longer reach the file "
            "fallback in source_version(). Cover it directly.")

    def test_the_module_run_reports_the_same_version_as_the_import(self):
        from potato.version_info import source_version

        assert run_cli("--version").stdout.split()[1] == source_version()

    def test_the_two_routes_agree(self):
        """Only one route runs at a time, so nothing else would notice them
        diverging. A computed `__version__`, or a quoting change the regex
        stops matching, would silently turn the file route into `unknown` on
        exactly the machines where it is the only route that runs -- and there
        is at least one such machine: a leftover `site-packages/potato/` with
        no `__init__.py` makes `potato` a namespace package from every
        directory outside the checkout, so `potato.__version__` does not exist
        while `potato.version_info` imports fine.
        """
        import potato
        from potato.version_info import UNKNOWN_VERSION, version_from_init_file

        imported = getattr(potato, "__version__", None)
        if imported is None:
            pytest.skip("the import route is unavailable here; nothing to compare")

        from_file = version_from_init_file()
        assert from_file != UNKNOWN_VERSION, (
            "source_version() could not read __version__ out of "
            "potato/__init__.py. That is the only route on a machine where "
            "`potato` resolves as a namespace package.")
        assert from_file == imported


class TestItSaysWhichPotatoIsRunning:
    def test_disagreeing_metadata_is_named_rather_than_hidden(self, monkeypatch):
        # An editable checkout that has moved on since `pip install -e .`
        # reports the older number forever. Printing only one of the two would
        # make a bug report name a build nobody is running.
        import potato.version_info as vi

        monkeypatch.setattr(vi, "installed_distributions",
                            lambda: [{"version": "0.0.1", "location": "/somewhere"}])
        report = vi.version_report()
        assert "0.0.1" in report
        assert vi.source_version() in report
        assert "does not match" in report

    @pytest.mark.parametrize("metadata_version", ["0.0.1", "999.0.0"])
    def test_it_does_not_claim_which_side_is_stale(self, monkeypatch,
                                                   metadata_version):
        """The metadata is usually the one left behind, but checking out an
        older commit leaves it AHEAD, and the report cannot tell the
        difference. Naming the wrong side sends someone to reinstall when they
        should be checking out."""
        import potato.version_info as vi

        monkeypatch.setattr(
            vi, "installed_distributions",
            lambda: [{"version": metadata_version, "location": "/somewhere"}])
        report = vi.version_report()
        assert "stale" not in report
        # It still has to say which number is the one running.
        assert "The source above is what is running" in report

    def test_two_visible_copies_are_both_listed(self, monkeypatch):
        # A checkout in front of a released wheel: the answer to "what version
        # is this" then depends on the directory you asked from.
        import potato.version_info as vi

        monkeypatch.setattr(vi, "installed_distributions", lambda: [
            {"version": "9.9.9", "location": "/checkout"},
            {"version": "0.0.1", "location": "/site-packages"},
        ])
        report = vi.version_report()
        assert "/checkout" in report and "/site-packages" in report
        assert "9.9.9" in report and "0.0.1" in report

    def test_a_shadowing_namespace_directory_is_named(self, monkeypatch):
        """The state that makes `potato.__version__` vanish while every
        submodule still imports. Silent, machine-specific, and the exact thing
        someone runs --version to find out about."""
        import potato.version_info as vi

        monkeypatch.setattr(vi, "installed_distributions", lambda: [])
        monkeypatch.setattr(vi, "shadowing_namespace_dirs",
                            lambda: ["/site-packages/potato"])
        report = vi.version_report()
        assert "/site-packages/potato" in report
        assert "namespace package" in report

    def test_a_normal_install_says_nothing_about_namespaces(self, monkeypatch):
        # A line that appears on every install teaches nobody anything.
        import potato.version_info as vi

        monkeypatch.setattr(vi, "installed_distributions", lambda: [])
        monkeypatch.setattr(vi, "shadowing_namespace_dirs", lambda: [])
        assert "namespace package" not in vi.version_report()

    def test_the_detector_ignores_a_real_package(self, tmp_path):
        """A regular package's `__path__` always contains its own
        `__init__.py`, so calling the real thing cannot distinguish a working
        `__file__` check from a missing one -- a mutation removing it survived.
        Both arms are driven here instead.
        """
        from potato.version_info import namespace_shadows

        real = tmp_path / "potato"
        real.mkdir()
        (real / "__init__.py").write_text("__version__ = '1.2.3'\n")
        leftover = tmp_path / "leftover" / "potato"
        leftover.mkdir(parents=True)

        # A real package: `__file__` is set, and there is nothing to report
        # even when a bare directory is also on the search path.
        assert namespace_shadows(str(real / "__init__.py"),
                                 [str(real), str(leftover)]) == []
        # A namespace package: `__file__` is None, and only the directory
        # WITHOUT an __init__.py is at fault.
        assert namespace_shadows(None, [str(real), str(leftover)]) == \
            [str(leftover)]

    def test_a_source_only_tree_says_so(self, monkeypatch):
        import potato.version_info as vi

        monkeypatch.setattr(vi, "installed_distributions", lambda: [])
        assert "not installed as a distribution" in vi.version_report()

    def test_could_not_look_never_prints_as_looked_and_found_nothing(
            self, monkeypatch):
        """The two must not produce the same sentence.

        "potato-annotation is not installed as a distribution; this is running
        from the source tree" is a definite claim, and it is the sentence that
        tells a reader to stop investigating the install. A metadata scan that
        threw used to produce it, because the scan returned [] for both
        outcomes. The fix is the general one: the instrument returns its status
        separately from its result.
        """
        import potato.version_info as vi

        def explode():
            raise OSError("metadata directory is unreadable")

        monkeypatch.setattr(vi, "installed_distributions", explode)
        failed = vi.version_report()

        monkeypatch.setattr(vi, "installed_distributions", lambda: [])
        empty = vi.version_report()

        assert "not installed as a distribution" in empty
        assert "not installed as a distribution" not in failed
        assert "metadata directory is unreadable" in failed

    def test_the_scan_itself_propagates_rather_than_returning_empty(
            self, monkeypatch):
        """The other half of the claim above.

        The test before it monkeypatches `installed_distributions` wholesale,
        so it pins `version_report`'s handling and nothing about the scan. A
        mutation putting the swallow back inside the scan passed it. This
        drives the real function against a metadata read that fails.
        """
        import importlib.metadata

        import potato.version_info as vi

        def explode():
            raise OSError("metadata directory is unreadable")

        monkeypatch.setattr(importlib.metadata, "distributions", explode)
        with pytest.raises(OSError):
            vi.installed_distributions()

    def test_one_unreadable_sibling_does_not_abandon_the_scan(self, monkeypatch):
        """A distribution that is not Potato failing to describe itself says
        nothing about whether Potato is installed, so that one is skipped
        rather than ending the scan and reporting nothing found."""
        import importlib.metadata

        import potato.version_info as vi

        class Broken:
            version = "0"

            @property
            def metadata(self):
                raise ValueError("unreadable")

        class Ours:
            version = "9.9.9"
            metadata = {"Name": "potato-annotation"}
            _path = "/somewhere"

        monkeypatch.setattr(importlib.metadata, "distributions",
                            lambda: iter([Broken(), Ours()]))
        found = vi.installed_distributions()
        assert [d["version"] for d in found] == ["9.9.9"]

    def test_git_declining_to_answer_is_not_a_clean_tree(self, monkeypatch):
        """`_git` returned None for both "command failed" and "said nothing",
        and a clean tree is exactly what `git status --porcelain` says nothing
        about. So a missing or broken git reported "no uncommitted changes"
        having never looked."""
        import potato.version_info as vi

        monkeypatch.setattr(vi, "repo_root", lambda: "/checkout")

        def git(root, *args):
            if args[0] == "status":
                return None          # git declined
            if args[0] == "rev-parse" and args[1] == "--short":
                return "abc1234"
            return "master"

        monkeypatch.setattr(vi, "_git", git)
        info = vi.commit_info()
        assert info["dirty"] is None, "unreadable status must not read as clean"

        def git_clean(root, *args):
            if args[0] == "status":
                return ""            # git answered: nothing to report
            if args[0] == "rev-parse" and args[1] == "--short":
                return "abc1234"
            return "master"

        monkeypatch.setattr(vi, "_git", git_clean)
        assert vi.commit_info()["dirty"] is False

    def test_a_checkout_whose_git_is_broken_says_so(self, monkeypatch):
        # Silence would read exactly like an ordinary installed copy, which is
        # the opposite conclusion about what someone is running.
        import potato.version_info as vi

        monkeypatch.setattr(vi, "repo_root", lambda: "/checkout")
        monkeypatch.setattr(vi, "_git", lambda root, *args: None)
        monkeypatch.setattr(vi, "installed_distributions", lambda: [])

        info = vi.commit_info()
        assert info is not None, "None means 'not a checkout'; this IS one"
        assert info["error"]
        assert "in a checkout" in vi.version_report()

    def test_no_pep610_record_is_not_the_same_as_not_editable(self, monkeypatch):
        # An install from an index has no record, and so does an unreadable
        # one. False would claim the install was checked.
        import potato.version_info as vi

        monkeypatch.setattr(vi, "_direct_url", lambda: None)
        assert vi.is_editable() is None

        monkeypatch.setattr(vi, "_direct_url", lambda: {"dir_info": {}})
        assert vi.is_editable() is False

        monkeypatch.setattr(vi, "_direct_url",
                            lambda: {"dir_info": {"editable": True}})
        assert vi.is_editable() is True

    def test_broken_metadata_does_not_take_the_flag_down(self, monkeypatch):
        # --version is what someone runs when the install is already suspect,
        # so the metadata read must not be the thing that crashes it.
        import potato.version_info as vi

        def explode():
            raise RuntimeError("metadata is unreadable")

        monkeypatch.setattr(vi, "installed_distributions", explode)
        report = vi.version_report()
        assert vi.source_version() in report
        assert "metadata is unreadable" in report
