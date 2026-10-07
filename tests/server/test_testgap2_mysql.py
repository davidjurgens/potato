"""
The MySQL backend against a real MySQL server, through a real restart.

Skipped unless POTATO_TEST_MYSQL names a server, for example
``POTATO_TEST_MYSQL=root:testpw@127.0.0.1:33306/potato_test``. The earlier tests
replaced the connection pool with a Mock, so no query ever ran: saving raised
on every request and the suite still passed.
"""

import json
import os
import re
import signal
import subprocess
import sys
import time

import pytest
import requests

from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.environ.get("POTATO_TEST_MYSQL", "")
PORT = 9822
BASE = f"http://127.0.0.1:{PORT}"

pytestmark = pytest.mark.skipif(not TARGET, reason="set POTATO_TEST_MYSQL to run")


def _db():
    m = re.match(r"(?P<user>[^:]+):(?P<pw>[^@]*)@(?P<host>[^:/]+):(?P<port>\d+)/(?P<db>\w+)", TARGET)
    return m.groupdict()


CONFIG = """
annotation_task_name: MySQL test
task_dir: .
output_annotation_dir: annotation_output
data_files: [data/items.jsonl]
item_properties: {{id_key: id, text_key: text}}
user_config: {{allow_all_users: true, users: []}}
require_password: {require_password}
assignment_strategy: fixed_order
admin_api_key: mysqlkey
max_annotations_per_item: 1
database: {{type: mysql, host: "{host}", port: {port}, database: {db}, username: {user}, password: "{pw}"}}
annotation_schemes:
- {{annotation_type: radio, name: ok, description: pick, labels: [good, bad]}}
- {{annotation_type: text, name: note, description: note}}
- {{annotation_type: span, name: ent, description: mark, labels: [X]}}
"""


def _start(task_dir):
    log = open(os.path.join(task_dir, "server.log"), "a")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO, "potato", "flask_server.py"), "start",
         "config.yaml", "-p", str(PORT), "--host", "127.0.0.1"],
        cwd=task_dir, env=dict(os.environ, PYTHONPATH=REPO), stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        if proc.poll() is not None:
            pytest.fail("server exited; see " + os.path.join(task_dir, "server.log"))
        try:
            requests.get(BASE + "/", timeout=1)
            return proc
        except requests.RequestException:
            time.sleep(0.5)
    proc.kill()
    pytest.fail("server did not start")


def _stop(proc):
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _login(name, password="pw"):
    s = requests.Session()
    s.post(BASE + "/register", data={"email": name, "pass": password}, timeout=5)
    s.post(BASE + "/auth", data={"email": name, "pass": password}, timeout=5)
    s.get(BASE + "/annotate", timeout=5)
    return s


def _drop_tables():
    import mysql.connector
    db = _db()
    conn = mysql.connector.connect(host=db["host"], port=int(db["port"]), user=db["user"],
                                   password=db["pw"], database=db["db"])
    cur = conn.cursor()
    for table in ("annotation_history_log", "user_state_documents", "ai_hints",
                  "behavioral_data", "phase_annotations", "span_annotations",
                  "label_annotations", "user_instance_assignments", "user_states"):
        cur.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()


def _task_dir(name, require_password):
    _drop_tables()
    db = _db()
    d = create_test_directory(name)
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    with open(os.path.join(d, "data", "items.jsonl"), "w") as f:
        for i in range(3):
            f.write(json.dumps({"id": f"i{i}", "text": f"item {i} TARGET"}) + "\n")
    with open(os.path.join(d, "config.yaml"), "w") as f:
        f.write(CONFIG.format(require_password=str(require_password).lower(), **db))
    return d


@pytest.fixture
def task_dir():
    return _task_dir("tg2_mysql", False)


def test_annotations_survive_a_restart_on_mysql(task_dir):
    proc = _start(task_dir)
    try:
        s = _login("u1")
        r = s.post(BASE + "/updateinstance", json={
            "instance_id": "i0", "annotations": {"ok:good": "good", "note:text_box": "0"},
            "span_annotations": [{"schema": "ent", "name": "X", "start": 7, "end": 13,
                                  "value": "TARGET", "target_field": "text", "id": "sp1"}]})
        assert r.status_code == 200, r.text
        assert requests.get(BASE + "/admin/user_state/nobody",
                            headers={"X-API-Key": "mysqlkey"}).status_code == 404
    finally:
        _stop(proc)

    assert not os.path.exists(os.path.join(task_dir, "annotation_output", "u1", "user_state.json"))

    proc = _start(task_dir)
    try:
        state = requests.get(BASE + "/admin/user_state/u1",
                             headers={"X-API-Key": "mysqlkey"})
        assert state.status_code == 200, state.text
        s = _login("u1")
        body = s.get(BASE + "/get_annotations", params={"instance_id": "i0"}).json()
        assert body["label_values"] == {"ok": {"good": "good"}, "note": {"text_box": "0"}}
        spans = s.get(BASE + "/api/spans/i0").json()["spans"]
        assert [(sp["id"], sp["text"], sp.get("target_field")) for sp in spans] == \
            [("sp1", "TARGET", "text")]
        # The item has its one annotator, so a second user is not given it.
        s2 = _login("u2")
        assert s2.get(BASE + "/api/current_instance").json().get("instance_id") != "i0"
    finally:
        _stop(proc)


def test_a_stranger_cannot_register_as_an_annotator_after_a_restart():
    """Registration refuses a name that already has annotations when the roster
    (user_config.json) has been lost, for example when a study is moved without
    it. It decided that by looking for the name's user_state.json, which MySQL
    never writes."""
    task_dir = _task_dir("tg2_mysql_takeover", True)
    proc = _start(task_dir)
    try:
        s = _login("owner", "secret1")
        r = s.post(BASE + "/updateinstance", json={
            "instance_id": "i0", "annotations": {"ok:good": "good"}})
        assert r.status_code == 200, r.text
    finally:
        _stop(proc)

    os.remove(os.path.join(task_dir, "user_config.json"))
    proc = _start(task_dir)
    try:
        stranger = _login("owner", "other")
        body = stranger.get(BASE + "/get_annotations", params={"instance_id": "i0"})
        assert body.status_code != 200 or not body.json().get("label_values"), body.text
        state = requests.get(BASE + "/admin/user_state/owner",
                             headers={"X-API-Key": "mysqlkey"}).json()
        assert "i0" in json.dumps(state)
    finally:
        _stop(proc)


def test_exports_read_a_mysql_study():
    """Export, paper mode and auto-export read the saved states. They read only
    user_state.json files, so on a MySQL study every one of them came back
    empty without an error."""
    task_dir = _task_dir("tg2_mysql_export", False)
    proc = _start(task_dir)
    try:
        s = _login("exporter")
        r = s.post(BASE + "/updateinstance", json={
            "instance_id": "i1", "annotations": {"ok:bad": "bad"}})
        assert r.status_code == 200, r.text
        r = requests.post(BASE + "/admin/api/export", json={"format": "jsonl"},
                          headers={"X-API-Key": "mysqlkey"})
        assert r.status_code == 200, r.text
        written = r.json()["files_written"]
        assert written, r.json()
        exported = "".join(open(p).read() for p in written)
        assert "exporter" in exported and "bad" in exported
    finally:
        _stop(proc)

    from potato.export.cli import build_export_context
    from potato.paper.collect import collect_project
    config_path = os.path.join(task_dir, "config.yaml")
    rows = build_export_context(config_path).annotations
    assert [(a["user_id"], a["instance_id"]) for a in rows] == [("exporter", "i1")]
    project = collect_project(config_path)
    assert project.annotators == ["exporter"]


def test_the_documented_password_variable_is_substituted():
    """The docs write ``password: ${POTATO_DB_PASSWORD}``. The server expands it;
    the offline export reads the YAML itself and has to expand it too, or the
    literal string is sent as the password."""
    import mysql.connector
    db = _db()
    conn = mysql.connector.connect(host=db["host"], port=int(db["port"]), user=db["user"],
                                   password=db["pw"], database=db["db"])
    cur = conn.cursor()
    cur.execute("DROP USER IF EXISTS 'potato_env'@'%'")
    cur.execute("CREATE USER 'potato_env'@'%' IDENTIFIED BY 'env-secret'")
    cur.execute(f"GRANT ALL ON {db['db']}.* TO 'potato_env'@'%'")
    conn.commit()
    conn.close()

    task_dir = _task_dir("tg2_mysql_env", False)
    path = os.path.join(task_dir, "config.yaml")
    text = open(path).read()
    text = re.sub(r"username: [^,]+, password: \"[^\"]*\"",
                  'username: potato_env, password: "${POTATO_TEST_DB_PW}"', text)
    open(path, "w").write(text)
    os.environ["POTATO_TEST_DB_PW"] = "env-secret"
    try:
        proc = _start(task_dir)
        try:
            s = _login("envuser")
            r = s.post(BASE + "/updateinstance", json={
                "instance_id": "i2", "annotations": {"ok:good": "good"}})
            assert r.status_code == 200, r.text
        finally:
            _stop(proc)
        from potato.export.cli import build_export_context
        rows = build_export_context(path).annotations
        assert [a["user_id"] for a in rows] == ["envuser"]
    finally:
        os.environ.pop("POTATO_TEST_DB_PW", None)


# ---------------------------------------------------------------------------
# Tools that used to read only user_state.json files
# ---------------------------------------------------------------------------

def _config(task_dir):
    import yaml
    with open(os.path.join(task_dir, "config.yaml")) as f:
        config = yaml.safe_load(f)
    config["output_annotation_dir"] = os.path.join(task_dir, "annotation_output")
    config["task_dir"] = task_dir
    return config


def _seed_file_state(task_dir, user, labels):
    """A user_state.json as the file backend or `potato import` writes it."""
    d = os.path.join(task_dir, "annotation_output", user)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "user_state.json"), "w") as f:
        json.dump({"user_id": user, "instance_id_ordering": ["i0"],
                   "instance_id_to_label_to_value": {
                       "i0": [[{"schema": "ok", "name": n}, n] for n in labels]}}, f)
    from potato.annotation_history import AnnotationHistoryManager
    action = AnnotationHistoryManager.create_action(
        user_id=user, instance_id="i0", action_type="add_label", schema_name="ok",
        label_name=labels[0], old_value=None, new_value=labels[0])
    with open(os.path.join(d, "annotation_history.jsonl"), "w") as f:
        f.write(json.dumps(action.to_dict(), default=str) + "\n")


def _stored(user):
    import mysql.connector
    db = _db()
    conn = mysql.connector.connect(host=db["host"], port=int(db["port"]), user=db["user"],
                                   password=db["pw"], database=db["db"])
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM user_state_documents WHERE user_id=%s", (user,))
    row = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM annotation_history_log WHERE user_id=%s", (user,))
    history = cur.fetchone()[0]
    conn.close()
    return (json.loads(row[0]) if row else None), history


def test_file_annotators_are_imported_into_mysql_at_boot():
    """A file study switched to MySQL, or one made by `potato import
    --seed-user`, kept its work in files the MySQL backend never read."""
    task_dir = _task_dir("tg2_mysql_import", False)
    _seed_file_state(task_dir, "seeded", ["good"])
    proc = _start(task_dir)
    try:
        state = requests.get(BASE + "/admin/user_state/seeded",
                             headers={"X-API-Key": "mysqlkey"})
        assert state.status_code == 200, state.text
    finally:
        _stop(proc)
    stored, history = _stored("seeded")
    assert stored["instance_id_to_label_to_value"]["i0"] == [[{"schema": "ok", "name": "good"}, "good"]]
    assert history == 1


def test_repair_reads_and_writes_mysql():
    from potato.repair_cli import repair_output_dir
    task_dir = _task_dir("tg2_mysql_repair", False)
    _seed_file_state(task_dir, "dup", ["good", "bad"])
    proc = _start(task_dir)       # imports the file state into the database
    _stop(proc)
    import shutil
    shutil.rmtree(os.path.join(task_dir, "annotation_output", "dup"))

    config = _config(task_dir)
    summary = repair_output_dir(config["output_annotation_dir"], {"ok"}, apply=True,
                                config=config)
    assert summary["users_scanned"] == 1 and summary["collapses"] == 1, summary
    stored, _ = _stored("dup")
    assert len(stored["instance_id_to_label_to_value"]["i0"]) == 1
    assert os.path.isfile(os.path.join(task_dir, "annotation_output", "dup",
                                       "user_state.json.bak"))


def test_the_data_archive_carries_mysql_annotators():
    """`potato deploy pull` over HTTPS gets the server's archive. On MySQL it
    held no annotator, and pull reported files but no annotators."""
    import io
    import tarfile
    task_dir = _task_dir("tg2_mysql_archive", False)
    proc = _start(task_dir)
    try:
        s = _login("puller")
        assert s.post(BASE + "/updateinstance", json={
            "instance_id": "i0", "annotations": {"ok:good": "good"}}).status_code == 200
        r = requests.get(BASE + "/admin/api/data/archive", headers={"X-API-Key": "mysqlkey"})
        assert r.status_code == 200
    finally:
        _stop(proc)
    names = tarfile.open(fileobj=io.BytesIO(r.content)).getnames()
    assert "annotation_output/puller/user_state.json" in names
    assert "annotation_output/puller/annotation_history.jsonl" in names

    from potato.deploy.pull import verify_pull
    dest = os.path.join(task_dir, "pulled")
    tarfile.open(fileobj=io.BytesIO(r.content)).extractall(dest)
    assert verify_pull(dest).annotators == 1


def test_backup_snapshots_and_restores_mysql_annotators():
    from potato.server_utils import backup
    task_dir = _task_dir("tg2_mysql_backup", False)
    proc = _start(task_dir)
    try:
        s = _login("backedup")
        assert s.post(BASE + "/updateinstance", json={
            "instance_id": "i1", "annotations": {"ok:bad": "bad"}}).status_code == 200
    finally:
        _stop(proc)

    config = _config(task_dir)
    # A study with annotators in the database is not empty, so a restart does
    # not restore the backup over its live files.
    assert not backup.output_is_empty(config)
    backup.snapshot_databases(config)
    snap = os.path.join(backup.snapshot_dir(config), "mysql", "backedup")
    assert os.path.isfile(os.path.join(snap, "user_state.json"))

    # The host comes back with an empty database and the restored snapshot.
    _drop_tables()
    assert backup.output_is_empty(config)
    backup._install_restored_mysql_states(config)
    proc = _start(task_dir)
    try:
        state = requests.get(BASE + "/admin/user_state/backedup",
                             headers={"X-API-Key": "mysqlkey"})
        assert state.status_code == 200, state.text
    finally:
        _stop(proc)
    stored, _ = _stored("backedup")
    assert stored["instance_id_to_label_to_value"]["i1"]


def test_filter_by_prior_annotation_reads_a_mysql_task():
    from potato.filter_by_annotation import load_annotations_from_dir
    task_dir = _task_dir("tg2_mysql_filter", False)
    proc = _start(task_dir)
    try:
        s = _login("triager")
        assert s.post(BASE + "/updateinstance", json={
            "instance_id": "i2", "annotations": {"ok:good": "good"}}).status_code == 200
    finally:
        _stop(proc)
    config = _config(task_dir)
    found = load_annotations_from_dir(config["output_annotation_dir"],
                                      {"database": config["database"]})
    assert found["i2"]["ok"] == {"triager": {"good"}}
