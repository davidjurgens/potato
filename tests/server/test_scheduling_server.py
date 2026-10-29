"""
Scheduled sessions over HTTP, on an in-process server.

The full participant path (consent, regular flow, enrolment with contact
details, the out-of-window page, a resume link from a message, answering the
wave) and the PII guarantees: the email address and phone number given at
enrolment appear in no file under the output directory, in no file any
registered exporter writes, and not in the data archive.
"""

from __future__ import annotations

import copy
import io
import os
import re
import shutil
import tarfile

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "examples", "advanced",
                       "two-wave-panel")
EMAIL = "pii-sentinel-7731@example.org"
PHONE_TYPED = "+44 7700 900 731"
PHONE = "+447700900731"
YES = "Yes, you may contact me"
NO = "No reminders, thank you"
ADMIN_KEY = "scheduling-test-admin-key"


def _config(test_dir: str, port: int) -> str:
    for sub in ("data", "surveys"):
        shutil.copytree(os.path.join(EXAMPLE, sub), os.path.join(test_dir, sub),
                        dirs_exist_ok=True)
    cfg = yaml.safe_load(open(os.path.join(EXAMPLE, "config.yaml")))
    cfg["task_dir"] = os.path.abspath(test_dir)
    cfg["output_annotation_dir"] = os.path.join(os.path.abspath(test_dir), "annotation_output")
    cfg["schedule"]["scheduler"] = False        # the test drives tick() itself
    cfg["notifications"]["base_url"] = f"http://localhost:{port}"
    cfg["admin_api_key"] = ADMIN_KEY
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as fh:
        yaml.safe_dump(cfg, fh)
    return path


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("scheduling_server")
    port = find_free_port()
    srv = FlaskTestServer(port=port, config_file=_config(test_dir, port))
    if not srv.start():
        pytest.fail("server did not start")
    srv.test_dir = test_dir
    yield srv
    srv.stop()
    shutil.rmtree(test_dir, ignore_errors=True)


def _manager():
    from potato.scheduling import manager as m
    return m._LATEST


def _participant(srv, user, contact_answer=YES):
    s = requests.Session()
    s.post(f"{srv.base_url}/register", data={"email": user, "pass": "pw"})
    s.post(f"{srv.base_url}/auth", data={"email": user, "pass": "pw"})
    s.post(f"{srv.base_url}/updateinstance", json={
        "instance_id": "__phase_page__",
        "annotations": {"study_consent:::I agree": "I agree",
                        f"contact_consent:::{contact_answer}": contact_answer}})
    s.post(f"{srv.base_url}/annotate", json={"action": "next_instance",
                                             "instance_id": "__phase_page__"})
    from potato.user_state_management import get_user_state_manager
    for _ in range(10):
        r = s.get(f"{srv.base_url}/annotate", allow_redirects=False)
        if r.status_code == 302:
            return s, r
        iid = get_user_state_manager().get_user_state(user).get_current_instance().get_id()
        s.post(f"{srv.base_url}/updateinstance",
               json={"instance_id": iid, "annotations": {"agreement:::4": "4"}})
        s.post(f"{srv.base_url}/annotate", json={"action": "next_instance", "instance_id": iid})
    pytest.fail("never reached the end of the regular flow")


class TestSchedulingFlow:
    def test_full_participant_path(self, server):
        s, r = _participant(server, "panel1")
        assert r.headers["Location"].endswith("/schedule/enrol")
        page = s.get(f"{server.base_url}/schedule/enrol").text
        assert 'name="email"' in page and 'name="phone"' in page
        # A bad phone number is refused with a message, and nothing is stored.
        r = s.post(f"{server.base_url}/schedule/enrol",
                   data={"timezone": "America/New_York", "phone": "555-0100"})
        assert r.status_code == 400 and "country code" in r.text
        assert _manager().participant("panel1") is None
        r = s.post(f"{server.base_url}/schedule/enrol", allow_redirects=False,
                   data={"timezone": "America/New_York", "timezone_detected": "America/New_York",
                         "email": EMAIL, "phone": PHONE_TYPED})
        assert r.status_code == 302 and "/schedule?enrolled=1" in r.headers["Location"]
        m = _manager()
        held = m.contacts.get("panel1")
        assert (held["email"], held["phone"]) == (EMAIL, PHONE)
        # Coming back early: the gate sends them to the out-of-window page,
        # which names the opening time in their zone (09:00 local, a week on).
        r = s.get(f"{server.base_url}/", allow_redirects=False)
        assert r.headers["Location"].endswith("/schedule")
        status = s.get(f"{server.base_url}/schedule").text
        assert "Your next session is not open yet" in status
        assert re.search(r"id=\"schedule-next-opens\">\w{3} \d+ \w{3} \d{4}, 09:00 E[SD]T<", status)
        early = s.get(f"{server.base_url}/schedule/session/wave:followup")
        assert early.status_code == 200 and "One-week follow-up is not open yet" in early.text
        assert 'name="changed_view"' not in early.text

        wave = m.sessions("panel1")[0]
        m.tick(wave["opens_at"] + 1)                       # the opening messages
        sent = [n for n in m.store.notifications(participant="panel1")
                if n["rule"] == "open" and n["channel"] == "log"][0]
        # The harness may move the server to another port than the config's
        # base_url names, so follow the link's path on the real address.
        link = server.base_url + re.search(r"http://\S+?(/s/\S+)", sent["preview"]).group(1)
        assert EMAIL not in sent["preview"]

        # A fresh browser follows the link: signed in as panel1, on the wave.
        m.clock = lambda: wave["opens_at"] + 120
        fresh = requests.Session()
        r = fresh.get(link, allow_redirects=False)
        assert r.status_code == 302 and r.headers["Location"].endswith("/schedule/session/wave:followup")
        form = fresh.get(f"{server.base_url}/schedule/session/wave:followup").text
        assert "Since last week" in form
        r = fresh.post(f"{server.base_url}/schedule/session/wave:followup",
                       data={"changed_view": "A little"})
        assert r.status_code == 400 and "This question needs an answer." in r.text
        r = fresh.post(f"{server.base_url}/schedule/session/wave:followup",
                       data={"changed_view": "A little", "trust_media": "2",
                             "what_changed": "a documentary"}, allow_redirects=False)
        assert r.status_code == 302
        done = fresh.get(server.base_url + r.headers["Location"]).text
        assert "FOLLOWUP-DONE" in done and "Your answers to One-week follow-up are saved" in done
        stored = m.session("panel1", "wave:followup")
        assert stored["answers"] == {"changed_view": "A little", "trust_media": 2,
                                     "what_changed": "a documentary"}
        # A tampered link signs nobody in.
        assert fresh.get(link[:-3] + "AAA").status_code == 403

    def test_no_contact_consent_stores_no_address(self, server):
        s, _r = _participant(server, "panel2", contact_answer=NO)
        page = s.get(f"{server.base_url}/schedule/enrol").text
        assert 'name="email"' not in page and "chose not to be contacted" in page
        # Posting an address anyway does not store it.
        s.post(f"{server.base_url}/schedule/enrol",
               data={"timezone": "Europe/Berlin", "email": "forged@example.org"})
        m = _manager()
        assert m.participant("panel2")["contact_consent"] == 0
        assert m.contacts.get("panel2") is None
        assert m.store.notifications(participant="panel2") == []

    def test_admin_page_and_api_show_no_addresses(self, server):
        s = requests.Session()
        headers = {"X-API-Key": ADMIN_KEY}
        assert s.get(f"{server.base_url}/admin/api/schedule").status_code == 403
        r = s.get(f"{server.base_url}/admin/api/schedule", headers=headers)
        assert r.status_code == 200
        body = r.text
        assert "panel1" in body and EMAIL not in body and PHONE not in body
        page = s.get(f"{server.base_url}/admin/schedule", headers=headers)
        assert page.status_code == 200 and "Participants and compliance" in page.text
        assert EMAIL not in page.text and PHONE not in page.text

    def test_contact_details_reach_no_file_export_or_archive(self, server):
        """Every registered exporter, every file under the output directory,
        and the data archive are free of the address and the number."""
        from potato.export.cli import build_export_context
        from potato.export.registry import export_registry
        from potato.server_utils.data_archive import build_archive
        from potato.user_state_management import get_user_state_manager
        assert _manager().contacts.get("panel1")["email"] == EMAIL   # still held
        get_user_state_manager().save_user_state(
            get_user_state_manager().get_user_state("panel1"))
        cfg_path = os.path.join(server.test_dir, "config.yaml")
        ctx = build_export_context(cfg_path)
        out_root = os.path.join(server.test_dir, "exports")
        ran = []
        for name in export_registry.get_supported_formats():
            exporter = export_registry.get(name)
            try:
                ok, _why = exporter.can_export(copy.copy(ctx))
                if not ok:
                    continue
                exporter.export(copy.copy(ctx), os.path.join(out_root, name), {})
                ran.append(name)
            except Exception:
                continue
        assert "schedule" in ran and "csv" in ran and "jsonl" in ran

        def scan(root):
            hits = []
            for dirpath, _d, files in os.walk(root):
                for f in files:
                    data = open(os.path.join(dirpath, f), "rb").read()
                    if EMAIL.encode() in data or PHONE.encode() in data:
                        hits.append(os.path.join(dirpath, f))
            return hits

        assert scan(out_root) == []
        assert scan(ctx.output_dir) == []
        buf = io.BytesIO()
        build_archive(ctx.output_dir, server.test_dir, buf)
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    data = tar.extractfile(member).read()
                    assert EMAIL.encode() not in data and PHONE.encode() not in data, member.name
        # And the sessions export does carry the wave answers.
        rows = open(os.path.join(out_root, "schedule", "schedule_sessions.csv")).read()
        assert "a documentary" in rows


class TestAdminKeyUnderTheCli:
    """The admin routes authorize the key when the server runs as
    ``python -m potato start``, not only on the in-process test server.

    Under the CLI, ``potato.routes`` is not the module that registered the
    routes, so a handler that imports it re-runs its decorators against the
    running app and fails. The in-process server above already has
    ``potato.routes`` loaded and never sees that.
    """

    @pytest.fixture(scope="class")
    def cli_server(self):
        import signal
        import subprocess
        import sys
        import time

        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        test_dir = create_test_directory("scheduling_cli_admin")
        port = find_free_port()
        config_path = _config(test_dir, port)
        base = f"http://127.0.0.1:{port}"
        log = open(os.path.join(test_dir, "server.log"), "a")
        proc = subprocess.Popen(
            [sys.executable, "-m", "potato", "start", config_path, "-p", str(port),
             "--host", "127.0.0.1"],
            cwd=test_dir, env=dict(os.environ, PYTHONPATH=repo),
            stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if proc.poll() is not None:
                    pytest.fail("server exited at start; see " + log.name)
                try:
                    requests.get(base + "/", timeout=1)
                    break
                except requests.RequestException:
                    time.sleep(0.5)
            else:
                pytest.fail("server did not start; see " + log.name)
            yield base
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log.close()
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_admin_key_opens_the_schedule_api_and_page(self, cli_server):
        headers = {"X-API-Key": ADMIN_KEY}
        assert requests.get(f"{cli_server}/admin/api/schedule", timeout=10).status_code == 403
        assert requests.get(f"{cli_server}/admin/api/schedule",
                            headers={"X-API-Key": "wrong"}, timeout=10).status_code == 403
        r = requests.get(f"{cli_server}/admin/api/schedule", headers=headers, timeout=10)
        assert r.status_code == 200, r.text[:300]
        assert "participants" in r.json()
        page = requests.get(f"{cli_server}/admin/schedule", headers=headers,
                            allow_redirects=False, timeout=10)
        assert page.status_code == 200 and "Participants and compliance" in page.text
