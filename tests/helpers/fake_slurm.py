"""A stand-in for ``sbatch``, ``squeue`` and ``scancel``, for tests.

``fake_slurm_bin(directory)`` writes the three commands into
``directory/bin`` and returns that path, to put first on ``PATH``. Jobs run
on this machine as background processes; their state lives in
``FAKE_SLURM_DIR`` (``directory`` by default), so the three commands agree
across processes the way a real controller's clients do.

What a test can set, in the environment of the process calling sbatch:

``FAKE_SLURM_PENDING_S``
    Seconds a job stays PENDING (reason ``Priority``) before it starts.

Every sbatch command line is appended to ``sbatch.log`` as JSON, so a test
can check what was asked for.
"""

import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.abspath(__file__)


def fake_slurm_bin(directory: str) -> str:
    bin_dir = os.path.join(directory, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    for command in ("sbatch", "squeue", "scancel"):
        path = os.path.join(bin_dir, command)
        with open(path, "w") as fh:
            fh.write('#!/bin/sh\nFAKE_SLURM_DIR="${FAKE_SLURM_DIR:-%s}" '
                     'exec "%s" "%s" %s "$@"\n'
                     % (directory, sys.executable, HERE, command))
        os.chmod(path, 0o755)
    return bin_dir


def _root() -> str:
    root = os.environ["FAKE_SLURM_DIR"]
    os.makedirs(os.path.join(root, "jobs"), exist_ok=True)
    return root


def _state_path(job_id: str) -> str:
    return os.path.join(_root(), "jobs", "%s.json" % job_id)


def _read(job_id: str):
    try:
        with open(_state_path(job_id)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(job_id: str, state) -> None:
    tmp = _state_path(job_id) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, _state_path(job_id))


def sbatch(argv):
    options = {}
    for arg in argv[:-1]:
        key, _, value = arg.partition("=")
        options[key] = value
    script = argv[-1]
    root = _root()
    with open(os.path.join(root, "sbatch.log"), "a") as fh:
        fh.write(json.dumps(argv) + "\n")
    counter = os.path.join(root, "counter")
    job_id = str(int(open(counter).read()) + 1 if os.path.exists(counter)
                 else 1000)
    with open(counter, "w") as fh:
        fh.write(job_id)
    _write(job_id, {"state": "PENDING", "reason": "Priority"})
    subprocess.Popen(
        [sys.executable, HERE, "_run", job_id, script,
         options.get("--chdir", "."), options.get("--output", "slurm.out")],
        start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=dict(os.environ, SLURM_JOB_ID=job_id))
    print(job_id)
    return 0


def _run(job_id, script, chdir, output):
    time.sleep(float(os.environ.get("FAKE_SLURM_PENDING_S") or 0))
    state = _read(job_id)
    if state is None:  # cancelled while pending
        return 0
    with open(output, "a") as out:
        process = subprocess.Popen(["bash", script], cwd=chdir, stdout=out,
                                   stderr=out, start_new_session=True)
        _write(job_id, {"state": "RUNNING", "reason": "None",
                        "node": "fakenode", "pgid": process.pid,
                        "output": output})
        process.wait()
    try:
        os.remove(_state_path(job_id))
    except OSError:
        pass
    return 0


def squeue(argv):
    job_id = argv[argv.index("-j") + 1] if "-j" in argv else ""
    state = _read(job_id)
    if state:
        print("%s|%s|%s" % (state["state"], state.get("reason", "None"),
                            state.get("node", "")))
    return 0


def scancel(argv):
    job_id = argv[-1]
    state = _read(job_id)
    if state is None:
        return 0
    term = "--signal=TERM" in argv
    with open(os.path.join(_root(), "scancel.log"), "a") as fh:
        fh.write(json.dumps(argv) + "\n")
    if state["state"] == "PENDING":
        os.remove(_state_path(job_id))
        return 0
    try:
        os.killpg(state["pgid"], signal.SIGTERM if term else signal.SIGKILL)
    except OSError:
        pass
    if not term:
        with open(state["output"], "a") as fh:
            fh.write("slurmstepd: error: *** JOB %s ON fakenode CANCELLED "
                     "AT now ***\n" % job_id)
    return 0


if __name__ == "__main__":
    command, rest = sys.argv[1], sys.argv[2:]
    if command == "_run":
        sys.exit(_run(*rest))
    sys.exit({"sbatch": sbatch, "squeue": squeue, "scancel": scancel}[command](rest))
