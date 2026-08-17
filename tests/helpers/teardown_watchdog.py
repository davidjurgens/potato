"""Bound fixture teardown so a wedged browser or server cannot hang the suite.

`pytest.ini` sets ``timeout_func_only = true``, so pytest-timeout watches the
test body and nothing else. Fixture setup and teardown are untimed, and a
*session*-scoped fixture finalizes after the last test, when no per-test alarm
is armed at all. A browser handle that will not close there spins at 100% CPU
with no output for as long as you let it — which reads as "still running", not
"broken". One such hang cost an hour before anyone looked.

Both browser suites are exposed: Playwright's ``browser.close()``/``pw.stop()``
and Selenium's ``driver.quit()`` each talk to a subprocess that may already be
gone.

A watchdog *thread* cannot substitute for this. Playwright's sync API is
greenlet-bound to the thread that created it, so calling ``close()`` from
anywhere else raises instead of unblocking, and Selenium's ``quit()`` blocks on
a socket read that another thread cannot interrupt either. faulthandler's
C-level timer is the only thing here that can end it.

Note that faulthandler keeps a single global timer, so these guards must not be
nested — in practice they never are, because per-test teardown always completes
before session teardown begins.
"""

import contextlib
import faulthandler
import sys

#: pytest's default `--capture=fd` swaps file descriptors 1 and 2 for temp
#: files, so a dump written during teardown lands in a buffer that is discarded
#: when faulthandler kills the process — the run ends, correctly, with no
#: diagnosis at all. Verified: a hanging session fixture produced exactly one
#: character of output ("."). Capture is suspended while the guard is armed.
_capture_manager = None


def use_capture_manager(manager):
    """Register pytest's capture manager. Call from `pytest_configure`."""
    global _capture_manager
    _capture_manager = manager


@contextlib.contextmanager
def _capture_suspended():
    manager = _capture_manager
    if manager is None:
        yield
        return
    try:
        manager.suspend_global_capture(in_=False)
    except Exception:       # pragma: no cover - pytest internals moved
        yield
        return
    try:
        yield
    finally:
        try:
            manager.resume_global_capture()
        except Exception:   # pragma: no cover
            pass

#: Session fixtures: generous, because a legitimate multi-server shutdown is slow.
SESSION_TEARDOWN_TIMEOUT_SECONDS = 60

#: Per-test fixtures: tighter, and silent — one banner per test is noise.
TEST_TEARDOWN_TIMEOUT_SECONDS = 30


@contextlib.contextmanager
def bounded_teardown(label, seconds=SESSION_TEARDOWN_TIMEOUT_SECONDS, announce=True):
    """Turn an unbounded teardown hang into a loud, diagnosable failure.

    ``faulthandler.dump_traceback_later(exit=True)`` dumps every thread's stack
    and then kills the process, which is the right trade for a test harness: a
    non-terminating run tells you nothing, a stack dump tells you where it stuck.
    """
    with _capture_suspended():
        if announce:
            # Names the teardown, so the dump that follows is attributable.
            print(f"[teardown watchdog armed: {label}, {seconds}s]",
                  file=sys.__stderr__, flush=True)
        faulthandler.dump_traceback_later(seconds, exit=True)
        try:
            yield
        finally:
            faulthandler.cancel_dump_traceback_later()
