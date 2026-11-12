"""
Who is admitted, qualified, blocked or graded, driven through the real routes.

The earlier tests checked the managers' return values. These check what the
routes do with them: whether a block stops work, whether a training answer
order changes the outcome, whether a declined consent is honoured, and
whether a consent page can become gold.
"""

import json
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_config, create_test_data_file, create_test_directory

SENTIMENT = {"annotation_type": "radio", "name": "sentiment", "description": "S?",
             "labels": ["positive", "negative"]}


def _login(srv, user):
    s = requests.Session()
    s.post(f"{srv.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{srv.base_url}/auth", data={"email": user, "pass": "pw"})
    return s


def _state(user):
    from potato.user_state_management import get_user_state_manager
    return get_user_state_manager().get_user_state(user)


@pytest.fixture
def server():
    started = []

    def start(config_file):
        srv = FlaskTestServer(port=9830 + len(started), config_file=config_file)
        assert srv.start()
        started.append(srv)
        return srv
    yield start
    for srv in started:
        srv.stop()


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

QUESTIONS = [
    {"id": "t1", "text": "Q one", "correct_answers": {"sentiment": "positive"}, "explanation": "E1"},
    {"id": "t2", "text": "Q two", "correct_answers": {"sentiment": "negative"}, "explanation": "E2"},
    {"id": "t3", "text": "Q three", "correct_answers": {"sentiment": "positive"}, "explanation": "E3"},
]


def _training_config(name, training, extra=None, questions=QUESTIONS, schemes=(SENTIMENT,)):
    d = create_test_directory(name)
    create_test_data_file(d, [{"id": f"item_{i}", "text": f"Item {i}"} for i in range(1, 4)])
    with open(os.path.join(d, "training_data.json"), "w") as f:
        json.dump({"training_instances": questions}, f)
    block = {"enabled": True, "data_file": "training_data.json", **training}
    return create_test_config(d, list(schemes), data_files=["test_data.jsonl"],
                              annotation_task_name=name,
                              phases={"order": ["training", "annotation"],
                                      "training": {"type": "training"}},
                              additional_config={"training": block, **(extra or {})})


def _answer(s, srv, label):
    s.post(f"{srv.base_url}/updateinstance", json={
        "instance_id": "__phase_page__", "annotations": {f"sentiment:::{label}": label}})
    s.post(f"{srv.base_url}/annotate", json={"action": "next_instance",
                                             "instance_id": "__phase_page__"})


class TestTrainingGrading:
    @pytest.mark.parametrize("answers", [
        ("negative", "negative", "positive"),   # wrong, right, right
        ("positive", "negative", "negative"),   # right, right, wrong
    ])
    def test_two_of_three_is_below_min_correct_in_either_order(self, server, answers):
        srv = server(_training_config("tg2_minc", {
            "passing_criteria": {"min_correct": 3}, "allow_retry": False,
            "failure_action": "repeat_training"}))
        s = _login(srv, "trainee")
        for label in answers:
            _answer(s, srv, label)
        training = _state("trainee").get_training_state()
        assert not training.passed
        assert _state("trainee").get_phase().name == "TRAINING"

    def test_require_all_correct_asks_every_question(self, server):
        srv = server(_training_config("tg2_reqall", {
            "passing_criteria": {"min_correct": 2, "require_all_correct": True},
            "allow_retry": False, "failure_action": "move_to_done"}))
        s = _login(srv, "trainee")
        _answer(s, srv, "positive")
        _answer(s, srv, "negative")
        training = _state("trainee").get_training_state()
        assert not training.passed
        assert training.current_question_index == 2

    def test_a_retried_question_counts_once_for_qualification(self, server):
        questions = [
            {"id": "t1", "text": "Q one", "correct_answers": {"sentiment": "positive"},
             "categories": ["sports"]},
            {"id": "t2", "text": "Q two", "correct_answers": {"sentiment": "negative"},
             "categories": ["news"]},
        ]
        srv = server(_training_config(
            "tg2_cat", {"passing_criteria": {"min_correct": 2}, "allow_retry": True},
            extra={"category_assignment": {"enabled": True, "qualification": {
                "threshold": 0.5, "min_questions": 2}}}, questions=questions))
        s = _login(srv, "trainee")
        _answer(s, srv, "negative")   # t1 wrong
        _answer(s, srv, "positive")   # t1 right on retry
        _answer(s, srv, "negative")   # t2 right
        state = _state("trainee")
        assert state.get_training_state().category_scores["sports"] == {"correct": 0, "total": 1}
        assert "sports" not in (state.qualified_categories or set())

    def test_feedback_allow_retry_false_is_honoured(self, server):
        srv = server(_training_config("tg2_fb", {
            "passing_criteria": {"min_correct": 3}, "feedback": {"allow_retry": False},
            "failure_action": "move_to_done"}))
        s = _login(srv, "trainee")
        _answer(s, srv, "negative")   # wrong on t1, no retry: the training ends
        assert _state("trainee").get_training_state().failed

    def test_max_attempts_limits_retakes(self, server):
        srv = server(_training_config("tg2_attempts", {
            "passing_criteria": {"min_correct": 3, "max_attempts": 2}, "allow_retry": False,
            "failure_action": "repeat_training"}))
        s = _login(srv, "trainee")
        for _ in range(2):
            for label in ("negative", "negative", "negative"):
                _answer(s, srv, label)
        assert _state("trainee").get_training_state().failed

    def test_training_shows_only_the_named_schemes(self, server):
        topics = {"annotation_type": "multiselect", "name": "topics", "description": "T?",
                  "labels": ["a", "b"]}
        srv = server(_training_config("tg2_schemes", {"annotation_schemes": ["sentiment"]},
                                      schemes=(SENTIMENT, topics)))
        page = _login(srv, "trainee").get(f"{srv.base_url}/").text
        assert 'data-schema-name="sentiment"' in page
        assert 'data-schema-name="topics"' not in page


# ---------------------------------------------------------------------------
# Attention checks
# ---------------------------------------------------------------------------

def _attention_config(name, items=10, block_threshold=2):
    d = create_test_directory(name)
    create_test_data_file(d, [{"id": f"item_{i}", "text": f"Item {i}"} for i in range(1, items + 1)])
    with open(os.path.join(d, "attn.json"), "w") as f:
        json.dump([{"id": f"attn_{k}", "text": "Select positive",
                    "expected_answer": {"sentiment": "positive"}} for k in range(1, 4)], f)
    return create_test_config(d, [SENTIMENT], data_files=["test_data.jsonl"],
                              annotation_task_name=name,
                              additional_config={
                                  "max_annotations_per_user": 4,
                                  "assignment_strategy": "fixed_order",
                                  "attention_checks": {
                                      "enabled": True, "items_file": "attn.json", "frequency": 1,
                                      "failure_handling": {"warn_threshold": 1,
                                                           "block_threshold": block_threshold}}})


class TestAttentionCheckBlock:
    def _get_blocked(self, srv, user):
        from potato.quality_control import get_quality_control_manager
        qc = get_quality_control_manager()
        s = _login(srv, user)
        s.get(f"{srv.base_url}/annotate")
        state = _state(user)
        for _ in range(10):
            cur = state.get_current_instance().get_id()
            label = "negative" if qc.is_attention_check(cur) else "positive"
            r = s.post(f"{srv.base_url}/updateinstance", json={
                "instance_id": cur, "annotations": {f"sentiment:::{label}": label}})
            if r.json().get("status") == "blocked":
                return s, state, qc
            s.post(f"{srv.base_url}/annotate", json={"action": "next_instance", "instance_id": cur})
            s.get(f"{srv.base_url}/annotate")
        pytest.fail("never blocked")

    def test_a_blocked_user_gets_no_more_work_and_no_more_saves(self, server):
        srv = server(_attention_config("tg2_block"))
        s, state, qc = self._get_blocked(srv, "blocked_user")
        r = s.get(f"{srv.base_url}/annotate", allow_redirects=False)
        assert r.status_code == 302 and r.headers["Location"].endswith("/done")
        assert state.get_phase().name == "DONE"
        r = s.post(f"{srv.base_url}/updateinstance", json={
            "instance_id": "item_9", "annotations": {"sentiment:::negative": "negative"}})
        assert r.status_code == 403
        assert not state.get_label_annotations("item_9")

    def test_re_answering_a_failed_check_does_not_lift_the_block(self, server):
        srv = server(_attention_config("tg2_unblock"))
        s, state, qc = self._get_blocked(srv, "unblock_user")
        for check in [i for i in qc.attention_expected if i in state.get_assigned_instance_ids()]:
            qc.validate_attention_response("unblock_user", check, {"sentiment": "positive"})
        assert qc.is_user_blocked("unblock_user")

    def test_moving_past_a_check_without_answering_fails_it(self, server):
        srv = server(_attention_config("tg2_skip", block_threshold=5))
        from potato.quality_control import get_quality_control_manager
        qc = get_quality_control_manager()
        s = _login(srv, "skipper")
        s.get(f"{srv.base_url}/annotate")
        state = _state("skipper")
        for _ in range(8):
            if state.get_phase().name != "ANNOTATION":
                break
            cur = state.get_current_instance().get_id()
            if not qc.is_attention_check(cur):
                s.post(f"{srv.base_url}/updateinstance", json={
                    "instance_id": cur, "annotations": {"sentiment:::positive": "positive"}})
            s.post(f"{srv.base_url}/annotate", json={"action": "next_instance", "instance_id": cur})
            s.get(f"{srv.base_url}/annotate")
        stats = qc.get_attention_check_stats("skipper")
        assert stats["total"] >= 1 and stats["failed"] == stats["total"]


# ---------------------------------------------------------------------------
# Consent and phase pages
# ---------------------------------------------------------------------------

class TestConsentAndPhasePages:
    @pytest.fixture
    def consent_server(self, server):
        d = create_test_directory("tg2_consent")
        create_test_data_file(d, [{"id": f"item_{i}", "text": f"Item {i}"} for i in range(1, 6)])
        with open(os.path.join(d, "consent.json"), "w") as f:
            json.dump([{"id": "1", "name": "age_consent", "description": "18+?",
                        "annotation_type": "radio", "labels": ["I agree", "I disagree"],
                        "label_requirement": {"required_label": ["I agree"]}}], f)
        with open(os.path.join(d, "gold.json"), "w") as f:
            json.dump([{"id": "item_5", "text": "Item 5", "gold_label": {"sentiment": "positive"}}], f)
        cfg = create_test_config(
            d, [SENTIMENT], data_files=["test_data.jsonl"], annotation_task_name="tg2 consent",
            phases={"order": ["consent", "annotation"],
                    "consent": {"type": "consent", "file": "consent.json"}},
            additional_config={"gold_standards": {
                "enabled": True, "items_file": "gold.json", "mode": "mixed", "frequency": 100,
                "auto_promote": {"enabled": True, "min_annotators": 2, "agreement_threshold": 1.0}}})
        return server(cfg)

    def _consent(self, srv, user, answer):
        s = _login(srv, user)
        s.get(f"{srv.base_url}/")
        s.post(f"{srv.base_url}/updateinstance", json={
            "instance_id": "__phase_page__", "annotations": {f"age_consent:::{answer}": answer}})
        return s.post(f"{srv.base_url}/consent", data={})

    def test_declining_consent_keeps_the_participant_on_the_consent_page(self, consent_server):
        r = self._consent(consent_server, "decliner", "I disagree")
        assert r.status_code == 400
        assert _state("decliner").get_phase().name == "CONSENT"

    def test_agreeing_still_moves_on(self, consent_server):
        self._consent(consent_server, "agreer", "I agree")
        assert _state("agreer").get_phase().name != "CONSENT"

    def test_consent_answers_are_never_promoted_to_gold(self, consent_server):
        from potato.quality_control import get_quality_control_manager
        for user in ("p2", "p3", "p4"):
            self._consent(consent_server, user, "I agree")
        qc = get_quality_control_manager()
        assert not qc.is_gold_standard("__phase_page__")
        assert "__phase_page__" not in qc.item_annotations
