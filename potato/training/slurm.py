"""Running the training worker as a SLURM batch job.

On a cluster the GPUs are behind a scheduler: the machine Potato can reach
over ssh is a login node with no GPUs, and the compute nodes cannot reach
Potato at all (the ssh backend's unix socket lives on the login node, and a
job never sees it). So the agent stays on the login node, where the
protocol works, and only the worker goes to the scheduler:

1. the agent unpacks the bundle into its work directory, which must be on a
   filesystem the compute nodes share;
2. it writes a batch script that runs ``python -m potato.training.worker``
   with stdout in ``events.jsonl``, stderr in ``stderr.log`` and the exit
   code in ``exit_code``, and submits it with ``sbatch --parsable``;
3. :class:`SlurmJob` stands in for the worker's ``Popen``: its ``stdout``
   follows ``events.jsonl``, ``poll()`` reads ``exit_code``, and signals
   become ``scancel``. The agent's supervision loop, event relay, prediction
   upload and completion report run unchanged.

Only ``sbatch``, ``squeue`` and ``scancel`` are used. ``srun`` is not, since
some clusters cannot launch steps; nor is ``sacct``, which needs an
accounting database many clusters lack. A job that leaves the queue without
writing ``exit_code`` was killed by the scheduler (time limit, node failure,
``scancel`` from outside), and the reason is read from SLURM's own output
file, ``slurm.out``.

Standard library only, like the agent.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

__all__ = ["SLURM_KEYS", "DEFAULTS", "parse_time", "validate_settings",
           "sbatch_argv", "batch_script", "SlurmJob", "EXIT_LOST"]

#: Settings a ``type: slurm`` backend adds to the ssh ones.
SLURM_KEYS = {"job_python", "partition", "gres", "time", "nice",
              "cpus_per_task", "mem", "sbatch_options", "prelude",
              "poll_interval_s", "job_name", "exit_grace_s"}

DEFAULTS: Dict[str, Any] = {"job_python": "", "partition": "", "gres": "",
                            "time": "04:00:00", "nice": 0,
                            "cpus_per_task": None, "mem": "",
                            "sbatch_options": [], "prelude": [],
                            "poll_interval_s": 30, "job_name": "potato-train",
                            "exit_grace_s": 180}

#: The worker's exit code when the scheduler ended the job before the worker
#: could report one. Not one of the worker's own codes.
EXIT_LOST = 75

#: How long, after a job leaves ``squeue``, ``exit_code`` may take to appear
#: before the job counts as lost. The file is written on the compute node, and
#: NFS caches can hide a new file from the login node: 48 s was measured on a
#: share mounted with acdirmin=60. ``exit_grace_s`` overrides it.
EXIT_FILE_GRACE_S = 180.0

#: ``scontrol`` job states in which the scheduler, not the worker, ended the
#: job, and what to tell the admin.
_SCHEDULER_ENDED = {
    "TIMEOUT": "it reached its time limit",
    "DEADLINE": "it reached its deadline",
    "NODE_FAIL": "its node failed",
    "BOOT_FAIL": "its node failed to boot",
    "PREEMPTED": "it was preempted",
    "OUT_OF_MEMORY": "it ran out of memory",
    "CANCELLED": "it was cancelled outside Potato",
}

_TIME = re.compile(r"^(?:(\d+)-)?(\d+)(?::(\d+))?(?::(\d+))?$")

Runner = Callable[[Sequence[str]], Tuple[int, str, str]]


def parse_time(text: Any) -> int:
    """A SLURM ``--time`` value in seconds. Raises ValueError.

    Accepts ``MM``, ``MM:SS``, ``HH:MM:SS``, ``D-HH``, ``D-HH:MM`` and
    ``D-HH:MM:SS``, as sbatch does.
    """
    match = _TIME.match(str(text).strip())
    if not match:
        raise ValueError("%r is not a SLURM time such as 04:00:00" % (text,))
    days, a, b, c = match.groups()
    a, b, c = int(a), int(b) if b else None, int(c) if c else None
    if days is not None:
        hours, minutes, seconds = a, b or 0, c or 0
    elif c is not None:
        hours, minutes, seconds = a, b, c
    elif b is not None:
        hours, minutes, seconds = 0, a, b
    else:
        hours, minutes, seconds = 0, a, 0
    total = ((int(days or 0) * 24 + hours) * 60 + minutes) * 60 + seconds
    if total <= 0:
        raise ValueError("time must be more than zero")
    return total


def settings_of(data: Dict[str, Any]) -> Dict[str, Any]:
    """The slurm settings in a backend entry, with defaults filled in."""
    out = dict(DEFAULTS)
    for key in SLURM_KEYS:
        if key in data and data[key] is not None:
            out[key] = data[key]
    out["sbatch_options"] = [str(o) for o in out["sbatch_options"] or []]
    out["prelude"] = [str(line) for line in out["prelude"] or []]
    return out


def validate_settings(data: Dict[str, Any], where: str) -> Tuple[List[str], List[str]]:
    """``(problems, warnings)`` for one ``type: slurm`` backend entry."""
    problems: List[str] = []
    warnings: List[str] = []
    remote_dir = str(data.get("remote_dir") or "")
    if not remote_dir:
        problems.append("%s.remote_dir is required for a slurm backend: a "
                        "directory on storage the compute nodes share"
                        % where)
    elif remote_dir.startswith(("/tmp", "/var/tmp")):
        problems.append("%s.remote_dir is %s, which is local to each node; "
                        "the job could not read the bundle" % (where, remote_dir))
    if "gpus" in data:
        problems.append("%s.gpus is not used by a slurm backend; request "
                        "GPUs with gres, such as gpu:1" % where)
    if data.get("packages"):
        problems.append("%s.packages is not supported by a slurm backend: a "
                        "virtualenv made on the login node may not run on the "
                        "compute nodes. Point job_python at an environment "
                        "that exists on them." % where)
    if "time" in data:
        try:
            seconds = parse_time(data["time"])
            if seconds > 6 * 3600:
                warnings.append("%s.time is %s. A job that holds a GPU for "
                                "more than 6 hours is long on a shared "
                                "cluster; check its policy" % (where, data["time"]))
        except ValueError as exc:
            problems.append("%s.time: %s" % (where, exc))
    if "nice" in data:
        try:
            nice = int(data["nice"])
            if not 0 <= nice <= 2000:
                problems.append("%s.nice must be between 0 and 2000" % where)
        except (TypeError, ValueError):
            problems.append("%s.nice must be a whole number" % where)
    if "exit_grace_s" in data:
        try:
            if float(data["exit_grace_s"]) < 20:
                problems.append("%s.exit_grace_s must be at least 20" % where)
        except (TypeError, ValueError):
            problems.append("%s.exit_grace_s must be a number" % where)
    if "poll_interval_s" in data:
        try:
            if float(data["poll_interval_s"]) < 10:
                problems.append("%s.poll_interval_s must be at least 10: "
                                "squeue is the scheduler's own controller"
                                % where)
        except (TypeError, ValueError):
            problems.append("%s.poll_interval_s must be a number" % where)
    for key in ("sbatch_options", "prelude"):
        if key in data and not isinstance(data[key], list):
            problems.append("%s.%s must be a list" % (where, key))
    for option in data.get("sbatch_options") or []:
        if str(option).split("=", 1)[0] in _OWNED_FLAGS:
            problems.append("%s.sbatch_options sets %s, which Potato sets "
                            "itself" % (where, str(option).split("=", 1)[0]))
    return problems, warnings


#: Flags the backend sets from its own settings or needs for itself.
_OWNED_FLAGS = {"--output", "-o", "--error", "-e", "--chdir", "-D",
                "--parsable", "--job-name", "-J", "--wrap"}


def sbatch_argv(settings: Dict[str, Any], job_dir: str, script: str,
                run_id: str) -> List[str]:
    """The ``sbatch`` command line. Paths go here rather than in ``#SBATCH``
    lines, which sbatch does not unquote."""
    argv = ["sbatch", "--parsable",
            "--job-name=%s-%s" % (settings.get("job_name") or "potato-train",
                                  run_id[:8]),
            "--output=%s" % os.path.join(job_dir, "slurm.out"),
            "--chdir=%s" % job_dir,
            "--time=%s" % (settings.get("time") or DEFAULTS["time"]),
            "--nice=%d" % int(settings.get("nice") or 0)]
    if settings.get("partition"):
        argv.append("--partition=%s" % settings["partition"])
    if settings.get("gres"):
        argv.append("--gres=%s" % settings["gres"])
    if settings.get("cpus_per_task"):
        argv.append("--cpus-per-task=%d" % int(settings["cpus_per_task"]))
    if settings.get("mem"):
        argv.append("--mem=%s" % settings["mem"])
    argv.extend(settings.get("sbatch_options") or [])
    argv.append(script)
    return argv


def batch_script(settings: Dict[str, Any], python: str, spec_path: str
                 ) -> str:
    """The job script. Runs in ``job_dir`` (``--chdir``)."""
    lines = ["#!/bin/bash",
             "# Written by Potato's training agent. The worker's events go to",
             "# events.jsonl, which the agent on the login node relays.",
             "set -u",
             # A handler rather than `trap '' TERM`: an ignored signal stays
             # ignored in the worker, which must stop on it. With a handler
             # the shell waits for the worker, then still writes exit_code.
             "trap 'echo \"potato: SIGTERM at $(date)\" >&2' TERM",
             'echo "potato: job ${SLURM_JOB_ID:-?} on $(hostname) at $(date), '
             'CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}" >&2']
    lines.extend(settings.get("prelude") or [])
    lines.append("%s -m potato.training.worker --spec %s > events.jsonl "
                 "2> stderr.log" % (shlex.quote(python),
                                    shlex.quote(spec_path)))
    lines.append("code=$?")
    lines.append('echo "potato: worker exited $code at $(date)" >&2')
    lines.append("echo $code > exit_code.tmp && mv exit_code.tmp exit_code")
    lines.append("exit $code")
    return "\n".join(lines) + "\n"


def _shell_runner(argv: Sequence[str], env: Optional[Dict[str, str]] = None,
                  timeout: float = 60.0) -> Tuple[int, str, str]:
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True,
                              timeout=timeout, env=env)
    except FileNotFoundError:
        return 127, "", "%s: command not found" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "", "%s timed out after %d s" % (argv[0], timeout)
    return done.returncode, done.stdout, done.stderr


class SlurmJob:
    """A submitted batch job, with the parts of ``Popen`` the agent uses.

    ``stdout`` yields the worker's event lines as they are written;
    ``poll()``/``wait()`` give its exit code; ``send_signal`` cancels it.
    ``log(level, message)`` reports queue changes ("PENDING (Priority)",
    "RUNNING on node07").
    """

    def __init__(self, settings: Dict[str, Any], job_dir: str,
                 spec_path: str, python: str, run_id: str,
                 env: Optional[Dict[str, str]] = None,
                 log: Optional[Callable[[str, str], None]] = None,
                 runner: Optional[Callable[..., Tuple[int, str, str]]] = None,
                 clock: Callable[[], float] = time.time,
                 on_state: Optional[Callable[[str, str], None]] = None):
        self.settings = settings_of(settings)
        self.job_dir = job_dir
        self.spec_path = spec_path
        self.python = python
        self.run_id = run_id
        self.env = dict(env if env is not None else os.environ)
        # The scheduler sets CUDA_VISIBLE_DEVICES for the GPUs it grants;
        # a value carried over from the login node would override it.
        self.env.pop("CUDA_VISIBLE_DEVICES", None)
        self._log = log or (lambda level, msg: None)
        #: ``on_state(state, description)``: called when the queue state
        #: changes, so the run page can show "PENDING (Priority)".
        self._on_state = on_state or (lambda state, text: None)
        self._run = runner or _shell_runner
        self._clock = clock
        self.job_id = ""
        self.pid = None
        self.returncode: Optional[int] = None
        self.state = ""
        self.lost_reason = ""
        self._last_check = 0.0
        self._gone_since: Optional[float] = None
        self._cancelled = False
        #: ``(JobState, StartTime)`` when the job left the queue.
        self._final: Tuple[str, str] = ("", "")

    # -- submit ---------------------------------------------------------

    def submit(self) -> "SlurmJob":
        script = os.path.join(self.job_dir, "job.sh")
        with open(script, "w") as fh:
            fh.write(batch_script(self.settings, self.python, self.spec_path))
        os.chmod(script, 0o700)
        for name in ("exit_code", "events.jsonl"):
            try:
                os.remove(os.path.join(self.job_dir, name))
            except OSError:
                pass
        argv = sbatch_argv(self.settings, self.job_dir, script, self.run_id)
        rc, out, err = self._run(argv, env=self.env)
        if rc != 0:
            raise RuntimeError("sbatch failed (exit %d): %s"
                               % (rc, (err or out).strip()[:1000]))
        # --parsable prints "<id>" or "<id>;<cluster>".
        self.job_id = out.strip().splitlines()[-1].split(";")[0].strip() \
            if out.strip() else ""
        if not self.job_id.isdigit():
            raise RuntimeError("sbatch did not print a job id: %r" % out[:200])
        self._log("info", "Submitted SLURM job %s (%s)" % (
            self.job_id, " ".join(a for a in argv[1:-1]
                                  if not a.startswith(("--output", "--chdir")))))
        return self

    # -- Popen-like -----------------------------------------------------

    def _exit_code(self) -> Optional[int]:
        try:
            with open(os.path.join(self.job_dir, "exit_code")) as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            return None

    def _squeue(self) -> Optional[str]:
        """``"STATE|reason|node"`` while queued or running; ``""`` once gone;
        None when squeue itself failed."""
        rc, out, err = self._run(["squeue", "-h", "-j", self.job_id,
                                  "-o", "%T|%r|%N"], env=self.env)
        if rc != 0:
            # squeue errors for a job id it no longer knows on some versions.
            return "" if "Invalid job id" in (out + err) else None
        return out.strip().splitlines()[0] if out.strip() else ""

    def _final_state(self) -> Tuple[str, str]:
        """``(JobState, StartTime)`` from ``scontrol show job``, which keeps a
        finished job for the cluster's MinJobAge (300 s by default) with no
        accounting database. ``("", "")`` when it no longer knows the job."""
        rc, out, _ = self._run(["scontrol", "show", "job", "-o", self.job_id],
                               env=self.env)
        if rc != 0 or not out.strip():
            return "", ""
        fields = dict(part.split("=", 1) for part in out.split()
                      if "=" in part)
        return fields.get("JobState", "").split("+")[0], fields.get("StartTime", "")

    def _ended_by_scheduler(self, state: str, started: str) -> str:
        reason = _SCHEDULER_ENDED.get(state, "")
        if state == "CANCELLED" and self._cancelled:
            return ""
        if state == "CANCELLED" and started in ("", "Unknown", "None"):
            return "it was cancelled outside Potato before it started"
        return reason

    def poll(self) -> Optional[int]:
        if self.returncode is not None:
            return self.returncode
        code = self._exit_code()
        if code is not None:
            if code != 0 and not self._cancelled:
                # A time limit or an outside scancel sends SIGTERM: the
                # worker stops cleanly and the shell still writes its code,
                # which reads as an ordinary cancel. Ask the scheduler.
                state, started = self._final_state()
                reason = self._ended_by_scheduler(state, started) or \
                    self._reason_from_output()
                if reason:
                    self.lost_reason = reason
                    code = EXIT_LOST
            self.returncode = code
            return code
        now = self._clock()
        interval = max(10.0, float(self.settings.get("poll_interval_s") or 30))
        if self._gone_since is None and now - self._last_check < interval:
            return None
        if self._gone_since is not None and now - self._last_check < 5.0:
            return None
        self._last_check = now
        line = self._squeue()
        if line is None:
            return None
        if line:
            self._gone_since = None
            state, _, rest = line.partition("|")
            reason, _, node = rest.partition("|")
            shown = ("%s on %s" % (state, node) if state == "RUNNING" and node
                     else "%s (%s)" % (state, reason) if reason
                     and reason != "None" else state)
            if shown != self.state:
                self.state = shown
                self._log("info", "SLURM job %s: %s" % (self.job_id, shown))
                self._on_state(state, "SLURM job %s: %s" % (self.job_id, shown))
            return None
        if self._gone_since is None:
            self._gone_since = now
            state, started = self._final = self._final_state()
            reason = self._ended_by_scheduler(state, started)
            if reason:
                # The scheduler says how it ended; no need to wait on NFS.
                self.lost_reason = reason
                self.returncode = EXIT_LOST
                return self.returncode
            return None
        grace = max(20.0, float(self.settings.get("exit_grace_s")
                                or EXIT_FILE_GRACE_S))
        if now - self._gone_since < grace:
            return None
        self.lost_reason = self._why_lost()
        self.returncode = EXIT_LOST
        return self.returncode

    def _reason_from_output(self) -> str:
        try:
            with open(os.path.join(self.job_dir, "slurm.out"),
                      errors="replace") as fh:
                text = fh.read()[-4000:]
        except OSError:
            return ""
        for needle, why in (("DUE TO TIME LIMIT", "it reached its time limit"),
                            ("DUE TO NODE FAIL", "its node failed"),
                            ("DUE TO PREEMPTION", "it was preempted"),
                            ("oom-kill", "it ran out of memory"),
                            ("Out Of Memory", "it ran out of memory")):
            if needle in text:
                return why
        if "CANCELLED AT" in text and not self._cancelled:
            # slurmstepd's line for an scancel; ours sets _cancelled.
            return "it was cancelled outside Potato"
        return ""

    def _why_lost(self) -> str:
        reason = self._reason_from_output()
        if reason:
            return reason
        if self._cancelled:
            return "it was cancelled"
        state, started = self._final
        if state in ("COMPLETED", "FAILED") and started not in ("", "Unknown", "None"):
            # The scheduler saw it run and finish; the file is what is missing.
            return ("SLURM reports it %s, but its exit_code never appeared in "
                    "the job directory within %d s: can the compute node "
                    "write there (quota, permissions), or is the shared "
                    "filesystem slower than exit_grace_s?"
                    % (state, int(float(self.settings.get("exit_grace_s")
                                        or EXIT_FILE_GRACE_S))))
        if not os.path.exists(os.path.join(self.job_dir, "slurm.out")):
            return ("it left the queue before it started (there is no "
                    "slurm.out); was it cancelled outside Potato?")
        return ("it left the queue and no exit code appeared within %d s "
                "(a time limit or node failure, or a shared filesystem "
                "slower than exit_grace_s)"
                % int(float(self.settings.get("exit_grace_s") or EXIT_FILE_GRACE_S)))

    def wait(self, timeout: Optional[float] = None) -> int:
        deadline = None if timeout is None else self._clock() + timeout
        while self.poll() is None:
            if deadline is not None and self._clock() > deadline:
                raise subprocess.TimeoutExpired("slurm job %s" % self.job_id,
                                                timeout)
            time.sleep(0.5)
        return int(self.returncode)

    def send_signal(self, sig: int) -> None:
        if not self.job_id or self.returncode is not None:
            return
        self._cancelled = True
        if sig == signal.SIGTERM:
            # --full reaches the worker inside the batch shell, which a plain
            # --signal does not for a job without steps.
            self._run(["scancel", "--full", "--signal=TERM", self.job_id],
                      env=self.env)
        else:
            self._run(["scancel", self.job_id], env=self.env)

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    @property
    def stdout(self) -> Iterator[str]:
        return self._follow()

    def _follow(self) -> Iterator[str]:
        """Lines of ``events.jsonl`` as they appear, until the job ends and
        the file has been read to its end."""
        path = os.path.join(self.job_dir, "events.jsonl")
        offset, partial = 0, ""
        while True:
            done = self.poll() is not None
            try:
                with open(path, errors="replace") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
                    offset = fh.tell()
            except OSError:
                chunk = ""
            if chunk:
                partial += chunk
                *lines, partial = partial.split("\n")
                for line in lines:
                    yield line + "\n"
                continue
            if done:
                if partial:
                    yield partial
                return
            time.sleep(1.0)


def describe(settings: Dict[str, Any]) -> str:
    """One line for the run page: what was asked for."""
    s = settings_of(settings)
    parts = [s["gres"] or "no GPU requested", "time %s" % s["time"],
             "nice %s" % s["nice"]]
    if s["partition"]:
        parts.insert(0, "partition %s" % s["partition"])
    return ", ".join(parts)


def dumps(settings: Dict[str, Any]) -> str:
    return json.dumps(settings_of(settings), sort_keys=True)
