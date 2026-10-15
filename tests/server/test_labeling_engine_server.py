"""
The labeling engine in a running server, with a fixture source.

The planner registers the study's items, has the cascade label them and draws
a blind calibration sample. The `engine` assignment strategy serves those
requests; the AI suggestion routes refuse on blind items; an annotation save
closes the request it answers. Then certification and resolution run on the
labels collected through the real routes.
"""

import random

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory)

LABELS = ["positive", "negative"]
N = 40
ADMIN_KEY = "engine-test-admin-key"


@pytest.fixture(scope="module")
def engine_server():
    test_dir = create_test_directory("labeling_engine_server")
    rng = random.Random(0)
    data = [{"id": f"item_{k}", "text": f"review {k}",
             "gold": rng.choice(LABELS)} for k in range(N)]
    # One pre-annotated item, so a blind request on it has something to leak.
    data[3]["predictions"] = {"sentiment": "negative"}
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        [{"name": "sentiment", "description": "Sentiment", "annotation_type": "radio",
          "labels": LABELS}],
        data_files=[data_file],
        assignment_strategy="engine",
        admin_api_key=ADMIN_KEY,
        additional_config={
            "labeling_engine": {
                "enabled": True,
                "sources": [{"id": "fx", "kind": "fixture", "error_rate": 0.1}],
                "cascade": ["fx"],
                "contracts": [{"id": "acc", "kind": "selective_risk",
                               "schema": "sentiment", "error": 0.2, "confidence": 0.8}],
                "humans": {"calibration_rate": 0.5},
                # The test drives the planner itself.
                "runtime": {"planner_interval": 3600},
            },
            "pre_annotation": {"enabled": True},
            "pocket": {"enabled": True, "auto_redirect": False},
        },
    )
    server = FlaskTestServer(port=find_free_port(preferred_port=9640), config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start labeling engine test server")
    yield server
    server.stop()
    from potato.labeling_engine.integration.hooks import clear_engine
    clear_engine()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def engine(engine_server):
    from potato.labeling_engine.integration.hooks import get_engine, get_planner
    eng = get_engine()
    assert eng is not None, "the server did not start the labeling engine"
    report = get_planner().tick()
    assert report["items"] == N, report
    return eng


PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def _login(server, name, user_agent=None, land=True):
    """Register and log in. ``land=False`` stops before the page /auth
    redirects to, as an annotator who goes straight to /pocket does."""
    s = requests.Session()
    if user_agent:
        s.headers["User-Agent"] = user_agent
    if not land:
        s.post(f"{server.base_url}/register", data={"email": name, "pass": "pass"},
               allow_redirects=False)
        s.post(f"{server.base_url}/auth", data={"email": name, "pass": "pass"},
               allow_redirects=False)
        return s
    s.post(f"{server.base_url}/register", data={"email": name, "pass": "pass"})
    s.post(f"{server.base_url}/auth", data={"email": name, "pass": "pass"})
    return s


def _current_item(session, server):
    from potato.user_state_management import get_user_state_manager
    r = session.get(f"{server.base_url}/annotate")
    assert r.status_code == 200
    return r


def test_planner_predicted_and_sampled(engine):
    assert engine.store.prediction_count() == N
    cal = engine.store.requests(purpose=["calibration"])
    assert 0 < len(cal) < N
    assert all(r.visibility == "blind" and r.inclusion_prob == pytest.approx(0.5)
               for r in cal)


def test_annotate_serves_an_engine_request_and_saving_closes_it(engine_server, engine):
    from potato.user_state_management import get_user_state_manager
    s = _login(engine_server, "eng_user_1")
    _current_item(s, engine_server)
    held = engine.store.requests(status=["assigned"], user="eng_user_1")
    assert held, "the engine strategy assigned nothing"
    iid = held[0].item_id
    state = get_user_state_manager().get_user_state("eng_user_1")
    assert iid in state.get_assigned_instance_ids()

    r = s.post(f"{engine_server.base_url}/updateinstance",
               json={"instance_id": iid, "annotations": {"sentiment:positive": "true"}})
    assert r.status_code == 200, r.text
    [done] = [x for x in engine.store.requests(item_id=iid) if x.status == "done"]
    assert done.user_id == "eng_user_1" and done.label == "positive"
    assert done.id == held[0].id   # the request was closed, not a new organic one


def test_ai_suggestions_are_refused_on_blind_items(engine_server, engine):
    s = _login(engine_server, "eng_user_2")
    _current_item(s, engine_server)
    held = engine.store.requests(status=["assigned"], user="eng_user_2")
    assert held and held[0].visibility == "blind"
    r = s.get(f"{engine_server.base_url}/api/ai_assistant", params={"annotationId": 0})
    assert r.status_code == 403
    assert "blind" in r.json()["error"]


def _chat_that_records(monkeypatch, calls):
    import potato.chat_manager as cm

    class _Endpoint:
        def query(self, *a, **k):
            calls.append(a)
            return "positive"
        chat_query = query

    class _Chat:
        enabled = True
        endpoint = _Endpoint()
        max_history_per_instance = 50

        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name) or "positive"

    monkeypatch.setattr(cm, "_chat_manager", _Chat())


def _assert_every_ai_route_refuses(engine_server, s, held, calls):
    from potato.routes import ENGINE_BLIND_ROUTES
    checked = 0
    for method, path in ENGINE_BLIND_ROUTES:
        url = f"{engine_server.base_url}{path}"
        if method == "GET":
            r = s.get(url, params={"annotationId": 0, "annotation_id": 0,
                                   "instance_id": held.item_id, "schema": "sentiment"})
        else:
            r = s.post(url, json={"message": "what is the label?",
                                  "instance_id": held.item_id})
        assert r.status_code == 403, (path, r.status_code, r.text[:200])
        checked += 1
    assert checked == len(ENGINE_BLIND_ROUTES) and not calls


def test_every_ai_route_refuses_on_a_blind_item(engine_server, engine, monkeypatch):
    """Each route in routes.ENGINE_BLIND_ROUTES, by class rather than one at a
    time. The chat assistant is switched on with an endpoint that records
    calls, so a 403 means the route refused, not that chat was off."""
    calls = []
    _chat_that_records(monkeypatch, calls)
    s = _login(engine_server, "eng_user_ai")
    _current_item(s, engine_server)
    [held] = engine.store.requests(status=["assigned"], user="eng_user_ai")[:1]
    assert held.visibility == "blind"
    _assert_every_ai_route_refuses(engine_server, s, held, calls)


def test_an_item_stays_blind_after_its_first_save(engine_server, engine, monkeypatch):
    """Found by potato-skill (G1). A radio click autosaves, which closes the
    request; blindness was read from held requests only, so from that click
    on the page showed the pre-annotation and every AI route answered, and
    the edits that followed were written into the blind label."""
    calls = []
    _chat_that_records(monkeypatch, calls)
    rid = _hand(engine, "eng_user_g1", "item_3", purpose="calibration",
                visibility="blind", split="dev")
    s = _login(engine_server, "eng_user_g1")
    _current_item(s, engine_server)
    r = s.post(f"{engine_server.base_url}/updateinstance",
               json={"instance_id": "item_3", "annotations": {"sentiment:positive": "true"}})
    assert r.status_code == 200, r.text
    held = engine.store.get_request(rid)
    assert held.status == "done" and held.label == "positive"
    # Still on the item: no machine answer anywhere, every AI route refuses.
    cur = s.get(f"{engine_server.base_url}/api/current_instance").json()
    assert cur["instance_id"] == "item_3" and "predictions" not in cur["data"]
    assert "predictions" not in s.get(f"{engine_server.base_url}/api/instance_data").json()
    _assert_every_ai_route_refuses(engine_server, s, held, calls)
    # The page re-rendered (a reload, or Back to the item) prefills nothing
    # from the machine and still says it is blind.
    page = s.get(f"{engine_server.base_url}/annotate").text
    assert "negative" not in _checked(page)
    assert "Suggestions are off for this item" in page


def test_a_released_hold_leaves_the_holders_page(engine_server, engine):
    """Found by potato-skill (G2). After release_stale, the old holder's open
    tab still had the item, now with no request behind it: the machine's
    answer showed, and its save closed a blind request they no longer held."""
    import time as _time
    rid = _hand(engine, "eng_user_g2", "item_3", purpose="calibration",
                visibility="blind", split="cert")
    s = _login(engine_server, "eng_user_g2")
    _current_item(s, engine_server)
    cur = s.get(f"{engine_server.base_url}/api/current_instance").json()
    assert cur["instance_id"] == "item_3"
    engine.store.update_request(rid, assigned_at=_time.time() - 7200)
    assert engine.release_stale(3600) >= 1
    # The tab saves anyway.
    r = s.post(f"{engine_server.base_url}/updateinstance",
               json={"instance_id": "item_3", "annotations": {"sentiment:neutral": "true"}})
    assert r.status_code == 403, r.text
    assert engine.store.get_request(rid).status == "open"
    assert not [x for x in engine.store.requests(item_id="item_3", status=["done"])
                if x.user_id == "eng_user_g2"]
    cur = s.get(f"{engine_server.base_url}/api/current_instance")
    assert cur.status_code != 200 or cur.json()["instance_id"] != "item_3"


def test_a_returning_annotator_lands_on_their_open_request(engine_server, engine):
    """Found by potato-skill (A7): the page opened on the last item they had
    finished, and only Next reached the new request."""
    s = _login(engine_server, "eng_returner")
    _current_item(s, engine_server)
    [first] = engine.store.requests(status=["assigned"], user="eng_returner")[:1]
    s.post(f"{engine_server.base_url}/updateinstance", json={
        "instance_id": first.item_id, "annotations": {"sentiment:negative": "true"}})
    rid = _hand(engine, "eng_returner", "item_14", purpose="verify", visibility="blind")
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager
    state = get_user_state_manager().get_user_state("eng_returner")
    state.assign_instance(get_item_state_manager().get_item("item_14"))
    # Coming back: their position is still the item they finished.
    state.current_instance_index = state.instance_id_ordering.index(first.item_id)
    s.get(f"{engine_server.base_url}/annotate")
    cur = s.get(f"{engine_server.base_url}/api/current_instance").json()
    held = {r.item_id for r in engine.store.requests(status=["assigned"], user="eng_returner")}
    assert "item_14" in held and cur["instance_id"] in held
    assert cur["instance_id"] != first.item_id


def test_blind_item_data_leaves_out_machine_answers(engine_server, engine):
    """The pre-annotation field is not in the item data on a blind request."""
    s = _login(engine_server, "eng_user_fields")
    _current_item(s, engine_server)
    held = engine.store.requests(status=["assigned"], user="eng_user_fields")
    assert held and held[0].visibility == "blind"
    data = s.get(f"{engine_server.base_url}/api/instance_data").json()
    cur = s.get(f"{engine_server.base_url}/api/current_instance").json()["data"]
    assert "predictions" not in data and "predictions" not in cur
    assert "text" in data


def test_labels_through_the_routes_certify(engine_server, engine):
    """Answer every calibration request through /updateinstance, then certify."""
    from potato.item_state_management import get_item_state_manager
    gold = {}
    ism = get_item_state_manager()
    for iid in ism.get_instance_ids():
        gold[iid] = ism.get_item(iid).get_data()["gold"]
    sessions = {}
    for _ in range(4 * N):
        open_cal = engine.store.requests(purpose=["calibration"],
                                         status=["open", "assigned"])
        if not open_cal:
            break
        # Each request goes to whoever it was assigned to, or a new person.
        name = open_cal[0].assigned_user or f"cal_{len(sessions)}"
        s = sessions.get(name) or _login(engine_server, name)
        sessions[name] = s
        _current_item(s, engine_server)
        for r in engine.store.requests(status=["assigned"], user=name):
            s.post(f"{engine_server.base_url}/updateinstance", json={
                "instance_id": r.item_id,
                "annotations": {f"sentiment:{gold[r.item_id]}": "true"}})
    assert not engine.store.requests(purpose=["calibration"], status=["open", "assigned"])

    scheme = engine.scheme("sentiment")
    res = engine.certify(scheme)["acc"]
    # One calibration item per labeled item (tests above hand a second
    # request on item_3).
    items = {r.item_id for r in engine.store.requests(purpose=["calibration"])}
    assert res["n_cert"] + res["n_dev"] == len(items)
    counts = engine.resolve(scheme)
    assert counts["human"] >= res["n_cert"] + res["n_dev"]


def test_item_side_counts_the_human(engine_server, engine):
    """The commit funnel registered annotators on the item side too."""
    from potato.item_state_management import get_item_state_manager
    done = [r for r in engine.store.requests(status=["done"]) if r.user_id]
    ism = get_item_state_manager()
    r = done[0]
    assert r.user_id in ism.get_annotators_for_item(r.item_id)


def test_a_caught_up_annotator_is_not_sent_to_the_completion_page(engine_server, engine):
    """Under the engine, no work now is not the end: new requests open later."""
    from potato.labeling_engine.model import HumanRequest
    from potato.user_state_management import get_user_state_manager
    s = _login(engine_server, "eng_waiter")
    for _ in range(N):
        r = s.get(f"{engine_server.base_url}/annotate")
        held = engine.store.requests(status=["assigned"], user="eng_waiter")
        if not held:
            break
        for h in held:
            s.post(f"{engine_server.base_url}/updateinstance", json={
                "instance_id": h.item_id, "annotations": {"sentiment:negative": "true"}})
    r = s.get(f"{engine_server.base_url}/annotate")
    assert "Nothing to label right now" in r.text
    state = get_user_state_manager().get_user_state("eng_waiter")
    assert str(state.get_phase()).lower().endswith("annotation")
    # A new request appears; the same annotator gets it on reload.
    labeled = {x.item_id for x in engine.store.requests(status=["done"])
               if x.user_id == "eng_waiter"}
    free = next(i for i in [f"item_{k}" for k in range(N)] if i not in labeled)
    engine.store.add_requests([HumanRequest(free, "sentiment", "verify", None,
                                            visibility="shown")])
    s.get(f"{engine_server.base_url}/annotate")
    assert engine.store.requests(status=["assigned"], user="eng_waiter")


def test_an_annotator_with_nothing_left_to_come_finishes(engine_server, engine,
                                                         monkeypatch):
    """Found by potato-skill (I1/A5): with every item resolved, or the budget
    spent, the page said "come back later" forever, so no post-study page
    and no crowd completion code was ever reached."""
    from potato.user_state_management import get_user_state_manager
    s = _login(engine_server, "eng_done")
    _current_item(s, engine_server)
    for h in engine.store.requests(status=["assigned"], user="eng_done"):
        s.post(f"{engine_server.base_url}/updateinstance", json={
            "instance_id": h.item_id, "annotations": {"sentiment:negative": "true"}})
    monkeypatch.setattr(engine, "human_work_remaining", lambda: None)
    monkeypatch.setattr(engine, "claim_requests", lambda *a, **k: [])
    monkeypatch.setattr(engine, "has_work_for", lambda *a, **k: False)
    r = s.get(f"{engine_server.base_url}/annotate")
    assert "Nothing to label right now" not in r.text
    state = get_user_state_manager().get_user_state("eng_done")
    assert not str(state.get_phase()).lower().endswith("annotation")



class TestRestApi:

    def _get(self, server, path, **params):
        return requests.get(f"{server.base_url}/api/engine/v1{path}", params=params,
                            headers={"X-API-Key": ADMIN_KEY}, timeout=30)

    def test_reads_need_admin_auth(self, engine_server, engine):
        r = requests.get(f"{engine_server.base_url}/api/engine/v1/status", timeout=10)
        assert r.status_code == 403

    def test_status_and_contracts(self, engine_server, engine):
        r = self._get(engine_server, "/status")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["items"] == N and "sentiment" in body["schemes"]
        r = self._get(engine_server, "/schemes/sentiment/contracts")
        assert r.status_code == 200 and "acc" in r.json()
        assert self._get(engine_server, "/schemes/nope/contracts").status_code == 404

    def test_certify_and_certificate(self, engine_server, engine):
        r = requests.post(f"{engine_server.base_url}/api/engine/v1/certify",
                          headers={"X-API-Key": ADMIN_KEY}, timeout=30)
        assert r.status_code == 200 and "sentiment" in r.json()
        r = self._get(engine_server, "/certificate", format="md")
        assert r.status_code == 200 and r.text.startswith("# Labeling certificate")

    def test_charts_data(self, engine_server, engine):
        rel = self._get(engine_server, "/schemes/sentiment/reliability")
        assert rel.status_code == 200 and "fx" in rel.json()
        rc = self._get(engine_server, "/schemes/sentiment/risk_coverage")
        assert rc.status_code == 200 and rc.json()["tier"] == "fx"
        for p in rc.json()["points"]:
            assert p["error"] <= p["upper_bound"] + 1e-9
        assert self._get(engine_server, "/calls", limit=5).status_code == 200
        assert self._get(engine_server, "/requests", purpose="calibration").status_code == 200
        assert self._get(engine_server, "/schemes/sentiment/drift").status_code == 200

    @pytest.mark.parametrize("path,params,word", [
        ("/calls", {"limit": "abc"}, "limit"),
        ("/calls", {"offset": "x"}, "offset"),
        ("/requests", {"limit": "1.5"}, "limit"),
        ("/requests", {"purpose": "calibraton"}, "calibraton"),
        ("/requests", {"status": "closed"}, "closed"),
        ("/certificate", {"format": "xml"}, "xml"),
    ])
    def test_bad_parameters_are_a_json_400(self, engine_server, engine, path, params, word):
        r = self._get(engine_server, path, **params)
        assert r.status_code == 400 and word in r.json()["error"]

    def test_purpose_takes_a_comma_list(self, engine_server, engine):
        one = self._get(engine_server, "/requests", purpose="calibration").json()
        both = self._get(engine_server, "/requests", purpose="calibration,verify").json()
        assert len(both["requests"]) >= len(one["requests"]) > 0


def _hand(engine, user, item_id, **fields):
    """Put a request on ``item_id`` in ``user``'s hands before they log in;
    held requests are served first."""
    from potato.labeling_engine.model.records import HumanRequest
    [rid] = engine.store.add_requests([HumanRequest(
        item_id=item_id, schema="sentiment", inclusion_prob=None,
        assigned_user=user, status="assigned", **fields)])
    return rid


def _checked(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    return [i.get("value") for i in soup.select('input[type="radio"]')
            if i.has_attr("checked")]


class TestTaskPageNote:
    """The note above the item, and what each kind of request withholds."""

    def test_blind_request_withholds_everything(self, engine_server, engine):
        _hand(engine, "note_blind", "item_3", purpose="calibration", visibility="blind")
        s = _login(engine_server, "note_blind")
        html = s.get(f"{engine_server.base_url}/annotate").text
        assert 'data-engine-visibility="blind"' in html
        assert 'class="engine-request-note" data-purpose="calibration"' in html
        # item_3 carries a pre-annotation ("negative"); a blind request must
        # not show it.
        assert _checked(html) == []

    def test_without_a_blind_request_the_pre_annotation_still_shows(self, engine_server, engine):
        """The control for the test above: the item's pre-annotation does
        reach a page that holds no engine request on it."""
        _hand(engine, "note_control", "item_3", purpose="verify", visibility="shown")
        s = _login(engine_server, "note_control")
        assert _checked(s.get(f"{engine_server.base_url}/annotate").text) == ["negative"]

    def test_verify_request_prefills_the_machine_answer(self, engine_server, engine):
        from potato.labeling_engine.schemes import SchemeSpec  # noqa: F401
        scheme = engine.scheme("sentiment")
        version = engine.tier_versions(scheme)[0]
        pred = engine.store.current_predictions("sentiment", version)["item_5"]
        _hand(engine, "note_verify", "item_5", purpose="verify", visibility="shown",
              shown_prediction_id=pred.id)
        s = _login(engine_server, "note_verify")
        html = s.get(f"{engine_server.base_url}/annotate").text
        assert 'data-purpose="verify"' in html
        assert _checked(html) == [pred.value]
        from potato.user_state_management import get_user_state_manager
        state = get_user_state_manager().get_user_state("note_verify")
        bd = state.instance_id_to_behavioral_data["item_5"]
        assert bd.pre_annotation_seeds == {"sentiment": pred.value}

    def test_progress_counts_requests_not_the_corpus(self, engine_server, engine):
        from potato.flask_server import progress_counts
        _hand(engine, "note_progress", "item_7", purpose="calibration", visibility="blind")
        s = _login(engine_server, "note_progress")
        s.get(f"{engine_server.base_url}/annotate")
        # Their work: what they hold, plus what anyone may still take.
        theirs = {r.item_id for r in engine.store.requests(status=["assigned"],
                                                            user="note_progress")}
        open_ids = {r.item_id for r in engine.store.requests(status=["open"])}
        finished, total = progress_counts("note_progress")
        assert finished == 0 and "item_7" in theirs
        assert total == len(open_ids | theirs)
        assert total < N


class TestAdminPage:

    def test_needs_the_admin_key(self, engine_server, engine):
        """A browser without an admin session goes to the dashboard's key form
        (potato-skill I7), and gets nothing of the page."""
        r = requests.get(f"{engine_server.base_url}/admin/labeling-engine", timeout=10,
                         allow_redirects=False)
        assert r.status_code in (302, 303) and r.headers["Location"].rstrip("/").endswith("/admin")
        assert "le-root" not in r.text

    def test_renders_with_the_contract_target(self, engine_server, engine):
        r = requests.get(f"{engine_server.base_url}/admin/labeling-engine",
                         headers={"X-API-Key": ADMIN_KEY}, timeout=10)
        assert r.status_code == 200
        assert 'id="le-root"' in r.text
        assert 'const targets = {"sentiment": 0.2};' in r.text

    def test_linked_from_the_dashboard(self, engine_server, engine):
        r = requests.get(f"{engine_server.base_url}/admin",
                         headers={"X-API-Key": ADMIN_KEY, "Accept": "text/html"}, timeout=10)
        assert 'href="/admin/labeling-engine"' in r.text


class TestPocket:
    """Pocket Mode, where phones land, on an engine study."""

    def test_a_verify_already_shown_on_desktop_stays_shown_on_pocket(self, engine_server, engine):
        """Found by potato-skill (E5): Pocket rewrote a verify request to blind
        after the desktop page had prefilled the machine's answer."""
        scheme = engine.scheme("sentiment")
        pred = engine.store.current_predictions(
            "sentiment", engine.tier_versions(scheme)[0])["item_11"]
        rid = _hand(engine, "pocket_e5", "item_11", purpose="verify", visibility="shown",
                    shown_prediction_id=pred.id)
        s = _login(engine_server, "pocket_e5")
        page = s.get(f"{engine_server.base_url}/annotate").text
        assert "a model's answer is filled in" in page.lower()
        s.get(f"{engine_server.base_url}/pocket/api/batch", timeout=10)
        req = engine.store.get_request(rid)
        assert req.visibility == "shown" and req.shown_prediction_id == pred.id

    def test_pocket_says_when_the_answer_is_the_label(self, engine_server, engine):
        """Found by potato-skill (E9): no engine note on Pocket cards."""
        _hand(engine, "pocket_e9", "item_12", purpose="resolve", visibility="blind")
        s = _login(engine_server, "pocket_e9", user_agent=PHONE_UA, land=False)
        batch = s.get(f"{engine_server.base_url}/pocket/api/batch", timeout=10).json()
        [card] = [it for it in batch["items"] if it["instance_id"] == "item_12"]
        assert card["note"].endswith("your answer is the label.")

    def test_pocket_tops_up_a_full_batch_from_the_engine(self, engine_server, engine):
        """Found by potato-skill (E1): one card per fetch after the first."""
        from potato.labeling_engine.model.records import HumanRequest
        engine.store.add_requests([HumanRequest(
            item_id=f"item_{k}", schema="sentiment", purpose="calibration",
            inclusion_prob=0.5) for k in range(30, 38)])
        s = _login(engine_server, "pocket_e1")
        batch = s.get(f"{engine_server.base_url}/pocket/api/batch?n=5", timeout=10).json()
        assert len(batch["items"]) == 5
        for it in batch["items"]:
            s.post(f"{engine_server.base_url}/updateinstance",
                   json={"instance_id": it["instance_id"],
                         "annotations": {"sentiment:negative": "true"}})
        again = s.get(f"{engine_server.base_url}/pocket/api/batch?n=5", timeout=10).json()
        assert len(again["items"]) >= 2

    def test_a_pocket_batch_respects_the_per_annotator_cap(self, engine_server, engine):
        """Found by potato-skill (M1): capped at 3, one batch claimed 23 items;
        desktop stopped at 3."""
        from potato.labeling_engine.model.records import HumanRequest
        from potato.user_state_management import get_user_state_manager
        engine.store.add_requests([HumanRequest(
            item_id=f"item_{k}", schema="sentiment", purpose="calibration",
            inclusion_prob=0.5) for k in range(20, 28)])
        s = _login(engine_server, "pocket_m1", user_agent=PHONE_UA, land=False)
        user = get_user_state_manager().get_user_state("pocket_m1")
        user.max_assignments = 3
        batch = s.get(f"{engine_server.base_url}/pocket/api/batch?n=10", timeout=10).json()
        assert 0 < len(batch["items"]) <= 3
        assert len(engine.store.requests(status=["assigned"], user="pocket_m1")) <= 3 * 2

    def test_a_cap_of_zero_hands_out_nothing(self, engine_server, engine):
        """Found by potato-skill (Q1): cap 0 (an observer role) got 23 items on
        Pocket while desktop said there was nothing to label."""
        from potato.user_state_management import get_user_state_manager
        # Capped before signing in: sign-in already hands out work.
        usm = get_user_state_manager()
        if not usm.has_user("pocket_q1"):
            usm.add_user("pocket_q1")
        usm.get_user_state("pocket_q1").max_assignments = 0
        s = _login(engine_server, "pocket_q1", user_agent=PHONE_UA, land=False)
        assert usm.get_user_state("pocket_q1").get_max_assignments() == 0
        batch = s.get(f"{engine_server.base_url}/pocket/api/batch?n=10", timeout=10).json()
        assert batch["items"] == []
        assert engine.store.requests(status=["assigned"], user="pocket_q1") == []

    def test_verify_served_on_pocket_is_recorded_blind_and_the_stack_tops_up(
            self, engine_server, engine):
        from potato.labeling_engine.model.records import HumanRequest
        scheme = engine.scheme("sentiment")
        pred = engine.store.current_predictions(
            "sentiment", engine.tier_versions(scheme)[0])["item_9"]
        rid = _hand(engine, "pocket_eng", "item_9", purpose="verify", visibility="shown",
                    shown_prediction_id=pred.id)
        # A phone: /annotate sends it to /pocket before rendering anything, so
        # the desktop page never prefilled the answer.
        s = _login(engine_server, "pocket_eng", user_agent=PHONE_UA, land=False)
        batch = s.get(f"{engine_server.base_url}/pocket/api/batch", timeout=10).json()
        assert "item_9" in [it["instance_id"] for it in batch["items"]]
        # Pocket shows no machine answer, so the ledger must not say it did.
        [req] = [r for r in engine.store.requests(item_id="item_9") if r.id == rid]
        assert req.visibility == "blind" and req.shown_prediction_id is None

        for it in batch["items"]:
            r = s.post(f"{engine_server.base_url}/updateinstance",
                       json={"instance_id": it["instance_id"],
                             "annotations": {"sentiment:positive": "true"}})
            assert r.status_code == 200, r.text
        engine.store.add_requests([HumanRequest(
            item_id="item_13", schema="sentiment", purpose="calibration",
            inclusion_prob=0.5)])
        again = s.get(f"{engine_server.base_url}/pocket/api/batch", timeout=10).json()
        assert again["items"], "the card stack emptied while the engine had work"
