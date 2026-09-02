"""
Only the image schema's own bootstrap may ASSIGN `onAnnotationChange`.

`ImageAnnotationManager.onAnnotationChange` is a single assignable slot, and
`potato/server_utils/schemas/image_annotation.py` assigns it to drive the
annotation counter. Assignment is destructive: it silently discards whatever was
there before. So a companion schema that chained the slot became
order-dependent — whichever component attached first stopped receiving events,
and the symptom was not an error but annotations that never saved.

That is exactly what happened to `grounding_eval` and `region_caption`, and it
cost a long debugging session because the mechanism worked perfectly when driven
by hand in a browser: the failure only appears when two components want the same
callback, which no single-schema test reproduces.

`addAnnotationChangeListener()` is the fix — several listeners coexist and no
assignment can remove them. This test stops the slot from acquiring a second
assigner, because the obvious thing to write is `manager.onAnnotationChange =
...` (every generated template shows it) and nothing else would catch it.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POTATO = REPO_ROOT / "potato"

#: The one place allowed to assign the slot: the image schema's own bootstrap,
#: which owns the annotation counter it drives. Anything else must subscribe.
ALLOWED_ASSIGNERS = {
    "server_utils/schemas/image_annotation.py":
        "the image schema's own bootstrap — it owns the count display",
}

#: Build output and third-party code. `templates/generated/` is untracked and is
#: rendered FROM image_annotation.py, so it reproduces the allowed assignment
#: once per config and would otherwise swamp the result.
SKIP_DIRS = ("templates/generated/", "static/vendor/", "__pycache__/")

#: `foo.onAnnotationChange =` but not `this.onAnnotationChange =`, which is the
#: slot's own declaration and dispatch inside the manager class. Not `==`.
ASSIGNMENT = re.compile(r"(?<!\bthis)\.onAnnotationChange\s*=(?!=)")


def _source_files():
    for path in POTATO.rglob("*"):
        if path.suffix not in (".js", ".py", ".html"):
            continue
        relative = path.relative_to(POTATO).as_posix()
        if any(skip in relative for skip in SKIP_DIRS):
            continue
        yield path, relative


def _assigners():
    """{relative path: [line numbers]} for every assignment to the slot."""
    found = {}
    for path, relative in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = [n for n, line in enumerate(text.splitlines(), 1)
                 if ASSIGNMENT.search(line)]
        if lines:
            found[relative] = lines
    return found


class TestOnlyOneAssigner:
    def test_no_new_component_assigns_the_slot(self):
        """
        A new `x.onAnnotationChange = ...` fails here.

        Use `manager.addAnnotationChangeListener(fn)` instead. It returns an
        unsubscribe function and cannot be clobbered by another component.
        """
        unexpected = {path: lines for path, lines in _assigners().items()
                      if path not in ALLOWED_ASSIGNERS}
        assert not unexpected, (
            "these assign ImageAnnotationManager.onAnnotationChange, which "
            "silently discards any listener already in the slot:\n"
            + "\n".join(f"  potato/{path}:{lines}"
                        for path, lines in sorted(unexpected.items()))
            + "\n\nUse manager.addAnnotationChangeListener(fn) instead — see "
              "potato/static/grounding-eval.js and region-caption.js.")

    def test_the_allowlist_is_not_stale(self):
        """
        An allowlist entry whose assignment is gone must be removed.

        Without this the list quietly becomes a permanent exemption covering
        code that no longer exists, and the next real assignment there passes.
        """
        found = _assigners()
        stale = sorted(set(ALLOWED_ASSIGNERS) - set(found))
        assert not stale, (
            f"ALLOWED_ASSIGNERS names files that no longer assign the slot: "
            f"{stale}. Delete the entries.")


class TestTheSubscriptionApiExists:
    """
    The guard above is only reasonable if there is somewhere else to go.

    If `addAnnotationChangeListener` were renamed or removed, the assignment
    test would still pass while every companion schema silently broke — so the
    alternative it points people at is pinned here too.
    """

    @pytest.fixture(scope="class")
    def manager_source(self):
        return (POTATO / "static" / "image-annotation.js").read_text(
            encoding="utf-8")

    def test_manager_exposes_the_listener_api(self, manager_source):
        assert "addAnnotationChangeListener(listener)" in manager_source

    def test_dispatch_notifies_listeners_as_well_as_the_slot(self, manager_source):
        """
        Both paths must fire. The slot alone would break the companions; the
        listener list alone would break the count display.
        """
        assert "_annotationChangeListeners" in manager_source
        assert "this.onAnnotationChange(count)" in manager_source

    def test_a_failing_listener_cannot_silence_the_others(self, manager_source):
        """
        Listeners are foreign code. Without a try/except around each call, one
        companion schema throwing would stop every later listener from being
        notified — and the first symptom would be a different schema's
        annotations not saving.
        """
        dispatch = manager_source.split("_annotationChangeListeners")[-3:]
        assert any("try {" in chunk and "catch" in chunk for chunk in dispatch), (
            "each listener call must be individually guarded")

    def test_companion_schemas_use_the_listener_api(self):
        """The two schemas the original bug was found in must not regress."""
        for name in ("grounding-eval.js", "region-caption.js"):
            text = (POTATO / "static" / name).read_text(encoding="utf-8")
            assert "addAnnotationChangeListener(" in text, (
                f"{name} no longer subscribes through the listener API")
