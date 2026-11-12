"""The SLURM backend: the agent stays on the login node, the worker is a
batch job, and its events come back through a file on shared storage.

The end-to-end tests run the whole sequence: preflight, code copy, a
separate agent process, sbatch, the worker, events relayed over the
protocol, predictions and artifacts back. Two substitutions: the ssh
transport runs its commands on this machine (as in
test_training_backends.py), and sbatch/squeue/scancel are
tests/helpers/fake_slurm.py, which runs jobs as background processes.
"""

import json
import os
import signal
import sys
import textwrap
import time

import pytest

from potato.training import store
from potato.training.backends import load_backends, validate_backends_config
from potato.training.slurm import (EXIT_LOST, SlurmJob, batch_script,
                                   parse_time, sbatch_argv)
from tests.helpers.fake_slurm import fake_slurm_bin
from tests.unit.test_training_backends import _wait, project  # noqa: F401


def _slurm_config(**extra):
    entry = {"type": "slurm", "host": "login", "remote_dir": "/shared/x/potato"}
    entry.update(extra)
    return {"model_training": {"backends": {"c": entry}}}


# ------------------------------------------------------------- settings

class TestSettings:
    @pytest.mark.parametrize("text, seconds", [
        ("30", 1800), ("30:15", 1815), ("04:00:00", 14400),
        ("1-00", 86400), ("1-02:30", 95400), ("0-00:00:20", 20)])
    def test_times_parse_as_sbatch_reads_them(self, text, seconds):
        assert parse_time(text) == seconds

    @pytest.mark.parametrize("text", ["", "4h", "0", "1:2:3:4"])
    def test_a_bad_time_is_refused(self, text):
        with pytest.raises(ValueError):
            parse_time(text)

    def test_a_valid_slurm_backend_has_no_problems(self):
        assert validate_backends_config(_slurm_config(
            gres="gpu:A6000:1", time="04:00:00", nice=300,
            job_python="/opt/anaconda/bin/python",
            sbatch_options=["--requeue"], prelude=["module load cuda"])) == []

    @pytest.mark.parametrize("extra, needle", [
        ({"remote_dir": ""}, "remote_dir is required"),
        ({"remote_dir": "/tmp/potato"}, "local to each node"),
        ({"gpus": "0"}, "request GPUs with gres"),
        ({"packages": ["x"]}, "job_python"),
        ({"time": "soon"}, "SLURM time"),
        ({"nice": 5000}, "between 0 and 2000"),
        ({"poll_interval_s": 1}, "at least 10"),
        ({"sbatch_options": ["--output=/elsewhere"]}, "Potato sets itself"),
        ({"pyhton": "x"}, "pyhton is not a setting"),
    ])
    def test_problems_are_named(self, extra, needle):
        problems = validate_backends_config(_slurm_config(**extra))
        assert any(needle in p for p in problems), problems

    def test_a_login_node_is_required(self):
        problems = validate_backends_config(_slurm_config(host=""))
        assert any("host is required for an slurm backend" in p
                   for p in problems)

    def test_the_job_interpreter_defaults_to_the_agents(self):
        backend = load_backends(_slurm_config(python="/x/python3"))["c"]
        assert backend.is_remote and backend.launched
        assert backend.slurm["job_python"] == "/x/python3"
        assert backend.slurm["time"] == "04:00:00"
        assert backend.gpus == "none"


class TestScript:
    def test_paths_with_spaces_survive(self, tmp_path):
        job_dir = tmp_path / "a job dir"
        job_dir.mkdir()
        spec = job_dir / "spec file.json"
        spec.write_text("{}")
        # The script runs the "worker" it names: a stand-in that prints its
        # argument and exits 3.
        fake = tmp_path / "py thon"
        fake.write_text("#!/bin/sh\necho \"$4\"\nexit 3\n")
        fake.chmod(0o755)
        script = job_dir / "job.sh"
        script.write_text(batch_script({"prelude": ["export X=1"]},
                                       str(fake), str(spec)))
        import subprocess
        subprocess.run(["bash", str(script)], cwd=str(job_dir), check=False)
        assert (job_dir / "events.jsonl").read_text().strip() == str(spec)
        assert (job_dir / "exit_code").read_text().strip() == "3"

    def test_sbatch_gets_the_paths_and_the_request(self):
        argv = sbatch_argv({"gres": "gpu:A6000:1", "time": "00:20:00",
                            "nice": 0, "partition": "gpu", "mem": "32G",
                            "cpus_per_task": 4,
                            "sbatch_options": ["--requeue"]},
                           "/s/jobs/r1", "/s/jobs/r1/job.sh", "abcdef123456")
        assert argv[0] == "sbatch" and argv[-1] == "/s/jobs/r1/job.sh"
        for flag in ("--parsable", "--output=/s/jobs/r1/slurm.out",
                     "--chdir=/s/jobs/r1", "--gres=gpu:A6000:1",
                     "--time=00:20:00", "--nice=0", "--partition=gpu",
                     "--mem=32G", "--cpus-per-task=4", "--requeue",
                     "--job-name=potato-train-abcdef12"):
            assert flag in argv, (flag, argv)


# --------------------------------------------------- the job, in-process

class FakeScheduler:
    """Answers sbatch/squeue/scancel/scontrol from a script of states.
    ``final`` is what ``scontrol show job`` says once the job is done:
    ``(JobState, StartTime)``, or None for a job it no longer knows."""

    def __init__(self, states, final=None):
        self.states = list(states)
        self.final = final
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append(list(argv))
        if argv[0] == "sbatch":
            return 0, "4242\n", ""
        if argv[0] == "squeue":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return 0, state + ("\n" if state else ""), ""
        if argv[0] == "scontrol":
            if self.final is None:
                return 1, "", "slurm_load_jobs error: Invalid job id specified"
            return 0, ("JobId=4242 JobName=x JobState=%s Reason=None "
                       "ExitCode=0:15 StartTime=%s\n" % self.final), ""
        return 0, "", ""


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _job(tmp_path, scheduler, clock, logs=None):
    (tmp_path / "spec.json").write_text("{}")
    return SlurmJob({"poll_interval_s": 30}, str(tmp_path),
                    str(tmp_path / "spec.json"), "python", "run-1",
                    env={"CUDA_VISIBLE_DEVICES": "0", "PATH": "/bin"},
                    log=lambda level, msg: (logs if logs is not None
                                            else []).append(msg),
                    runner=scheduler, clock=clock).submit()


def test_queue_changes_are_reported_and_squeue_is_not_hammered(tmp_path):
    logs = []
    clock = Clock()
    scheduler = FakeScheduler(["PENDING|Priority|", "PENDING|Priority|",
                               "RUNNING|None|sushi"])
    job = _job(tmp_path, scheduler, clock, logs)
    assert job.job_id == "4242"
    for _ in range(50):           # many polls inside one interval
        assert job.poll() is None
    assert sum(c[0] == "squeue" for c in scheduler.calls) == 1
    clock.now += 31
    job.poll()
    clock.now += 31
    job.poll()
    assert "SLURM job 4242: PENDING (Priority)" in logs
    assert "SLURM job 4242: RUNNING on sushi" in logs
    # The login node's GPU choice is not carried into the job.
    assert "CUDA_VISIBLE_DEVICES" not in job.env


def test_a_finished_job_is_read_from_its_exit_code(tmp_path):
    clock = Clock()
    job = _job(tmp_path, FakeScheduler(["RUNNING|None|n"]), clock)
    (tmp_path / "events.jsonl").write_text('{"event": "log"}\n{"event": "res')
    (tmp_path / "exit_code").write_text("0\n")
    assert job.poll() == 0
    assert list(job.stdout) == ['{"event": "log"}\n', '{"event": "res']


def test_a_job_the_scheduler_ended_is_lost_with_its_reason(tmp_path):
    clock = Clock()
    job = _job(tmp_path, FakeScheduler(["RUNNING|None|n", ""],
                                       final=("TIMEOUT", "2026-11-02T10:00:00")),
               clock)
    assert job.poll() is None            # running
    clock.now += 31
    # Gone, and scontrol says why: no wait for the exit code.
    assert job.poll() == EXIT_LOST
    assert job.lost_reason == "it reached its time limit"


def test_sigterm_at_the_time_limit_is_not_read_as_a_cancel(tmp_path):
    """The batch shell's trap writes exit_code (the worker's 4, cancelled)
    when SLURM sends SIGTERM at the time limit (audit 100 S1)."""
    job = _job(tmp_path, FakeScheduler(["RUNNING|None|n"],
                                       final=("TIMEOUT", "2026-11-02T10:00:00")),
               Clock())
    (tmp_path / "exit_code").write_text("4")
    assert job.poll() == EXIT_LOST
    assert job.lost_reason == "it reached its time limit"


def test_our_own_cancel_stays_a_cancel(tmp_path):
    job = _job(tmp_path, FakeScheduler(["RUNNING|None|n"],
                                       final=("CANCELLED", "2026-11-02T10:00:00")),
               Clock())
    job.send_signal(signal.SIGTERM)
    (tmp_path / "exit_code").write_text("4")
    assert job.poll() == 4 and job.lost_reason == ""


def test_a_job_cancelled_outside_before_it_started_says_so(tmp_path):
    clock = Clock()
    job = _job(tmp_path, FakeScheduler([""], final=("CANCELLED", "Unknown")),
               clock)
    assert job.poll() == EXIT_LOST
    assert job.lost_reason == ("it was cancelled outside Potato before it "
                               "started")


def test_an_exit_code_that_arrives_late_over_nfs_still_counts(tmp_path):
    """48 s was measured on a share mounted with acdirmin=60 (audit 100 S2):
    a finished job must not be declared lost while NFS catches up."""
    clock = Clock()
    job = _job(tmp_path, FakeScheduler([""], final=("COMPLETED", "x")), clock)
    assert job.poll() is None            # gone from the queue, finished
    for _ in range(12):                  # 60 s of polls, nothing visible yet
        clock.now += 5
        assert job.poll() is None
    (tmp_path / "exit_code").write_text("0")
    assert job.poll() == 0 and job.lost_reason == ""


def test_with_no_scheduler_record_the_grace_runs_out_with_a_reason(tmp_path):
    clock = Clock()
    job = _job(tmp_path, FakeScheduler([""], final=None), clock)
    assert job.poll() is None
    clock.now += 175
    assert job.poll() is None
    clock.now += 6                       # past 180 s, and past the 5 s re-check
    assert job.poll() == EXIT_LOST
    assert "before it started" in job.lost_reason   # no slurm.out


def test_a_lost_job_does_not_hide_the_workers_own_error(tmp_path):
    """The server keeps the last error event: job_lost after the worker's
    out_of_memory replaced the OOM message and its hint (audit 100 S2)."""
    from potato.training.agent import JobRunner

    class Client:
        def __init__(self):
            self.posted = []

        def request(self, method, path, body=None, **kw):
            self.posted.append((path, body))
            return 200, {}

    class Lost:
        job_id, pid, lost_reason, returncode = "4242", None, "its node failed", 75
        stdout = iter(['{"v": 1, "event": "error", "code": "out_of_memory", '
                       '"message": "The GPU ran out of memory", "t": 1}\n'])

        def poll(self):
            return 75

        def wait(self, timeout=None):
            return 75

    client = Client()
    runner = JobRunner(client, {"job_id": "r1", "spec": {}}, str(tmp_path),
                       slurm={})
    os.makedirs(runner.job_dir)
    runner.prepare = lambda: str(tmp_path / "spec.json")
    runner._start_worker = lambda spec, err: Lost()
    runner.run()
    events = [e for _, body in client.posted for e in (body or {}).get("events", [])]
    errors = [e for e in events if e["event"] == "error"]
    assert [e["code"] for e in errors] == ["out_of_memory"]
    assert any(e["event"] == "log" and "its node failed" in e["msg"] for e in events)


def test_signals_become_scancel(tmp_path):
    scheduler = FakeScheduler(["RUNNING|None|n"])
    job = _job(tmp_path, scheduler, Clock())
    job.send_signal(signal.SIGTERM)
    job.send_signal(signal.SIGKILL)
    assert [c for c in scheduler.calls if c[0] == "scancel"] == [
        ["scancel", "--full", "--signal=TERM", "4242"], ["scancel", "4242"]]


def test_sbatch_failing_says_why(tmp_path):
    def refuse(argv, env=None):
        return 1, "", "sbatch: error: Invalid generic resource (gres) spec"
    (tmp_path / "spec.json").write_text("{}")
    with pytest.raises(RuntimeError, match="Invalid generic resource"):
        SlurmJob({}, str(tmp_path), str(tmp_path / "spec.json"), "python",
                 "r", runner=refuse).submit()


# ---------------------------------------------------------- end to end

@pytest.fixture
def cluster(project):  # noqa: F811
    fake_dir = os.path.join(project.tmp, "fake-slurm")
    bin_dir = fake_slurm_bin(fake_dir)
    project.config["model_training"]["backends"]["cluster"] = {
        "type": "slurm", "host": "localhost", "python": sys.executable,
        "remote_dir": os.path.join(project.tmp, "shared", "potato"),
        "gres": "gpu:1", "time": "00:20:00", "nice": 0,
        "env": {"PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
                "FAKE_SLURM_DIR": fake_dir},
        "_transport": "local"}
    project.fake_dir = fake_dir
    return project


def _events(manager, run_id):
    with open(os.path.join(manager.run_dir(run_id), "events.jsonl")) as fh:
        return [json.loads(line) for line in fh]


class TestSlurmEndToEnd:
    def test_a_run_goes_through_sbatch_and_writes_back(self, cluster):
        manager = cluster.manager
        outcome = manager.start_run("sklearn-text", ["sentiment"],
                                    params={"min_instances": 4},
                                    backend="cluster")
        assert outcome["started"], outcome
        status = _wait(manager)
        assert status["state"] == "success", status

        run = store.load_run(cluster.config, outcome["run_id"])
        assert run.status == "success"
        assert "SLURM: gpu:1, time 00:20:00, nice 0" in run.host
        assert status["writeback"]["n_read"] > 0
        artifacts = os.path.join(manager.run_dir(run.run_id), "artifacts")
        assert os.path.isfile(os.path.join(artifacts, "model.pkl"))

        with open(os.path.join(cluster.fake_dir, "sbatch.log")) as fh:
            submitted = [json.loads(line) for line in fh]
        assert len(submitted) == 1
        for flag in ("--gres=gpu:1", "--time=00:20:00", "--nice=0"):
            assert flag in submitted[0]
        messages = [e.get("msg", "") for e in _events(manager, run.run_id)]
        assert any(m.startswith("Submitted SLURM job 1000") for m in messages)
        # The worker's own events came through the file, not a pipe.
        assert {"result", "status"} <= {e["event"] for e in
                                        _events(manager, run.run_id)}

    def test_a_queued_job_is_reported_as_pending(self, cluster):
        cluster.config["model_training"]["backends"]["cluster"]["env"][
            "FAKE_SLURM_PENDING_S"] = "2"
        manager = cluster.manager
        outcome = manager.start_run("sklearn-text", ["sentiment"],
                                    params={"min_instances": 4},
                                    backend="cluster")
        status = _wait(manager)
        assert status["state"] == "success", status
        events = _events(manager, outcome["run_id"])
        messages = [e.get("msg", "") for e in events]
        assert "SLURM job 1000: PENDING (Priority)" in messages
        # The run page's step said so too, while it waited.
        assert {"event": "status", "state": "queued",
                "step": "SLURM job 1000: PENDING (Priority)"}.items() <= next(
            e for e in events if e["event"] == "status").items()

    def test_cancelling_scancels_the_job(self, cluster):
        slow_dir = os.path.join(cluster.tmp, "slowmod")
        os.makedirs(slow_dir)
        with open(os.path.join(slow_dir, "slowclf.py"), "w") as fh:
            fh.write(textwrap.dedent('''
                import signal, sys, time
                from sklearn.linear_model import LogisticRegression

                class SlowClassifier(LogisticRegression):
                    def fit(self, X, y, **kw):
                        signal.signal(signal.SIGTERM, lambda *a: sys.exit(4))
                        time.sleep(120)
                        return super().fit(X, y, **kw)
            '''))
        env = cluster.config["model_training"]["backends"]["cluster"]["env"]
        env["PYTHONPATH"] = slow_dir
        manager = cluster.manager
        outcome = manager.start_run(
            "sklearn-text", ["sentiment"], backend="cluster",
            params={"min_instances": 4, "calibrate": False,
                    "classifier": "slowclf.SlowClassifier"})
        assert outcome["started"]
        deadline = time.time() + 120
        while time.time() < deadline and manager.status().get("step") != "fitting":
            time.sleep(0.2)
        assert manager.status().get("step") == "fitting", manager.status()

        started = time.time()
        assert manager.cancel(outcome["run_id"])["cancelled"]
        status = _wait(manager, timeout=90)
        assert status["state"] == "cancelled", status
        assert time.time() - started < 45
        with open(os.path.join(cluster.fake_dir, "scancel.log")) as fh:
            cancels = [json.loads(line) for line in fh]
        assert ["--full", "--signal=TERM", "1000"] in cancels

    def test_a_host_without_sbatch_is_refused_before_anything_runs(self, cluster):
        env = cluster.config["model_training"]["backends"]["cluster"]["env"]
        env["PATH"] = "/usr/bin:/bin"
        manager = cluster.manager
        outcome = manager.start_run("sklearn-text", ["sentiment"],
                                    params={"min_instances": 4},
                                    backend="cluster")
        status = _wait(manager, timeout=60)
        assert status["state"] == "error"
        run = store.load_run(cluster.config, outcome["run_id"])
        assert run.error_code == "launch_failed"
        assert "sbatch" in run.error



def test_a_finished_job_whose_exit_code_never_appears_says_so(tmp_path):
    """Audit 100 N1: scontrol saw it COMPLETED; blaming "before it started"
    pointed at the wrong thing."""
    clock = Clock()
    job = _job(tmp_path, FakeScheduler([""], final=("COMPLETED",
                                                    "2026-11-02T10:00:00")),
               clock)
    assert job.poll() is None
    clock.now += 181
    assert job.poll() == EXIT_LOST
    assert job.lost_reason.startswith("SLURM reports it COMPLETED, but its "
                                      "exit_code never appeared")


def test_an_outside_cancel_seen_only_in_slurm_out_is_named(tmp_path):
    """Audit 100 N2: exit 4 while scontrol still says COMPLETING."""
    job = _job(tmp_path, FakeScheduler(["RUNNING|None|n"],
                                       final=("COMPLETING", "x")), Clock())
    (tmp_path / "slurm.out").write_text(
        "slurmstepd: error: *** JOB 4242 ON sushi CANCELLED AT 2026-11-02T10:05 ***\n")
    (tmp_path / "exit_code").write_text("4")
    assert job.poll() == EXIT_LOST
    assert job.lost_reason == "it was cancelled outside Potato"
