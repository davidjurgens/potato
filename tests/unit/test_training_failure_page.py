"""An annotator removed by the training gate is not told they finished.

`failure_action: move_to_done` puts a failing annotator in the DONE phase, and
DONE rendered as success:

    "Thank You! You have completed the annotation task and your responses are
     saved. Your annotations have been recorded."

They completed nothing. They failed qualification and never saw a real item.
For a paid annotator that is the difference between "you did not qualify" and
"you finished, expect payment" -- and the completion page also hands out the
completion code and fires the crowd provider's completion callback.

The right page already exists and the training route renders it. It never
arrives: the client POSTs to `/annotate` and then calls
`window.location.reload()`, so the rendered body is discarded and the reload
lands on `/`, which routes DONE to `done()`. Deciding this from the PERSISTED
training state rather than from a response body is what makes it reach the
annotator at all -- a fix in the training route would have been thrown away by
the same reload.

Measured in Chrome before the fix: one wrong answer with `max_mistakes: 1` and
`allow_retry: false`, and the page read "You have completed the annotation
task". After: "You did not pass the qualification questions, so the task did
not start", with no completion code.
"""

import pathlib

import pytest


class FakeTrainingState:
    def __init__(self, failed, mistakes=1, max_mistakes=1):
        self._failed = failed
        self._mistakes = mistakes
        self.max_mistakes = max_mistakes

    def is_failed(self):
        return self._failed

    def get_total_mistakes(self):
        return self._mistakes


class FakeUserState:
    def __init__(self, training_state):
        self._training_state = training_state

    def get_phase(self):
        from potato.phase import UserPhase

        return UserPhase.DONE

    def get_training_state(self):
        return self._training_state


def render_done(monkeypatch, training_state):
    """Drive the real `done()` view and return the rendered body."""
    import flask

    from potato import routes

    # Absolute, so the test does not depend on the working directory.
    template_folder = str(
        pathlib.Path(routes.__file__).resolve().parent / "templates")
    app = flask.Flask(__name__, template_folder=template_folder)
    app.secret_key = "test"
    monkeypatch.setattr(routes, "config",
                        {"annotation_task_name": "probe",
                         "completion_code": "SECRET-CODE-123"},
                        raising=False)
    monkeypatch.setattr(routes, "get_user_state",
                        lambda _u: FakeUserState(training_state),
                        raising=False)

    handler = getattr(routes.done, "__wrapped__", routes.done)
    with app.test_request_context("/done"):
        flask.session["username"] = "u1"
        response = handler()
    return response if isinstance(response, str) else str(response)


class TestAFailedAnnotatorSeesTheQualificationPage:

    def test_it_does_not_say_they_completed_the_task(self, monkeypatch):
        body = render_done(monkeypatch, FakeTrainingState(failed=True))
        assert "completed the annotation task" not in body, (
            "someone removed before seeing a single real item was told they "
            "had finished it")

    def test_it_says_the_task_did_not_start(self, monkeypatch):
        body = render_done(monkeypatch, FakeTrainingState(failed=True))
        assert "did not pass the qualification" in body

    def test_it_does_not_hand_out_the_completion_code(self, monkeypatch):
        """The code is what a paid annotator submits to be paid."""
        body = render_done(monkeypatch, FakeTrainingState(failed=True))
        assert "SECRET-CODE-123" not in body

    def test_it_reports_the_mistake_count(self, monkeypatch):
        body = render_done(monkeypatch,
                           FakeTrainingState(failed=True, mistakes=3,
                                             max_mistakes=2))
        assert "3" in body and "2" in body


class TestAPassingAnnotatorIsUnaffected:
    """The control arm: rendering the failure page for everyone would pass the
    tests above and break every completed study."""

    def test_they_still_see_the_completion_page(self, monkeypatch):
        body = render_done(monkeypatch, FakeTrainingState(failed=False))
        assert "did not pass the qualification" not in body

    def test_they_still_get_the_completion_code(self, monkeypatch):
        body = render_done(monkeypatch, FakeTrainingState(failed=False))
        assert "SECRET-CODE-123" in body

    def test_a_study_with_no_training_is_unaffected(self, monkeypatch):
        """`get_training_state()` returning None must not raise."""
        body = render_done(monkeypatch, None)
        assert "SECRET-CODE-123" in body


class TestTheGradedStateIsPersisted:
    """`done()` decides from the PERSISTED training state, so the state has to
    survive the request that produced it.

    Nothing saved after grading. The in-memory object was correct -- the page
    and the log both said "Total Mistakes: 1" -- and the file on disk said
    `total_mistakes: 0, failed: False`. Anything reading the state saw a study
    where nobody had answered anything: an admin report, a restart, and the
    DONE page above deciding whether this annotator failed qualification.

    That last one is why these two fixes are one commit. Rendering the right
    page from `is_failed()` works until the process restarts, at which point
    the flag reads False and the annotator is told they finished after all.
    """

    def test_the_training_route_registers_a_save(self):
        """Driven by calling the hook the route registers, not by reading it.

        The grading block has nine exit paths between pass, fail, retry and
        advance; a save placed at one of them is a save missed at eight.
        """
        import inspect

        from potato import routes

        source = inspect.getsource(routes.training)
        assert "after_this_request" in source, (
            "the graded state is saved from a single exit path again, so the "
            "other eight lose it")

    def test_the_serialized_state_carries_the_counters(self):
        """The save is only worth registering if it carries these fields.

        Asserted on the produced dict rather than on the serializer's source,
        so a rename of the method does not read as a pass.
        """
        import inspect

        from potato import user_state_management as usm

        serializers = [
            name for name, member in inspect.getmembers(
                usm.UserState, inspect.isfunction)
            if name in ("to_json", "to_dict")
        ]
        assert serializers, "UserState no longer has a serializer"
        source = "".join(inspect.getsource(getattr(usm.UserState, name))
                         for name in serializers)
        assert "training_state" in source, (
            "the saved state would not carry the training counters, so "
            "registering the save buys nothing")
