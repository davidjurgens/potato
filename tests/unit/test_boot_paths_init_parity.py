"""Both boot paths start the same subsystems, and SSO works in a container.

`potato start` boots through run_server(); every container, and so every
`potato deploy` target, boots gunicorn on the create_app(config) factory. Ten
config-gated subsystems used to be started only in run_server(). Under gunicorn
chat answered 404 "Chat support is not enabled" beneath a sidebar that still
rendered, and an OAuth task logged "OAuth not initialized" and 404'd its
sign-in route.

The boots run in a subprocess: the state managers and the authenticator are
process-wide singletons that only initialise once, so an in-process boot
would test whichever config got there first.
"""

import ast
import inspect
import json
import os
import subprocess
import sys

import pytest
import yaml

from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reachable_init_calls(function_name):
    """Names of init_* / _init_* calls reachable from a flask_server function,
    following calls into other module-level functions of flask_server."""
    import potato.flask_server as fs

    tree = ast.parse(inspect.getsource(fs))
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    seen, found = set(), set()

    def walk(name):
        if name in seen or name not in functions:
            return
        seen.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if called:
                    if called.lstrip("_").startswith("init"):
                        found.add(called)
                    walk(called)

    walk(function_name)
    return found


def test_the_factory_starts_everything_potato_start_starts():
    factory = (_reachable_init_calls("create_app")
               | _reachable_init_calls("_initialize_from_config"))
    missing = _reachable_init_calls("run_server") - factory
    assert not missing, (
        f"run_server() starts {sorted(missing)} but the create_app factory "
        "(gunicorn, every container and deploy) does not. Put the call in "
        "_init_optional_subsystems() or create_app().")


def _write_config(name, extra):
    test_dir = create_test_directory(name)
    data = os.path.join(test_dir, "data.jsonl")
    with open(data, "w") as f:
        for i in range(2):
            f.write(json.dumps({"id": str(i), "text": f"item {i}"}) + "\n")
    config = {
        "annotation_task_name": name,
        "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "out"),
        "data_files": [data],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                "description": "d", "labels": ["a", "b"]}],
        "alert_time_each_instance": 0,
    }
    config.update(extra)
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    return path


def _boot_factory_and_run(config_path, body):
    """Boot create_app(config_path) in a fresh interpreter, run *body* with
    `app`, `client` and `out` in scope, and return `out`."""
    code = (
        "import json, potato.routes\n"
        "from potato.flask_server import create_app\n"
        f"app = create_app({config_path!r})\n"
        "client = app.test_client()\n"
        "out = {}\n"
        + body +
        "\nprint('RESULT' + json.dumps(out))\n")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                            capture_output=True, text=True, timeout=300)
    lines = [l for l in result.stdout.splitlines() if l.startswith("RESULT")]
    assert lines, result.stdout[-2000:] + result.stderr[-4000:]
    return json.loads(lines[-1][len("RESULT"):])


def test_chat_starts_under_the_factory():
    path = _write_config("boot_parity_chat", {
        "chat_support": {"enabled": True, "endpoint_type": "ollama",
                         "ai_config": {"model": "llama3.2"}}})
    out = _boot_factory_and_run(path, (
        "from potato.chat_manager import get_chat_manager\n"
        "out['chat'] = get_chat_manager() is not None\n"))
    assert out["chat"], "chat_support is enabled but the factory never started it"


@pytest.fixture(scope="module")
def sso_only_task():
    pytest.importorskip("authlib")
    path = _write_config("boot_parity_sso", {
        "authentication": {"method": "oauth", "providers": {
            "google": {"client_id": "id", "client_secret": "secret"}}},
        "user_config": {"allow_all_users": True},
    })
    return _boot_factory_and_run(path, (
        "r = client.get('/auth/login/google')\n"
        "out['login_status'] = r.status_code\n"
        "out['login_location'] = r.headers.get('Location', '')\n"
        "home = client.get('/').get_data(as_text=True)\n"
        "out['home_has_sso'] = 'Sign in with Google' in home\n"
        "out['home_has_password'] = 'name=\"pass\"' in home\n"
        "r = client.post('/register', data={'email': 'eve', 'pass': 'pw'})\n"
        "out['register_status'] = r.status_code\n"
        "out['register_annotate'] = client.get('/annotate').status_code\n"
        "from potato.authentication import UserAuthenticator\n"
        "UserAuthenticator.get_instance().add_user('alice@example.org', None,\n"
        "    oauth_provider='google', oauth_profile={})\n"
        "c2 = app.test_client()\n"
        "c2.post('/auth', data={'email': 'alice@example.org', 'pass': 'guess'})\n"
        "with c2.session_transaction() as s:\n"
        "    out['impersonated'] = s.get('username')\n"))


class TestSsoOnlyTask:
    def test_the_sign_in_route_redirects_to_the_provider(self, sso_only_task):
        assert sso_only_task["login_status"] == 302
        assert "accounts.google.com" in sso_only_task["login_location"]

    def test_the_landing_page_offers_sso_and_no_password_form(self, sso_only_task):
        assert sso_only_task["home_has_sso"]
        assert not sso_only_task["home_has_password"]

    def test_password_registration_is_refused(self, sso_only_task):
        assert sso_only_task["register_status"] == 403
        assert sso_only_task["register_annotate"] != 200

    def test_a_password_cannot_sign_in_as_an_sso_user(self, sso_only_task):
        """OAuthBackend.authenticate returned True for any username a provider
        had registered, whatever the password."""
        assert sso_only_task["impersonated"] is None


class TestLocalLoginAlongsideSso:
    """allow_local_login: true keeps working, with real password checks."""

    def _backend(self):
        pytest.importorskip("authlib")
        from potato.auth_backends.oauth_backend import OAuthBackend
        return OAuthBackend({"providers": {"google": {"client_id": "i"}},
                             "allow_local_login": True})

    def test_a_local_account_needs_its_password(self):
        backend = self._backend()
        assert backend.add_user("bob", "right") == "Success"
        assert backend.authenticate("bob", "right")
        assert not backend.authenticate("bob", "wrong")

    def test_a_local_account_cannot_take_an_sso_name(self):
        backend = self._backend()
        backend.add_user("alice@example.org", None, oauth_provider="google")
        assert backend.add_user("alice@example.org", "pw") == "Duplicate user"
        assert not backend.authenticate("alice@example.org", "pw")
