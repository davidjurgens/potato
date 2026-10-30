"""Training backends: the agent protocol, the ssh launcher, and devices.

The end-to-end tests here run the real sequence -- preflight, code copy, a
separate agent process, the HTTP protocol, predictions travelling back, and
artifacts fetched -- with one substitution: the launcher's ssh transport is
replaced by one that runs the same commands on this machine. A protocol is
only real once two processes have spoken it, so the agent is always a
subprocess here, never a function call.
"""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from potato.training import store
from potato.training.backends import (BackendConfig, load_backends,
                                      validate_backends_config)
from potato.training.launchers import (LaunchError, choose_gpus, code_digest,
                                       check_backend)
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.unit.test_training_subprocess import _project


# ------------------------------------------------------------- fixtures

@pytest.fixture
def project():
    """A project with labelled items, a manager, and a live protocol server."""
    from flask import Flask
    from werkzeug.serving import make_server

    from potato.training import manager as manager_module
    from potato.training import protocol
    from potato.training.manager import TrainingManager

    tmp = create_test_directory("training_backends_%d" % os.getpid())
    config, context = _project(tmp)

    app = Flask("training-backends-test")
    app.register_blueprint(protocol.training_api_bp)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    config["port"] = server.server_port
    config["model_training"] = {
        "enabled": True,
        "grace_seconds": 3,
        "backends": {
            "here": {"type": "ssh", "host": "localhost",
                     "python": sys.executable, "gpus": "none",
                     "remote_dir": os.path.join(tmp, "remote"),
                     "_transport": "local"},
            "labgpu": {"type": "agent", "heartbeat_timeout_s": 60},
        },
    }
    manager = TrainingManager(config)
    manager._context_from_live_state = lambda: context

    saved = (manager_module._TRAINING_MANAGER, protocol._config)
    manager_module._TRAINING_MANAGER = manager
    protocol._config = lambda: config
    try:
        yield type("Project", (), {
            "tmp": tmp, "config": config, "manager": manager,
            "url": "http://127.0.0.1:%d" % server.server_port})
    finally:
        manager.shutdown()
        manager_module._TRAINING_MANAGER, protocol._config = saved
        server.shutdown()
        cleanup_test_directory(tmp)


def _wait(manager, timeout=240):
    deadline = time.time() + timeout
    while manager.is_running() and time.time() < deadline:
        time.sleep(0.2)
    return manager.status()


def _agent(url, token, backend, workdir, extra=()):
    env = dict(os.environ, POTATO_TRAINING_TOKEN=token)
    return subprocess.Popen(
        [sys.executable, "-m", "potato.training.agent", "--server", url,
         "--backend", backend, "--workdir", workdir, "--once"] + list(extra),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


# ---------------------------------------------------------------- config

class TestBackendConfig:
    def test_local_is_always_present(self):
        assert load_backends({})["local"].type == "local"

    def test_an_ssh_backend_needs_a_host(self):
        problems = validate_backends_config(
            {"model_training": {"backends": {"g": {"type": "ssh"}}}})
        assert any("host is required" in p for p in problems)

    def test_a_misspelt_key_is_reported(self):
        problems = validate_backends_config({"model_training": {"backends": {
            "g": {"type": "ssh", "host": "h", "pyhton": "/x"}}}})
        assert any("pyhton" in p for p in problems)

    def test_an_undefined_default_backend_is_reported(self):
        problems = validate_backends_config(
            {"model_training": {"backend": "nowhere"}})
        assert any("nowhere" in p for p in problems)

    def test_local_cannot_be_redefined_as_remote(self):
        problems = validate_backends_config({"model_training": {"backends": {
            "local": {"type": "ssh", "host": "h"}}}})
        assert any("reserved" in p for p in problems)

    def test_a_valid_config_has_no_problems(self):
        assert validate_backends_config({"model_training": {
            "backend": "g", "backends": {"g": {
                "type": "ssh", "host": "h", "gpus": "0,2",
                "env": {"A": "1"}, "packages": ["x"]}}}}) == []

    def test_starting_on_an_unknown_backend_is_refused(self, project):
        outcome = project.manager.start_run("sklearn-text", ["sentiment"],
                                            backend="nowhere")
        assert outcome["started"] is False
        assert "nowhere" in outcome["error"]


class TestGpuChoice:
    GPUS = [{"index": 0, "name": "A5000", "free_mb": 3000, "total_mb": 24000},
            {"index": 1, "name": "A5000", "free_mb": 20000, "total_mb": 24000},
            {"index": 2, "name": "TITAN V", "free_mb": 9000,
             "total_mb": 12000}]

    def test_auto_takes_the_most_free_memory(self):
        visible, text = choose_gpus("auto", self.GPUS, 2000)
        assert visible == "1"
        assert "19.5 GB free" in text

    def test_auto_refuses_when_every_card_is_full(self):
        with pytest.raises(LaunchError, match="No GPU has 30000 MB free"):
            choose_gpus("auto", self.GPUS, 30000)

    def test_auto_on_a_host_without_gpus_uses_the_cpu(self):
        assert choose_gpus("auto", [], 2000)[0] == ""

    def test_a_pinned_list_is_kept(self):
        assert choose_gpus("2,0", self.GPUS, 2000)[0] == "2,0"

    def test_a_pinned_gpu_that_does_not_exist_is_refused(self):
        with pytest.raises(LaunchError, match="GPU 7 not found"):
            choose_gpus("7", self.GPUS, 2000)

    def test_none_hides_every_gpu(self):
        assert choose_gpus("none", self.GPUS, 2000)[0] == ""


class TestDevices:
    def test_without_torch_everything_is_the_cpu(self, monkeypatch):
        from potato.training import devices
        monkeypatch.setattr(devices, "_torch", lambda: None)
        warnings = []
        assert devices.resolve_device(
            "cuda", lambda level, msg: warnings.append(msg)) == "cpu"
        assert warnings and "torch is not installed" in warnings[0]

    def test_a_missing_cuda_falls_back_with_a_warning(self, monkeypatch):
        from potato.training import devices

        class Torch:
            class cuda:
                @staticmethod
                def is_available():
                    return False

            class backends:
                class mps:
                    @staticmethod
                    def is_available():
                        return True

        monkeypatch.setattr(devices, "_torch", lambda: Torch)
        warnings = []
        assert devices.resolve_device(
            "cuda:1", lambda level, msg: warnings.append(msg)) == "mps"
        assert "CUDA is not available" in warnings[0]
        assert devices.resolve_device("auto") == "mps"

    def test_cpu_never_imports_torch(self, monkeypatch):
        from potato.training import devices

        def boom():
            raise AssertionError("torch was consulted for an explicit cpu")
        monkeypatch.setattr(devices, "_torch", boom)
        assert devices.resolve_device("cpu") == "cpu"

    def test_a_reloaded_text_encoder_is_not_pickled_with_the_model(self):
        """A model fitted on a CUDA host has to load on a laptop."""
        import pickle

        from potato.active_learning_manager import SentenceTransformerVectorizer

        vectorizer = SentenceTransformerVectorizer(device="cuda")
        vectorizer._model = object()  # stands in for a loaded encoder
        restored = pickle.loads(pickle.dumps(vectorizer))
        assert restored._model is None
        assert restored.device == "cuda"


class TestCodeShipping:
    def test_the_digest_changes_when_the_code_does(self, tmp_path):
        package = tmp_path / "potato"
        package.mkdir()
        (package / "a.py").write_text("x = 1\n")
        before = code_digest(str(package))
        (package / "a.py").write_text("x = 2\n")
        assert code_digest(str(package)) != before

    def test_bytecode_does_not_change_the_digest(self, tmp_path):
        package = tmp_path / "potato"
        (package / "__pycache__").mkdir(parents=True)
        (package / "a.py").write_text("x = 1\n")
        before = code_digest(str(package))
        (package / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\0")
        assert code_digest(str(package)) == before


# --------------------------------------------------------------- protocol

class TestProtocolAuth:
    def test_no_token_is_401(self, project):
        import requests
        response = requests.get(project.url + "/api/training/jobs/next")
        assert response.status_code == 401

    def test_a_wrong_token_is_401(self, project):
        import requests
        store.register_backend(project.config, "labgpu")
        response = requests.get(project.url + "/api/training/jobs/next",
                                headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401

    def test_an_idle_poll_is_204(self, project):
        import requests
        token = store.register_backend(project.config, "labgpu")
        response = requests.get(project.url + "/api/training/jobs/next",
                                headers={"Authorization": "Bearer " + token})
        assert response.status_code == 204

    def test_registering_needs_the_admin_key(self, project):
        import requests
        response = requests.post(
            project.url + "/api/training/backends/register",
            json={"name": "labgpu"})
        assert response.status_code == 401

    def test_registering_again_rotates_the_token(self, project):
        first = store.register_backend(project.config, "labgpu")
        second = store.register_backend(project.config, "labgpu")
        assert store.backend_for_token(project.config, first) is None
        assert store.backend_for_token(project.config, second) == "labgpu"

    def test_an_agent_cannot_see_another_backends_job(self, project):
        """A job for `here` is invisible to a token for `labgpu`."""
        import requests

        from potato.training.manager import ExternalJob, _EventSink

        token = store.register_backend(project.config, "labgpu")
        run_dir = os.path.join(project.tmp, "fake-run")
        os.makedirs(run_dir)
        job = ExternalJob(run_id="r-other", backend="here",
                          backend_type="ssh", spec={}, run_dir=run_dir,
                          sink=_EventSink(project.manager,
                                          os.path.join(run_dir, "e.jsonl")),
                          state="claimed")
        project.manager._job = job
        try:
            headers = {"Authorization": "Bearer " + token}
            for method, path in (("GET", "/jobs/r-other"),
                                 ("GET", "/jobs/r-other/bundle"),
                                 ("POST", "/jobs/r-other/complete")):
                response = requests.request(
                    method, project.url + "/api/training" + path,
                    headers=headers, json={})
                assert response.status_code == 404, path
            assert job.completion is None
        finally:
            project.manager._job = None
            job.sink.close()

    def test_a_launch_token_works_only_for_its_own_job(self, project):
        import hashlib

        import requests

        from potato.training.manager import ExternalJob, _EventSink

        run_dir = os.path.join(project.tmp, "fake-run2")
        os.makedirs(run_dir)
        job = ExternalJob(
            run_id="r-mine", backend="here", backend_type="ssh", spec={},
            run_dir=run_dir, state="claimed",
            sink=_EventSink(project.manager, os.path.join(run_dir, "e.jsonl")),
            launch_token_digest=hashlib.sha256(b"launch-secret").hexdigest())
        project.manager._job = job
        try:
            headers = {"Authorization": "Bearer launch-secret"}
            ok = requests.get(project.url + "/api/training/jobs/r-mine",
                              headers=headers)
            assert ok.status_code == 200
            other = requests.get(project.url + "/api/training/jobs/r-else",
                                 headers=headers)
            assert other.status_code == 404
            # And it is not a registered backend's token.
            beat = requests.post(
                project.url + "/api/training/backends/here/heartbeat",
                headers=headers)
            assert beat.status_code == 403
        finally:
            project.manager._job = None
            job.sink.close()


# ------------------------------------------------------------ end to end

class TestSshLauncherEndToEnd:
    def test_a_run_on_an_ssh_backend_succeeds_and_writes_back(self, project):
        manager = project.manager
        outcome = manager.start_run("sklearn-text", ["sentiment"],
                                    params={"min_instances": 4},
                                    backend="here")
        assert outcome["started"], outcome
        status = _wait(manager)
        assert status["state"] == "success", status

        run = store.load_run(project.config, outcome["run_id"])
        assert run.backend == "here"
        assert run.status == "success"
        assert run.model_version.startswith("sklearn-text-sentiment-")
        assert run.host.startswith("localhost")

        # Predictions came back over the protocol and were ingested.
        assert status["writeback"]["n_read"] > 0
        assert store.load_predictions(project.config, run_id=run.run_id)

        # Artifacts were fetched back, so the run looks like a local one.
        artifacts = os.path.join(manager.run_dir(run.run_id), "artifacts")
        assert os.path.isfile(os.path.join(artifacts, "model.pkl"))
        assert os.path.isfile(os.path.join(artifacts, "model_card.json"))

        # The events the remote worker emitted reached the run's event log.
        with open(os.path.join(manager.run_dir(run.run_id),
                               "events.jsonl")) as fh:
            kinds = {json.loads(line)["event"] for line in fh}
        assert {"status", "result", "log"} <= kinds

        # The remote job directory was cleaned up; the code cache was not.
        remote = project.config["model_training"]["backends"]["here"][
            "remote_dir"]
        assert os.listdir(os.path.join(remote, "jobs")) == []
        code = os.path.join(remote, "code", code_digest())
        assert os.path.isfile(os.path.join(code, ".complete"))
        assert os.path.isfile(os.path.join(code, "potato", "training",
                                           "agent.py"))

    def test_a_bad_interpreter_is_reported_not_hung(self, project):
        project.config["model_training"]["backends"]["here"]["python"] = \
            "/no/such/python3"
        outcome = project.manager.start_run(
            "sklearn-text", ["sentiment"], params={"min_instances": 4},
            backend="here")
        status = _wait(project.manager, timeout=60)
        assert status["state"] == "error"
        run = store.load_run(project.config, outcome["run_id"])
        assert run.error_code == "launch_failed"
        assert "/no/such/python3" in run.error

    def test_cancelling_reaches_the_remote_worker(self, project):
        """Cancel is delivered in the /progress response, and the run ends
        as cancelled rather than waiting out the fit."""
        slow_dir = os.path.join(project.tmp, "slowmod")
        os.makedirs(slow_dir)
        with open(os.path.join(slow_dir, "slowclf.py"), "w") as fh:
            fh.write(textwrap.dedent('''
                import signal, sys, time
                from sklearn.linear_model import LogisticRegression

                class SlowClassifier(LogisticRegression):
                    def fit(self, X, y, **kw):
                        # Stands in for a trainer that honours SIGTERM.
                        signal.signal(signal.SIGTERM,
                                      lambda *a: sys.exit(4))
                        time.sleep(120)
                        return super().fit(X, y, **kw)
            '''))
        project.config["model_training"]["backends"]["here"]["env"] = {
            "PYTHONPATH": slow_dir}

        manager = project.manager
        outcome = manager.start_run(
            "sklearn-text", ["sentiment"], backend="here",
            params={"min_instances": 4, "calibrate": False,
                    "classifier": "slowclf.SlowClassifier"})
        assert outcome["started"]
        deadline = time.time() + 120
        while time.time() < deadline:
            if manager.status().get("step") == "fitting":
                break
            time.sleep(0.2)
        else:
            pytest.fail("the remote fit never started: %s" % manager.status())

        started = time.time()
        assert manager.cancel(outcome["run_id"])["cancelled"]
        status = _wait(manager, timeout=60)
        assert status["state"] == "cancelled", status
        assert time.time() - started < 30


class TestManualAgentEndToEnd:
    def test_a_polling_agent_claims_and_runs_the_job(self, project):
        token = store.register_backend(project.config, "labgpu")
        agent = _agent(project.url, token, "labgpu",
                       os.path.join(project.tmp, "agent-work"))
        try:
            outcome = project.manager.start_run(
                "sklearn-text", ["sentiment"], params={"min_instances": 4},
                backend="labgpu")
            assert outcome["started"]
            status = _wait(project.manager)
            assert status["state"] == "success", status
            assert agent.wait(timeout=60) == 0
        finally:
            if agent.poll() is None:
                agent.kill()
            _, stderr = agent.communicate()

        run = store.load_run(project.config, outcome["run_id"])
        assert run.backend == "labgpu" and run.status == "success"
        import platform
        assert run.host == platform.node()  # the agent's, not the server's
        # Audit 98 D4: where the agent left the model was dropped, though the
        # docs point to it.
        assert run.artifact_uri == "%s:%s" % (platform.node(), os.path.join(
            project.tmp, "agent-work", "jobs", run.run_id, "artifacts"))
        assert store.load_run(project.config, run.run_id).artifact_uri
        assert store.load_predictions(project.config, run_id=run.run_id)
        assert "running job" in stderr

    def test_a_queued_job_with_no_agent_times_out(self, project):
        project.config["model_training"]["backends"]["labgpu"][
            "queue_timeout_s"] = 2
        outcome = project.manager.start_run(
            "sklearn-text", ["sentiment"], params={"min_instances": 4},
            backend="labgpu")
        status = _wait(project.manager, timeout=30)
        assert status["state"] == "error"
        run = store.load_run(project.config, outcome["run_id"])
        assert run.error_code == "no_agent"
        assert "potato training agent" in run.error

    def test_cancelling_a_queued_job_needs_no_agent(self, project):
        outcome = project.manager.start_run(
            "sklearn-text", ["sentiment"], params={"min_instances": 4},
            backend="labgpu")
        deadline = time.time() + 30
        while project.manager.status()["state"] != "queued" \
                and time.time() < deadline:
            time.sleep(0.1)
        assert project.manager.cancel()["cancelled"]
        assert _wait(project.manager, timeout=30)["state"] == "cancelled"


class TestCheck:
    def test_check_reports_python_and_no_gpus(self):
        backend = BackendConfig.from_dict("here", {
            "type": "ssh", "host": "localhost", "python": sys.executable,
            "gpus": "auto", "_transport": "local",
            "remote_dir": create_test_directory("training_check")})
        try:
            report = check_backend(backend)
            assert report["ok"], report
            assert report["python"] == "%d.%d.%d" % sys.version_info[:3]
        finally:
            cleanup_test_directory(backend.remote_dir)

    def test_check_names_a_missing_interpreter(self):
        backend = BackendConfig.from_dict("here", {
            "type": "ssh", "host": "localhost", "python": "/no/python",
            "_transport": "local"})
        report = check_backend(backend)
        assert report["ok"] is False
        assert "/no/python" in report["message"]


class TestArtifactFetch:
    """The copy back from a remote host streams to disk and reports progress.

    It used to read the whole tar into the annotation server's memory, with a
    fixed 15-minute limit; a fine-tuned model is hundreds of megabytes, and
    measured over a home connection the copy runs at under 2 MB/s.
    """

    def _launcher(self, root, steps):
        from potato.training.agent import _job_dir_name
        from potato.training.launchers import SSHLauncher
        backend = BackendConfig.from_dict("here", {
            "type": "ssh", "host": "localhost", "python": sys.executable,
            "_transport": "local"})
        launcher = SSHLauncher(backend, root, step=steps.append)
        launcher.info["root"] = root
        artifacts = os.path.join(root, "jobs", _job_dir_name("r1"), "artifacts")
        os.makedirs(os.path.join(artifacts, "model"))
        with open(os.path.join(artifacts, "model", "weights.bin"), "wb") as fh:
            fh.write(os.urandom(3 * 1024 * 1024))
        with open(os.path.join(artifacts, "model_card.json"), "w") as fh:
            fh.write("{}")
        return launcher

    def test_files_arrive_and_the_page_is_told_how_far_along(self):
        root = create_test_directory("training_fetch")
        try:
            steps = []
            launcher = self._launcher(os.path.join(root, "remote"), steps)
            dest = os.path.join(root, "run", "artifacts")
            names = launcher.fetch_artifacts("r1", dest)
            assert sorted(names) == ["model/weights.bin", "model_card.json"]
            assert os.path.getsize(os.path.join(dest, "model", "weights.bin")) \
                == 3 * 1024 * 1024
            assert any("3.0 MB" in s for s in steps), steps
            # The partial archive is not left behind.
            assert sorted(os.listdir(os.path.join(root, "run"))) == ["artifacts"]
        finally:
            cleanup_test_directory(root)

    def test_a_copy_that_stops_sending_fails_instead_of_hanging(self, monkeypatch):
        from potato.training import launchers
        root = create_test_directory("training_fetch_stall")
        try:
            launcher = self._launcher(os.path.join(root, "remote"), [])
            monkeypatch.setattr(launchers, "_PACK", "import time; time.sleep(30)")
            monkeypatch.setattr(launchers, "FETCH_STALL_S", 2)
            started = time.time()
            with pytest.raises(launchers.LaunchError, match="sent nothing"):
                launcher.fetch_artifacts("r1", os.path.join(root, "run", "a"))
            assert time.time() - started < 15
        finally:
            cleanup_test_directory(root)


class TestGPUsTheRemoteTorchCannotUse:
    """burger has three A5000s (compute 8.6) and a TITAN V (7.0), and its
    torch is built for sm_75 and up. A run put on the TITAN V fails at the
    first CUDA call, so `gpus: auto` must not pick it however free it is."""

    ARCH = ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]
    GPUS = [{"index": 0, "name": "NVIDIA RTX A5000", "free_mb": 4000,
             "total_mb": 24564, "util": 0, "compute_cap": "8.6"},
            {"index": 3, "name": "NVIDIA TITAN V", "free_mb": 12000,
             "total_mb": 12288, "util": 0, "compute_cap": "7.0"}]

    def test_auto_skips_the_unsupported_gpu_even_with_more_free_memory(self):
        visible, text = choose_gpus("auto", self.GPUS, 2000, self.ARCH)
        assert visible == "0"
        assert "A5000" in text

    def test_without_the_arch_list_the_choice_is_by_memory_as_before(self):
        visible, _ = choose_gpus("auto", self.GPUS, 2000, None)
        assert visible == "3"

    def test_pinning_the_unsupported_gpu_is_refused_by_name(self):
        with pytest.raises(LaunchError, match="GPU 3"):
            choose_gpus("3", self.GPUS, 2000, self.ARCH)

    def test_compatibility_rules(self):
        from potato.training.launchers import gpu_supported
        assert gpu_supported("8.9", ["sm_86"]) is True     # same major, later minor
        assert gpu_supported("8.0", ["sm_86"]) is False    # earlier minor
        assert gpu_supported("7.0", self.ARCH) is False
        assert gpu_supported("9.0", ["sm_80", "compute_80"]) is True  # PTX
        assert gpu_supported(None, self.ARCH) is None
