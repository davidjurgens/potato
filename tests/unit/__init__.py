"""Unit test package.

This marker matters: without it, pytest imports `tests/unit/test_solo_mode/` as a
top-level package named `test_solo_mode`, which collides with the identically named
package under `tests/server/`. Collecting both directories in one run then fails with
"No module named 'test_solo_mode....'". With both parents marked as packages the
modules resolve as tests.unit.test_solo_mode and tests.server.test_solo_mode.
"""
