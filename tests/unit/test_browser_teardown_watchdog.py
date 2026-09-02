"""Neither browser suite may hang forever in fixture teardown.

pytest.ini sets ``timeout_func_only = true``, so pytest-timeout watches only the
test body. Fixture setup and teardown are untimed, and a *session*-scoped
fixture finalizes after the last test, when no per-test alarm is armed at all.
A wedged browser handle there spins at 100% CPU with no output for as long as
you let it — indistinguishable, from the outside, from a slow run. That is
exactly how an hour went missing in the Playwright suite; Selenium's
``driver.quit()`` sits in the same position.

These tests pin the guard that converts that into a stack dump and a nonzero
exit, and prove the guard actually fires rather than merely being present.
"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PW_CONFTEST = REPO_ROOT / "tests" / "playwright" / "conftest.py"
SELENIUM_CONFTEST = REPO_ROOT / "tests" / "selenium" / "conftest.py"
WATCHDOG = REPO_ROOT / "tests" / "helpers" / "teardown_watchdog.py"

#: Every conftest that drives a real browser or a real server, and the fixtures
#: in each whose teardown is known to talk to a subprocess that may be gone.
BROWSER_CONFTESTS = {
    PW_CONFTEST: {"browser_instance", "_default_server"},
    SELENIUM_CONFTEST: {"shared_chrome_browser", "shared_flask_server"},
}


def _statements_after_yield(func_node):
    """The top-level statements a fixture runs after its yield — its teardown."""
    for i, stmt in enumerate(func_node.body):
        is_yield = (isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, (ast.Yield, ast.YieldFrom)))
        if is_yield:
            return func_node.body[i + 1:]
    return []


class TestTheGuardIsWired:
    @pytest.mark.parametrize("conftest", list(BROWSER_CONFTESTS),
                             ids=lambda p: p.parent.name)
    def test_every_fixture_teardown_is_covered(self, conftest):
        """A new fixture must not reintroduce an unbounded teardown.

        Parsed rather than grepped: a line-window search reads the ``scope=``
        of whichever fixture happens to sit above, and called a function-scoped
        fixture session-scoped on that basis.
        """
        tree = ast.parse(conftest.read_text())
        checked = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any("fixture" in ast.dump(d) for d in node.decorator_list):
                continue
            if not any(isinstance(n, ast.Yield) for n in ast.walk(node)):
                continue  # a return-style fixture has no teardown to bound

            # Statements after the yield are the teardown; each must be inside a
            # `with bounded_teardown(...)`.
            teardown = _statements_after_yield(node)
            if not teardown:
                continue  # yields last: nothing to tear down
            checked.append(node.name)
            for stmt in teardown:
                assert isinstance(stmt, ast.With) and "bounded_teardown" in ast.dump(stmt), (
                    f"{conftest.parent.name} fixture {node.name!r} (line {stmt.lineno}) "
                    "tears down outside bounded_teardown; pytest-timeout does not watch "
                    "fixtures, so a hang there runs forever."
                )

        expected = BROWSER_CONFTESTS[conftest]
        assert expected <= set(checked), (
            f"expected {sorted(expected)} to be checked in {conftest.parent.name}, "
            f"got {sorted(checked)} — did a fixture get renamed?"
        )

    def test_both_suites_share_one_implementation(self):
        """Two copies of a watchdog is one copy that drifts."""
        for conftest in BROWSER_CONFTESTS:
            source = conftest.read_text()
            assert "from tests.helpers.teardown_watchdog import" in source, (
                f"{conftest.parent.name}/conftest.py defines or copies its own guard "
                f"instead of importing {WATCHDOG.name}"
            )
            assert "def bounded_teardown" not in source


class TestTheGuardActuallyFires:
    """Wiring proves nothing on its own — run it and watch it kill the process."""

    def test_a_stuck_teardown_dumps_stacks_and_exits_nonzero(self, tmp_path):
        script = tmp_path / "hang.py"
        script.write_text(textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from tests.helpers.teardown_watchdog import bounded_teardown
            with bounded_teardown("pretend_fixture", seconds=1):
                time.sleep(60)          # the wedged close() this stands in for
            print("NEVER REACHED")
        """))

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=45,
        )

        assert result.returncode != 0, "a hung teardown must fail the run, not pass it"
        assert "NEVER REACHED" not in result.stdout
        assert "pretend_fixture" in result.stderr, (
            "the dump must name the teardown that stuck, or it is not diagnosable"
        )
        assert "Timeout (0:00:01)" in result.stderr or "Traceback" in result.stderr, (
            "expected faulthandler's thread stack dump"
        )
        assert "time.sleep" in result.stderr or "hang.py" in result.stderr, (
            "the dump must point at the code that was stuck"
        )

    def test_the_dump_survives_pytest_s_own_output_capture(self, tmp_path):
        """The case that matters, and the one the plain-subprocess test misses.

        pytest's default `--capture=fd` swaps fds 1 and 2 for temp files, and
        faulthandler's `_exit` discards whatever is still buffered there. The
        first version of this guard passed every test above and, run under
        pytest, killed the hang while printing exactly one character: ".".
        A watchdog that ends the run without saying where it stuck only
        converts one useless outcome into another.
        """
        (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""
            import sys, time, pytest
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from tests.helpers.teardown_watchdog import (
                bounded_teardown, use_capture_manager)

            def pytest_configure(config):
                use_capture_manager(config.pluginmanager.getplugin("capturemanager"))

            @pytest.fixture(scope="session")
            def wedged():
                yield "resource"
                with bounded_teardown("wedged_session_fixture", seconds=2):
                    time.sleep(120)
        """))
        (tmp_path / "test_inner.py").write_text(
            "def test_passes(wedged):\n    assert wedged == 'resource'\n")

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=tmp_path, capture_output=True, text=True, timeout=90,
        )
        output = result.stdout + result.stderr

        assert result.returncode != 0, "the hung session must not report success"
        assert "wedged_session_fixture" in output, (
            "the armed-watchdog banner was swallowed by pytest's capture")
        assert "Timeout (0:00:02)" in output, "no faulthandler dump reached the terminal"
        assert "conftest.py" in output and "in wedged" in output, (
            "the dump does not name the fixture that stuck, which is the whole point")

    def test_a_teardown_that_completes_is_not_killed(self, tmp_path):
        script = tmp_path / "ok.py"
        script.write_text(textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from tests.helpers.teardown_watchdog import bounded_teardown
            with bounded_teardown("quick_fixture", seconds=5):
                time.sleep(0.1)
            time.sleep(6)               # outlives the window: the alarm was cancelled
            print("FINISHED")
        """))

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=45,
        )

        assert result.returncode == 0, result.stderr[-2000:]
        assert "FINISHED" in result.stdout, (
            "cancel_dump_traceback_later must disarm the watchdog, or every run "
            "dies 60s after its first session teardown"
        )
