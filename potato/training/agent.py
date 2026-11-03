"""The training agent: runs Potato training jobs on another machine.

It asks a Potato server for work, downloads the job's bundle, runs the same
``potato.training.worker`` the server would have run locally, and reports
back over :mod:`potato.training.protocol`. Standard library only, so it runs
wherever Python and the trainer's own packages do.

Two ways it gets started:

* **By Potato, over ssh**, for one run (``--job``). The token arrives on
  stdin, the connection is a unix socket that ssh forwards back to the
  server (``--socket``), and the agent exits when the run does or when ssh
  goes away (``--exit-on-stdin-eof``). Nobody types this command.
* **By hand**, on a machine the server cannot reach::

      export POTATO_TRAINING_TOKEN=...   # from `potato training register`
      potato training agent --server https://annotate.example.org \\
          --backend labgpu

  It then polls for work until stopped.

Exit codes: 0 when the last job succeeded or polling was stopped, otherwise
the worker's exit code for ``--job``.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

API = "/api/training"

#: Seconds between progress posts while events are arriving, and the longest
#: gap with nothing to say before an empty post keeps the job alive.
FLUSH_INTERVAL_S = 1.0
HEARTBEAT_INTERVAL_S = 15.0
#: How long the server may be unreachable before the agent stops the worker.
GIVE_UP_AFTER_S = 300.0


def _say(message: str) -> None:
    sys.stderr.write("[potato-agent] %s\n" % message)
    sys.stderr.flush()


class ProtocolError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__("HTTP %d: %s" % (status, message))
        self.status = status


class _Restart(Exception):
    """Discard the partial download and fetch the file whole."""


class _Retry(Exception):
    """A server error worth another attempt."""

    def __init__(self, failure: ProtocolError):
        super().__init__(str(failure))
        self.failure = failure


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a unix socket: the far end of an ``ssh -R`` socket forward."""

    def __init__(self, path: str, timeout: float = 60.0,
                 tls: bool = False):
        super().__init__("localhost", timeout=timeout)
        self._path = path
        self._tls = tls

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        if self._tls:
            # The server's certificate names its public host, not this
            # socket, and the hop is already inside an authenticated ssh
            # connection. Verifying would only refuse.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock, server_hostname="localhost")
        self.sock = sock


class Client:
    """A minimal client for the protocol, over TCP or a unix socket."""

    def __init__(self, token: str, server: str = "",
                 socket_path: str = "", tls_over_socket: bool = False,
                 timeout: float = 120.0):
        if not server and not socket_path:
            raise ValueError("Need a server URL or a socket path")
        self.token = token
        self.socket_path = socket_path
        self.tls_over_socket = tls_over_socket
        self.timeout = timeout
        parsed = urllib.parse.urlparse(server) if server else None
        self._scheme = parsed.scheme if parsed else "http"
        self._netloc = parsed.netloc if parsed else ""
        self._prefix = (parsed.path.rstrip("/") if parsed else "")

    def _connection(self, timeout: float):
        if self.socket_path:
            return _UnixHTTPConnection(self.socket_path, timeout,
                                       tls=self.tls_over_socket)
        if self._scheme == "https":
            return http.client.HTTPSConnection(self._netloc, timeout=timeout)
        return http.client.HTTPConnection(self._netloc, timeout=timeout)

    def request(self, method: str, path: str, body: Any = None,
                headers: Optional[Dict[str, str]] = None,
                stream_to: Optional[str] = None,
                timeout: Optional[float] = None) -> Tuple[int, Any]:
        """``(status, parsed JSON or None)``. With *stream_to*, the body is
        written to that file instead."""
        headers = dict(headers or {})
        headers["Authorization"] = "Bearer %s" % self.token
        payload = body
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        conn = self._connection(timeout or self.timeout)
        try:
            conn.request(method, self._prefix + path, body=payload,
                         headers=headers)
            response = conn.getresponse()
            status = response.status
            if stream_to and status == 200:
                with open(stream_to, "wb") as fh:
                    shutil.copyfileobj(response, fh, 1 << 16)
                return status, None
            raw = response.read()
        finally:
            conn.close()

        data = None
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                data = {"error": raw[:500].decode("utf-8", "replace")}
        if status >= 400:
            message = (data or {}).get("error", "") if isinstance(data, dict) \
                else ""
            raise ProtocolError(status, message or "request failed")
        return status, data

    def download(self, path: str, dest: str, timeout: Optional[float] = None,
                 attempts: int = 5, backoff_s: float = 2.0,
                 _sleep=time.sleep) -> int:
        """Download *path* to *dest*, resuming where a dropped connection
        left off. Returns the size in bytes.

        A bundle with its media can be gigabytes over a slow link, and a
        restart from zero after a dropped connection was the only recovery.
        Each retry asks for the bytes it does not have (``Range``), tied to
        the file it started on (``If-Range`` with its ETag): if the server's
        file changed in between, the server sends it whole and the partial
        copy is discarded. A 5xx is retried like a dropped connection; any
        other 4xx is final. A 416 (the file shrank), or a partial answer for
        other bytes or another ETag than asked, restarts from zero.
        """
        partial = dest + ".partial"
        if os.path.exists(partial):
            os.remove(partial)
        etag, total, last_error = None, None, None
        for attempt in range(attempts):
            have = os.path.getsize(partial) if os.path.exists(partial) else 0
            headers = {"Authorization": "Bearer %s" % self.token}
            if have and etag:
                headers["Range"] = "bytes=%d-" % have
                headers["If-Range"] = etag
            error = None
            conn = self._connection(timeout or self.timeout)
            try:
                conn.request("GET", self._prefix + path, headers=headers)
                response = conn.getresponse()
                status = response.status
                if status == 416 and "Range" in headers:
                    response.read()
                    raise _Restart("the server refused the range")
                if status >= 400:
                    raw = response.read()
                    try:
                        message = json.loads(raw.decode("utf-8")).get("error", "")
                    except (ValueError, AttributeError):
                        message = raw[:200].decode("utf-8", "replace")
                    failure = ProtocolError(status, message or "download failed")
                    if status < 500:
                        raise failure
                    raise _Retry(failure)
                if status == 206:
                    mode = "ab"
                    content_range = response.getheader("Content-Range") or ""
                    start = content_range.split(" ", 1)[-1].split("-", 1)[0]
                    changed = response.getheader("ETag")
                    if "Range" not in headers or start != str(have) or (
                            changed and etag and changed != etag):
                        raise _Restart("a partial answer for other bytes "
                                       "(%s) than asked" % content_range)
                    tail = content_range.rsplit("/", 1)[-1]
                    if tail.isdigit():
                        total = int(tail)
                else:
                    # A whole file: the first answer, or the server's file
                    # changed and If-Range sent it again from the start.
                    mode = "wb"
                    etag = response.getheader("ETag")
                    length = response.getheader("Content-Length") or ""
                    total = int(length) if length.isdigit() else None
                with open(partial, mode) as fh:
                    shutil.copyfileobj(response, fh, 1 << 16)
            except _Restart as exc:
                error = exc
                etag, total = None, None
                if os.path.exists(partial):
                    os.remove(partial)
            except _Retry as exc:
                error = exc.failure
            except (OSError, http.client.HTTPException) as exc:
                error = exc
            except ProtocolError:
                if os.path.exists(partial):
                    os.remove(partial)
                raise
            finally:
                conn.close()

            size = os.path.getsize(partial) if os.path.exists(partial) else 0
            if error is None and (total is None or size >= total):
                os.replace(partial, dest)
                return size
            last_error = error or OSError("connection closed at %d of %s bytes"
                                          % (size, total))
            if attempt + 1 < attempts:
                _sleep(backoff_s * (attempt + 1))
        if os.path.exists(partial):
            os.remove(partial)
        raise ProtocolError(getattr(last_error, "status", 0),
                            "Download of %s failed after %d attempts: %s"
                            % (path, attempts, last_error))


def agent_info() -> Dict[str, str]:
    info = {"host": platform.node(), "python": platform.python_version(),
            "platform": platform.platform(terse=True)}
    if os.environ.get("CUDA_VISIBLE_DEVICES") is not None:
        info["cuda_visible_devices"] = os.environ["CUDA_VISIBLE_DEVICES"]
    try:
        from potato import __version__
        info["version"] = __version__
    except Exception:
        pass
    return info


def _safe_extract(archive: str, dest: str) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
            return
        root = os.path.realpath(dest)
        for member in tar.getmembers():
            target = os.path.realpath(os.path.join(dest, member.name))
            if not (target == root or target.startswith(root + os.sep)) \
                    or member.issym() or member.islnk():
                raise ProtocolError(0, "Refusing unsafe bundle entry %r"
                                    % member.name)
        tar.extractall(dest)


def _job_dir_name(run_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id)


class JobRunner:
    """Runs one job: download, work, report."""

    def __init__(self, client: Client, job: Dict[str, Any], root: str,
                 python: str = sys.executable, grace_s: float = 20.0,
                 keep: bool = True, stop_event: Optional[threading.Event] = None,
                 slurm: Optional[Dict[str, Any]] = None):
        self.client = client
        self.job = job
        self.run_id = job["job_id"]
        self.root = os.path.abspath(os.path.expanduser(root))
        self.python = python
        self.grace_s = grace_s
        self.keep = keep
        self.stop_event = stop_event or threading.Event()
        self.job_dir = os.path.join(self.root, "jobs",
                                    _job_dir_name(self.run_id))
        self._pending: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.result_seen = False
        #: The worker reported its own error; a SLURM "job lost" must not
        #: replace it (the server keeps the last error event).
        self.error_seen = False
        self._cancel_sent_at: Optional[float] = None
        self._process: Optional[subprocess.Popen] = None
        #: Submit the worker as a SLURM batch job instead of running it
        #: here (see :mod:`potato.training.slurm`).
        self.slurm = slurm

    # -- events --------------------------------------------------------

    def _queue(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._pending.append(payload)
            if payload.get("event") == "result":
                self.result_seen = True
            elif payload.get("event") == "error":
                self.error_seen = True

    def _log(self, level: str, msg: str) -> None:
        from potato.training.events import event
        self._queue(event("log", level=level, msg=msg))

    def _flush(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            batch, self._pending = self._pending, []
        try:
            _, data = self.client.request(
                "POST", "%s/jobs/%s/progress" % (API, self.run_id),
                {"events": batch})
            return data or {}
        except Exception:
            with self._lock:
                self._pending = batch + self._pending
            raise

    # -- the run -------------------------------------------------------

    def prepare(self) -> str:
        """Download and unpack the bundle; write a local spec. Returns its path."""
        if os.path.isdir(self.job_dir):
            shutil.rmtree(self.job_dir)
        bundle_dir = os.path.join(self.job_dir, "bundle")
        artifacts = os.path.join(self.job_dir, "artifacts")
        os.makedirs(bundle_dir)
        os.makedirs(artifacts)

        archive = os.path.join(self.job_dir, "bundle.tar.gz")
        self.client.download("%s/jobs/%s/bundle" % (API, self.run_id),
                             archive, timeout=600)
        _safe_extract(archive, bundle_dir)
        os.remove(archive)

        spec = dict(self.job["spec"])
        spec["bundle_dir"] = bundle_dir
        spec["workdir"] = artifacts
        spec_path = os.path.join(self.job_dir, "spec.json")
        with open(spec_path, "w") as fh:
            json.dump(spec, fh, indent=2)
        return spec_path

    def _environment(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("MPLBACKEND", "Agg")
        threads = (self.job["spec"].get("limits") or {}).get("num_threads")
        if threads:
            # Shared hosts often export OMP_NUM_THREADS=1 in login shells;
            # the run's own setting wins.
            for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
                        "OPENBLAS_NUM_THREADS"):
                env[var] = str(threads)
        cache = env.get("POTATO_MODEL_CACHE")
        if cache:
            env.setdefault("HF_HOME", cache)
            env.setdefault("SENTENCE_TRANSFORMERS_HOME", cache)
        return env

    def run(self) -> int:
        from potato.training.events import EXIT_UNEXPECTED, event, parse_line

        try:
            spec_path = self.prepare()
        except Exception as exc:  # noqa: BLE001
            self._queue(event("error", code="bundle_failed",
                              message="The agent could not fetch the "
                                      "bundle: %s" % exc, install_hint=""))
            return self._complete(EXIT_UNEXPECTED)

        info = agent_info()
        self._log("info", "Agent on %s (Python %s%s) running the job"
                  % (info["host"], info["python"],
                     ", CUDA_VISIBLE_DEVICES=%s" % info["cuda_visible_devices"]
                     if "cuda_visible_devices" in info else ""))

        stderr_path = os.path.join(self.job_dir, "stderr.log")
        stdout_path = os.path.join(self.job_dir, "stdout.log")
        with open(stderr_path, "w") as stderr_fh:
            try:
                process = self._start_worker(spec_path, stderr_fh)
            except Exception as exc:  # noqa: BLE001
                self._queue(event("error", code="launch_failed",
                                  message=str(exc), install_hint=""))
                return self._complete(EXIT_UNEXPECTED)
            self._process = process

            def drain():
                with open(stdout_path, "w") as raw:
                    for line in process.stdout:
                        raw.write(line)
                        payload = parse_line(line)
                        if payload is not None:
                            self._queue(payload)

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            self._supervise(process)
            reader.join(timeout=10)
            returncode = process.wait()

        if returncode != 0 and not self.result_seen:
            if getattr(process, "lost_reason", ""):
                message = ("SLURM job %s ended before the worker finished: %s"
                           % (process.job_id, process.lost_reason))
                if self.error_seen:
                    self._log("warning", message)
                else:
                    self._queue(event("error", code="job_lost",
                                      install_hint="", message=message))
            tail = _tail(stderr_path)
            if tail:
                self._log("error", "Worker stderr:\n%s" % tail)
        self._upload_predictions()
        return self._complete(returncode)

    def _start_worker(self, spec_path: str, stderr_fh):
        """The worker process, or a stand-in with the same interface."""
        if self.slurm is not None:
            from potato.training.slurm import SlurmJob
            # The job writes its own stderr.log next to the spec; the
            # agent's copy stays empty.
            from potato.training.events import event

            def on_state(state, text):
                # Until the worker's own status events arrive, the run page
                # shows where the job is in the queue.
                if state != "RUNNING":
                    self._queue(event("status", state="queued", step=text))
                else:
                    self._queue(event("status", state="running", step=text))
            return SlurmJob(self.slurm, self.job_dir, spec_path, self.python,
                            self.run_id, env=self._environment(),
                            log=self._log, on_state=on_state).submit()
        return subprocess.Popen(
            [self.python, "-m", "potato.training.worker",
             "--spec", spec_path],
            cwd=self.job_dir, env=self._environment(),
            stdout=subprocess.PIPE, stderr=stderr_fh, text=True,
            bufsize=1, start_new_session=True)

    def _supervise(self, process: subprocess.Popen) -> None:
        last_post = 0.0
        failing_since: Optional[float] = None
        while True:
            exited = process.poll() is not None
            now = time.time()
            with self._lock:
                has_events = bool(self._pending)
            if exited:
                return
            if has_events and now - last_post >= FLUSH_INTERVAL_S or \
                    now - last_post >= HEARTBEAT_INTERVAL_S:
                try:
                    response = self._flush()
                    last_post = now
                    failing_since = None
                    if response.get("cancelled"):
                        self._cancel(process, "the server asked to cancel")
                except ProtocolError as exc:
                    if exc.status in (401, 404, 410):
                        self._cancel(process, "the server no longer knows "
                                     "this job (%s)" % exc)
                    failing_since = failing_since or now
                except Exception as exc:  # noqa: BLE001
                    failing_since = failing_since or now
                    if now - failing_since > GIVE_UP_AFTER_S:
                        self._cancel(process, "the server has been "
                                     "unreachable for %d s (%s)"
                                     % (GIVE_UP_AFTER_S, exc))
            if self.stop_event.is_set():
                self._cancel(process, "the agent is stopping")
            if self._cancel_sent_at and \
                    now - self._cancel_sent_at > self.grace_s:
                _killpg(process, signal.SIGKILL)
            time.sleep(0.2)

    def _cancel(self, process: subprocess.Popen, why: str) -> None:
        if self._cancel_sent_at is not None:
            return
        _say("cancelling run %s: %s" % (self.run_id, why))
        self._cancel_sent_at = time.time()
        _killpg(process, signal.SIGTERM)

    def _upload_predictions(self) -> None:
        from potato.training.worker import PREDICTIONS_FILE

        path = os.path.join(self.job_dir, "artifacts", PREDICTIONS_FILE)
        if not self.result_seen or not os.path.isfile(path):
            return
        try:
            with open(path, "rb") as fh:
                self.client.request(
                    "POST", "%s/jobs/%s/predictions" % (API, self.run_id),
                    body=fh, timeout=600,
                    headers={"Content-Type": "application/x-ndjson",
                             "Content-Length": str(os.path.getsize(path))})
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "Could not upload predictions: %s" % exc)

    def _complete(self, returncode: int) -> int:
        with self._lock:
            batch, self._pending = self._pending, []
        body = {"returncode": int(returncode), "events": batch,
                "host": platform.node(),
                "artifact_uri": "%s:%s" % (platform.node(),
                                           os.path.join(self.job_dir,
                                                        "artifacts"))}
        for attempt in range(5):
            try:
                self.client.request(
                    "POST", "%s/jobs/%s/complete" % (API, self.run_id), body)
                break
            except ProtocolError as exc:
                _say("could not report completion: %s" % exc)
                break
            except Exception as exc:  # noqa: BLE001
                _say("could not report completion (attempt %d): %s"
                     % (attempt + 1, exc))
                time.sleep(2 ** attempt)
        if not self.keep:
            shutil.rmtree(os.path.join(self.job_dir, "bundle"),
                          ignore_errors=True)
        return int(returncode)


def _killpg(process: subprocess.Popen, sig: int) -> None:
    if process.poll() is not None:
        return
    if getattr(process, "pid", None) is None:
        # A SLURM job: its own send_signal maps to scancel.
        process.send_signal(sig)
        return
    try:
        os.killpg(os.getpgid(process.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.send_signal(sig)
        except Exception:
            pass


def _tail(path: str, limit: int = 3000) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            return fh.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


# ------------------------------------------------------------------ main

def _read_token(args) -> str:
    if args.token_stdin:
        return sys.stdin.readline().strip()
    if args.token_file:
        with open(os.path.expanduser(args.token_file)) as fh:
            return fh.read().strip()
    return os.environ.get("POTATO_TRAINING_TOKEN", "").strip()


def _watch_stdin(stop: threading.Event) -> None:
    """Stop when stdin closes: the ssh session that started us has gone."""
    def watch():
        try:
            while sys.stdin.readline():
                pass
        except Exception:
            pass
        stop.set()
    threading.Thread(target=watch, daemon=True).start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato training agent",
        description="Run Potato training jobs on this machine. Polls a "
                    "Potato server for work and reports back.")
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--server", help="The Potato server's URL")
    where.add_argument("--socket", help=argparse.SUPPRESS)
    parser.add_argument("--backend",
                        help="Backend name (a type: agent entry in the "
                             "server's model_training.backends)")
    parser.add_argument("--job", help=argparse.SUPPRESS)
    parser.add_argument("--token-file",
                        help="File holding the token. Default: the "
                             "POTATO_TRAINING_TOKEN environment variable")
    parser.add_argument("--token-stdin", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--exit-on-stdin-eof", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--tls-over-socket", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--workdir", default="~/.cache/potato-training",
                        help="Where bundles and artifacts go "
                             "(default: %(default)s)")
    parser.add_argument("--python", default=sys.executable,
                        help="Interpreter for the training worker "
                             "(default: this one)")
    parser.add_argument("--once", action="store_true",
                        help="Exit after one job")
    parser.add_argument("--keep", action="store_true",
                        help="Keep each job's bundle after it finishes")
    parser.add_argument("--slurm-config",
                        help="A JSON file of SLURM settings (gres, time, "
                             "nice, partition, ...): submit each job's "
                             "worker with sbatch instead of running it here. "
                             "--workdir must then be on storage the compute "
                             "nodes share")
    parser.add_argument("--slurm-json", help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    token = _read_token(args)
    if not token:
        _say("no token: set POTATO_TRAINING_TOKEN or pass --token-file. "
             "`potato training register <backend> <config>` issues one.")
        return 2

    stop = threading.Event()
    if args.exit_on_stdin_eof:
        _watch_stdin(stop)

    def on_signal(signum, frame):  # noqa: ARG001
        stop.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, on_signal)
        except (ValueError, OSError):
            pass

    slurm = None
    if args.slurm_json or args.slurm_config:
        try:
            if args.slurm_json:
                slurm = json.loads(args.slurm_json)
            else:
                with open(os.path.expanduser(args.slurm_config)) as fh:
                    slurm = json.load(fh)
        except (OSError, ValueError) as exc:
            _say("could not read the SLURM settings: %s" % exc)
            return 2
        if not isinstance(slurm, dict):
            _say("the SLURM settings must be a JSON object")
            return 2

    client = Client(token, server=args.server or "",
                    socket_path=args.socket or "",
                    tls_over_socket=args.tls_over_socket)

    if args.job:
        try:
            _, job = client.request("GET", "%s/jobs/%s" % (API, args.job))
        except Exception as exc:  # noqa: BLE001
            _say("could not fetch job %s: %s" % (args.job, exc))
            return 1
        runner = JobRunner(client, job, args.workdir, python=args.python,
                           keep=args.keep, stop_event=stop, slurm=slurm)
        return runner.run()

    if not args.backend:
        _say("--backend is required when polling for work")
        return 2

    _say("polling %s for %r jobs" % (args.server, args.backend))
    last = 0
    query = urllib.parse.urlencode({"wait": 30,
                                    "host": platform.node()})
    while not stop.is_set():
        try:
            status, job = client.request("GET", "%s/jobs/next?%s"
                                         % (API, query), timeout=90)
        except ProtocolError as exc:
            if exc.status == 401:
                _say("the server rejected the token")
                return 2
            _say("poll failed: %s" % exc)
            stop.wait(10)
            continue
        except Exception as exc:  # noqa: BLE001
            _say("server unreachable: %s" % exc)
            stop.wait(10)
            continue
        if status == 204 or not job:
            continue
        _say("running job %s" % job.get("job_id"))
        last = JobRunner(client, job, args.workdir, python=args.python,
                         keep=args.keep, stop_event=stop, slurm=slurm).run()
        _say("job %s finished with code %d" % (job.get("job_id"), last))
        if args.once:
            return last
    return 0


if __name__ == "__main__":
    sys.exit(main())
