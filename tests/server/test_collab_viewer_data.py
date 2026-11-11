"""Viewer data routes on a live-session page.

The time-series and spectrum viewers fetch their samples from routes that
check the annotator was assigned the item. In a session the item is assigned
to the team user, so a member's page got 403 and drew nothing. A request that
names the session (the ``X-Potato-Collab`` header collab.js adds) now gets
the data when the member is in that session and the item is one of its
items; everyone else is still refused.
"""

import os
import shutil

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import create_test_directory

# Two live servers answer with one project's data; fail rather than trust it.
pytestmark = pytest.mark.filterwarnings("error:FlaskTestServer on port:RuntimeWarning")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _session_copy(example, name, items):
    work = os.path.join(create_test_directory(f"collab_viewer_{name}"), "example")
    shutil.copytree(os.path.join(REPO, example), work, ignore=shutil.ignore_patterns(
        "annotation_output", "project.sqlite*", "test_config_port_*"))
    path = os.path.join(work, "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    config["user_config"] = {"allow_all_users": True, "users": []}
    config["require_password"] = False
    # A stranger gets one item, so some session item is never theirs.
    config["max_annotations_per_user"] = 1
    config["collab"] = {"enabled": True, "default_mode": "free", "teams": [
        {"id": "lab", "members": ["ana", "ben"], "leader": "ana", "items": items}]}
    with open(path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    return path


def _server(example, name, items, port):
    server = FlaskTestServer(port=port, config_file=_session_copy(example, name, items))
    if not server.start():
        pytest.fail(f"Failed to start the {name} server")
    return server


def _login(server, name):
    s = requests.Session()
    s.post(f"{server.base_url}/auth", data={"email": name, "pass": ""}, timeout=5)
    return s


SESSION = {"X-Potato-Collab": "LAB"}


def _not_theirs(session, urls):
    """The URLs this annotator is refused without naming the session."""
    refused = [u for u in urls if session.get(u, timeout=10).status_code == 403]
    assert refused, "every one of these items is assigned to them"
    return refused


# One server at a time: in-process test servers share Potato's singletons, so
# while two are up both ports answer with the later project's data, and a 403
# could come from the wrong project. Each class stops its server before the
# next class starts one.
class TestSignals:
    @pytest.fixture(scope="class")
    def signals(self):
        server = _server("examples/advanced/time-series-intervals", "signals",
                         ["psg-01", "accel-01"], 9096)
        yield server
        server.stop()

    def test_a_member_gets_the_signal_of_a_session_item(self, signals):
        ana = _login(signals, "ana")
        url = f"{signals.base_url}/api/signals/window?instance_id=psg-01&field=signal&start=0&end=30&px=200"
        r = ana.get(url, headers=SESSION, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["channels"][0]["name"] == "EEG Fpz-Cz"
        pre = ana.get(f"{signals.base_url}/api/signals/preannotations?instance_id=psg-01"
                      "&field=signal&schema=segments", headers=SESSION, timeout=10)
        assert pre.status_code == 200, pre.text

    def test_signal_refusals_stand_outside_the_session(self, signals):
        url = f"{signals.base_url}/api/signals/window?field=signal&start=0&end=30&px=200&instance_id="
        ana, carl = _login(signals, "ana"), _login(signals, "carl")
        # The refusals below are this project's: the session item is served.
        assert ana.get(url + "psg-01", headers=SESSION, timeout=10).status_code == 200
        # Without naming the session the item is not hers.
        assert ana.get(url + "psg-01", timeout=10).status_code == 403
        # Naming a session he is not in does not help a stranger.
        for u in _not_theirs(carl, [url + "psg-01", url + "accel-01"]):
            assert carl.get(u, headers=SESSION, timeout=10).status_code == 403


class TestSpectra:
    @pytest.fixture(scope="class")
    def spectra(self):
        server = _server("examples/advanced/spectrum-peak-picking", "spectra",
                         ["nmr_ethyl_acetate"], 9097)
        yield server
        server.stop()

    def test_a_member_gets_a_spectrum_range_of_a_session_item(self, spectra):
        url = f"{spectra.base_url}/api/spectrum/range?field=spectrum&x0=0&x1=5&instance_id="
        ana = _login(spectra, "ana")
        r = ana.get(url + "nmr_ethyl_acetate", headers=SESSION, timeout=10)
        assert r.status_code == 200, r.text
        assert len(r.json()["x"]) > 0
        assert ana.get(url + "nmr_ethyl_acetate", timeout=10).status_code == 403
        # Naming the session does not open an item outside it.
        for u in _not_theirs(ana, [url + "nmr_ethanol", url + "ir_ethyl_benzoate"]):
            assert ana.get(u, headers=SESSION, timeout=10).status_code == 403
