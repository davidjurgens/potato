"""Starting a training agent on another machine, so nobody has to.

:class:`SSHLauncher` does what a person would otherwise do by hand before a
remote run: connect, check the interpreter and the GPUs, copy Potato's code
over, open a way back to this server, and start
``python -m potato.training.agent`` for the one run. Then it gets out of the
way: the agent talks to the server over :mod:`potato.training.protocol` like
any other agent, and the launcher only watches whether its ssh process is
still alive.

**The way back is a unix socket.** ``ssh -R <socket>:127.0.0.1:<port>``
creates a socket on the remote host that only the connecting account can open
(mode 0600). A TCP reverse forward would put the whole annotation server on
the remote host's loopback, where every other account on a shared GPU server
could reach it.

**The token never appears in a command line.** The agent reads it from stdin,
and argv is visible to everyone in ``ps`` on a shared machine.

**The code is Potato's own.** The launcher sends the server's ``potato/``
Python sources, keyed by a hash of their content, so the remote trainer is the
same code as the server's whether it is a release or a working tree. A host
that already has that hash skips the upload.

Everything that touches ssh goes through a transport object. Tests substitute
:class:`LocalTransport`, which runs the same commands on this machine, so the
launcher's whole sequence runs in CI without an ssh server.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = ["LaunchError", "SSHLauncher", "SSHTransport", "LocalTransport",
           "code_digest", "build_code_archive", "preflight", "choose_gpus"]

Log = Callable[[str, str], None]

#: Modules the preflight reports on, so the run page can say what is missing
#: before a worker fails on it.
PROBED_MODULES = ("sklearn", "numpy", "scipy", "torch", "sentence_transformers",
                  "transformers", "peft", "trl", "PIL")

_PREFLIGHT = r'''
import importlib.util, json, os, shutil, subprocess, sys
root = os.path.abspath(os.path.expanduser(sys.argv[1]))
code, venv_key = sys.argv[2], sys.argv[3]
modules = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []
for sub in ("", "code", "jobs"):
    os.makedirs(os.path.join(root, sub), mode=0o700, exist_ok=True)
out = {"root": root, "python": "%d.%d.%d" % sys.version_info[:3],
       "executable": sys.executable,
       "code_present": os.path.isfile(os.path.join(root, "code", code, ".complete")),
       "venv": os.path.join(root, "venv-" + venv_key) if venv_key else "",
       "venv_present": bool(venv_key) and os.path.isfile(
           os.path.join(root, "venv-" + venv_key, ".complete")),
       "modules": {}, "gpus": [], "gpu_error": ""}
for name in modules:
    try:
        out["modules"][name] = importlib.util.find_spec(name) is not None
    except Exception:
        out["modules"][name] = False
smi = shutil.which("nvidia-smi")
if smi:
    try:
        text = subprocess.run(
            [smi, "--query-gpu=index,name,memory.total,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True,
            timeout=20).stdout
        for line in text.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                out["gpus"].append({"index": int(parts[0]), "name": parts[1],
                                    "total_mb": int(float(parts[2])),
                                    "free_mb": int(float(parts[3])),
                                    "util": int(float(parts[4]))})
    except Exception as exc:
        out["gpu_error"] = str(exc)
    # Compute capability on its own query: drivers before 510 reject the
    # field, and that must not lose the memory figures above.
    try:
        text = subprocess.run(
            [smi, "--query-gpu=index,compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20).stdout
        caps = dict(tuple(p.strip() for p in line.split(",")[:2])
                    for line in text.strip().splitlines() if "," in line)
        for gpu in out["gpus"]:
            if caps.get(str(gpu["index"]), "").replace(".", "").isdigit():
                gpu["compute_cap"] = caps[str(gpu["index"])]
    except Exception:
        pass
# Which GPU generations this interpreter's torch was built for. Importing
# torch costs seconds to tens of seconds, so the answer is cached per torch
# install, keyed by its version file.
torch_spec = importlib.util.find_spec("torch") if out["gpus"] else None
if torch_spec is not None and torch_spec.submodule_search_locations:
    import hashlib
    version_file = os.path.join(list(torch_spec.submodule_search_locations)[0],
                                "version.py")
    try:
        key = hashlib.sha1(("%s|%s|%s" % (sys.executable, version_file,
                            os.path.getmtime(version_file))).encode()).hexdigest()[:12]
        cache = os.path.join(root, "torch-arch-%s.json" % key)
        if os.path.isfile(cache):
            with open(cache) as fh:
                out["torch_arch"] = json.load(fh)
        else:
            text = subprocess.run(
                [sys.executable, "-c", "import json, torch; "
                 "print(json.dumps(torch.cuda.get_arch_list()))"],
                capture_output=True, text=True, timeout=180).stdout
            arch = json.loads(text.strip().splitlines()[-1])
            with open(cache, "w") as fh:
                json.dump(arch, fh)
            out["torch_arch"] = arch
    except Exception as exc:
        out["torch_arch_error"] = str(exc)
print("POTATO-PREFLIGHT " + json.dumps(out))
'''

_UNPACK = r'''
import os, shutil, sys, tarfile
dest = sys.argv[1]
partial = dest + ".partial"
shutil.rmtree(partial, ignore_errors=True)
os.makedirs(partial)
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as tar:
    for member in tar:
        if member.isfile() and not member.name.startswith(("/", "..")) \
                and "/../" not in member.name:
            tar.extract(member, partial)
open(os.path.join(partial, ".complete"), "w").close()
shutil.rmtree(dest, ignore_errors=True)
os.replace(partial, dest)
# Keep the three newest code versions; a working tree makes a new one per edit.
parent = os.path.dirname(dest)
versions = sorted((os.path.join(parent, d) for d in os.listdir(parent)
                   if not d.endswith(".partial")), key=os.path.getmtime)
for old in versions[:-3]:
    if old != dest:
        shutil.rmtree(old, ignore_errors=True)
'''

_PACK = r'''
import os, sys, tarfile
src, limit = sys.argv[1], int(sys.argv[2]) * 1024 * 1024
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as tar:
    for base, dirs, files in os.walk(src):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            if os.path.getsize(path) > limit:
                sys.stderr.write("skipped %s (over the size limit)\n" % path)
                continue
            tar.add(path, arcname=os.path.relpath(path, src))
'''

#: Bytes _PACK will send, so a slow copy can show how far along it is.
_PACK_SIZE = r'''
import os, sys
src, limit = sys.argv[1], int(sys.argv[2]) * 1024 * 1024
total = 0
for base, dirs, files in os.walk(src):
    for name in files:
        size = os.path.getsize(os.path.join(base, name))
        if size <= limit:
            total += size
print(total)
'''

#: A copy that sends nothing for this long is treated as dead.
FETCH_STALL_S = 180

_VENV = r'''
import os, subprocess, sys
dest, packages = sys.argv[1], sys.argv[2:]
subprocess.check_call([sys.executable, "-m", "venv", "--system-site-packages", dest])
python = os.path.join(dest, "bin", "python")
if packages:
    subprocess.check_call([python, "-m", "pip", "install", "--quiet"] + packages)
open(os.path.join(dest, ".complete"), "w").close()
'''


class LaunchError(RuntimeError):
    """The agent could not be started. The message is shown to the admin."""


# ---------------------------------------------------------------- code

def _package_root() -> str:
    # From this file rather than `potato.__file__`, which is None when a stray
    # site-packages/potato directory makes `potato` a namespace package.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _code_files(root: str) -> List[str]:
    files = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(names):
            if name.endswith(".py"):
                files.append(os.path.join(base, name))
    return files


def code_digest(root: Optional[str] = None) -> str:
    """A hash of every ``.py`` file in the package, path and content."""
    root = root or _package_root()
    digest = hashlib.sha256()
    for path in _code_files(root):
        digest.update(os.path.relpath(path, root).encode("utf-8"))
        digest.update(b"\0")
        with open(path, "rb") as fh:
            digest.update(fh.read())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def build_code_archive(root: Optional[str] = None) -> bytes:
    """``potato/**/*.py`` as a tar.gz, rooted so ``potato`` is importable."""
    root = root or _package_root()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in _code_files(root):
            arcname = os.path.join("potato", os.path.relpath(path, root))
            info = tar.gettarinfo(path, arcname)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with open(path, "rb") as fh:
                tar.addfile(info, fh)
    return buffer.getvalue()


# ----------------------------------------------------------- transports

class _Transport:
    """Runs commands on the target and keeps a way back to the server open."""

    host_label = ""

    def open(self, target: Optional[Tuple[str, int, str]],
             run_id: str) -> List[str]:
        """Connect; return the agent's connection arguments.

        *target* None connects without a way back, for a check."""
        raise NotImplementedError

    def run(self, argv: Sequence[str], stdin: Optional[bytes] = None,
            timeout: float = 120.0) -> Tuple[int, bytes, bytes]:
        raise NotImplementedError

    def popen(self, argv: Sequence[str], env: Dict[str, str],
              stdout, stderr) -> subprocess.Popen:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SSHTransport(_Transport):
    """One ssh ControlMaster connection carrying the forward and every command.

    One connection means one authentication -- one passphrase or agent
    confirmation -- and a forward whose lifetime is the run's.
    """

    def __init__(self, backend):
        self.backend = backend
        self.host_label = backend.host
        self._dir = tempfile.mkdtemp(prefix="potato-ssh-")
        self._control = os.path.join(self._dir, "c")
        self._master: Optional[subprocess.Popen] = None
        self._master_err = os.path.join(self._dir, "master.err")
        self.remote_socket = ""

    def _base(self) -> List[str]:
        b = self.backend
        argv = ["ssh", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=%d" % int(b.connect_timeout_s),
                "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
        if b.port:
            argv += ["-p", str(b.port)]
        if b.identity_file:
            argv += ["-i", os.path.expanduser(b.identity_file)]
        if b.user:
            argv += ["-l", b.user]
        for option in b.ssh_options:
            argv += ["-o", option]
        return argv

    def open(self, target, run_id):
        argv = self._base() + ["-M", "-S", self._control, "-N",
                               "-o", "ControlPersist=no"]
        scheme = "http"
        if target is not None:
            host, port, scheme = target
            self.remote_socket = "/tmp/potato-%s-%s.sock" % (
                run_id[-6:], uuid.uuid4().hex[:10])
            argv += ["-o", "ExitOnForwardFailure=yes",
                     "-o", "StreamLocalBindUnlink=yes",
                     "-o", "StreamLocalBindMask=0177",
                     "-R", "%s:%s:%d" % (self.remote_socket, host, port)]
        argv.append(self.backend.host)
        with open(self._master_err, "wb") as err:
            self._master = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=err, start_new_session=True)

        deadline = time.time() + float(self.backend.connect_timeout_s) + 15
        while time.time() < deadline:
            if self._master.poll() is not None:
                raise LaunchError("ssh to %s failed: %s" % (
                    self.backend.host, _read(self._master_err)
                    or "exit code %d" % self._master.returncode))
            check = subprocess.run(
                ["ssh", "-S", self._control, "-O", "check",
                 self.backend.host], capture_output=True)
            if check.returncode == 0:
                break
            time.sleep(0.3)
        else:
            self.close()
            raise LaunchError("Timed out connecting to %s" % self.backend.host)

        args = ["--socket", self.remote_socket]
        if scheme == "https":
            args.append("--tls-over-socket")
        return args

    def _wrap(self, argv: Sequence[str],
              env: Optional[Dict[str, str]] = None) -> List[str]:
        command = " ".join(shlex.quote(a) for a in argv)
        if env:
            command = "env %s %s" % (" ".join(
                "%s=%s" % (k, shlex.quote(v)) for k, v in env.items()),
                command)
        return ["ssh", "-S", self._control, "-o", "BatchMode=yes",
                self.backend.host, command]

    def run(self, argv, stdin=None, timeout=120.0):
        try:
            done = subprocess.run(self._wrap(argv), input=stdin,
                                  capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise LaunchError("A command on %s timed out after %d s"
                              % (self.backend.host, timeout))
        return done.returncode, done.stdout, done.stderr

    def popen(self, argv, env, stdout, stderr):
        return subprocess.Popen(self._wrap(argv, env), stdin=subprocess.PIPE,
                                stdout=stdout, stderr=stderr,
                                start_new_session=True)

    def close(self):
        if self._master is not None and self._master.poll() is None:
            if self.remote_socket:
                # ssh unlinks a stale socket before binding, never after, so
                # each run would otherwise leave one in the remote /tmp.
                subprocess.run(self._wrap(["rm", "-f", self.remote_socket]),
                               capture_output=True, timeout=30)
            subprocess.run(["ssh", "-S", self._control, "-O", "exit",
                            self.backend.host], capture_output=True)
            try:
                self._master.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._master.kill()
        shutil.rmtree(self._dir, ignore_errors=True)


class LocalTransport(_Transport):
    """The same commands, run here. For tests of the launch sequence."""

    host_label = "localhost"

    def open(self, target, run_id):
        if target is None:
            return []
        host, port, scheme = target
        return ["--server", "%s://%s:%d" % (scheme, host, port)]

    def run(self, argv, stdin=None, timeout=120.0):
        try:
            done = subprocess.run(list(argv), input=stdin,
                                  capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            # What a shell over ssh reports for a missing command.
            return 127, b"", ("%s: command not found" % exc.filename).encode()
        return done.returncode, done.stdout, done.stderr

    def popen(self, argv, env, stdout, stderr):
        full = dict(os.environ)
        full.update(env)
        return subprocess.Popen(list(argv), env=full, stdin=subprocess.PIPE,
                                stdout=stdout, stderr=stderr,
                                start_new_session=True)


# ------------------------------------------------------------ preflight

def preflight(transport: _Transport, python: str, remote_dir: str,
              code: str, venv_key: str = "") -> Dict[str, Any]:
    """Interpreter, GPUs and cached code on the target, in one round trip."""
    rc, out, err = transport.run(
        [python, "-c", _PREFLIGHT, remote_dir, code, venv_key,
         ",".join(PROBED_MODULES)], timeout=60)
    for line in out.decode("utf-8", "replace").splitlines():
        if line.startswith("POTATO-PREFLIGHT "):
            return json.loads(line[len("POTATO-PREFLIGHT "):])
    message = err.decode("utf-8", "replace").strip()
    if rc == 127 or "not found" in message:
        raise LaunchError("%s was not found on %s. Set python: in the "
                          "backend to the interpreter to use."
                          % (python, transport.host_label))
    raise LaunchError("Could not check %s: %s"
                      % (transport.host_label, message[-1500:]
                         or "exit code %d" % rc))


def gpu_supported(compute_cap: Optional[str],
                  arch_list: Optional[List[str]]) -> Optional[bool]:
    """Whether a torch built for *arch_list* can run on this GPU, or None
    when either side is unknown.

    A cubin for ``sm_XY`` runs on any GPU of major version X and minor
    version Y or later, and PTX for ``compute_XY`` is compiled at load time
    for any GPU from XY up.
    """
    if not compute_cap or not arch_list:
        return None
    try:
        major, minor = (int(p) for p in str(compute_cap).split(".")[:2])
    except ValueError:
        return None
    for arch in arch_list:
        kind, _, digits = str(arch).partition("_")
        if not digits.isdigit() or len(digits) < 2:
            continue
        a_major, a_minor = int(digits[:-1]), int(digits[-1])
        if kind == "sm" and a_major == major and a_minor <= minor:
            return True
        if kind == "compute" and (a_major, a_minor) <= (major, minor):
            return True
    return False


def choose_gpus(setting: str, gpus: List[Dict[str, Any]],
                min_free_mb: int,
                arch_list: Optional[List[str]] = None) -> Tuple[str, str]:
    """``(CUDA_VISIBLE_DEVICES, description)``.

    ``auto`` takes the GPU with the most free memory, because on a shared
    server the least-busy card by utilisation can still be full. It passes
    over a GPU the remote torch was not built for: burger's TITAN V (sm_70)
    has no kernels in a torch built for sm_75 and up, and a run placed on it
    fails at the first CUDA call.
    """
    setting = (setting or "auto").strip().lower()
    if setting == "none":
        return "", "CPU only (gpus: none)"
    if setting == "auto":
        if not gpus:
            return "", "no GPU found; running on the CPU"
        unusable = [g for g in gpus
                    if gpu_supported(g.get("compute_cap"), arch_list) is False]
        usable = [g for g in gpus if g not in unusable]
        if not usable:
            raise LaunchError(
                "This host's torch has no kernels for any of its GPUs (%s; "
                "torch was built for %s). Install a torch build for them, or "
                "set gpus: none." % (
                    "; ".join("%d %s, compute %s" % (g["index"], g["name"],
                                                    g.get("compute_cap"))
                              for g in gpus), ", ".join(arch_list or [])))
        gpus = usable
        best = max(gpus, key=lambda g: g["free_mb"])
        if best["free_mb"] < min_free_mb:
            listing = "; ".join("%d %s: %d MB free" % (g["index"], g["name"],
                                                      g["free_mb"])
                                for g in gpus)
            raise LaunchError(
                "No GPU has %d MB free (%s). Wait, lower min_free_gpu_mb, or "
                "pin one with gpus:." % (min_free_mb, listing))
        return str(best["index"]), "GPU %d, %s, %.1f GB free" % (
            best["index"], best["name"], best["free_mb"] / 1024.0)
    known = {g["index"]: g for g in gpus}
    chosen = [int(p) for p in setting.split(",") if p.strip()]
    missing = [i for i in chosen if gpus and i not in known]
    if missing:
        raise LaunchError("GPU %s not found; this host has %s"
                          % (", ".join(map(str, missing)),
                             ", ".join(str(i) for i in sorted(known)) or
                             "none"))
    unusable = [i for i in chosen if i in known and gpu_supported(
        known[i].get("compute_cap"), arch_list) is False]
    if unusable:
        raise LaunchError(
            "GPU %s (compute %s) is not one this host's torch was built for "
            "(%s). Pin another GPU, or use gpus: auto."
            % (", ".join(map(str, unusable)),
               ", ".join(str(known[i].get("compute_cap")) for i in unusable),
               ", ".join(arch_list or [])))
    names = ", ".join("%d %s" % (i, known[i]["name"]) if i in known
                      else str(i) for i in chosen)
    return ",".join(map(str, chosen)), "GPU %s" % names


# ------------------------------------------------------------- launcher

class SSHLauncher:
    """Starts and tears down the agent for one run on an ssh backend."""

    def __init__(self, backend, root: str, log: Optional[Log] = None,
                 step: Optional[Callable[[str], None]] = None,
                 transport: Optional[_Transport] = None):
        self.backend = backend
        self.root = root
        self._log = log or (lambda level, msg: None)
        self._step = step or (lambda text: None)
        if transport is None:
            transport = (LocalTransport() if backend._transport == "local"
                         else SSHTransport(backend))
        self.transport = transport
        self.info: Dict[str, Any] = {}
        self.host_description = ""
        self._agent: Optional[subprocess.Popen] = None
        self._agent_err = ""
        self._python = backend.python
        self._lock = threading.Lock()

    # -- start ---------------------------------------------------------

    def start(self, run_id: str, token: str,
              target: Tuple[str, int, str]) -> None:
        b = self.backend
        self._step("connecting to %s" % b.host)
        connection = self.transport.open(target, run_id)

        self._step("checking %s" % b.host)
        code = code_digest()
        venv_key = ""
        if b.packages:
            venv_key = hashlib.sha256(
                ("%s|%s" % (b.python, " ".join(sorted(b.packages))))
                .encode("utf-8")).hexdigest()[:12]
        info = preflight(self.transport, b.python, b.remote_dir, code,
                         venv_key)
        self.info = info
        major, minor = (int(x) for x in info["python"].split(".")[:2])
        if (major, minor) < (3, 8):
            raise LaunchError("%s on %s is Python %s; the agent needs 3.8 or "
                              "newer" % (b.python, b.host, info["python"]))

        if not info["code_present"]:
            self._step("copying Potato's code to %s" % b.host)
            dest = os.path.join(info["root"], "code", code)
            rc, _, err = self.transport.run(
                [b.python, "-c", _UNPACK, dest],
                stdin=build_code_archive(), timeout=300)
            if rc != 0:
                raise LaunchError("Could not copy code to %s: %s"
                                  % (b.host, _text(err)))

        if venv_key:
            if not info["venv_present"]:
                self._step("installing %s on %s" % (", ".join(b.packages),
                                                   b.host))
                rc, _, err = self.transport.run(
                    [b.python, "-c", _VENV, info["venv"]] + b.packages,
                    timeout=1800)
                if rc != 0:
                    raise LaunchError("Could not install %s on %s: %s"
                                      % (", ".join(b.packages), b.host,
                                         _text(err)))
            self._python = os.path.join(info["venv"], "bin", "python")

        visible, gpu_text = choose_gpus(b.gpus, info.get("gpus") or [],
                                        int(b.min_free_gpu_mb),
                                        info.get("torch_arch"))
        self.host_description = "%s (%s)" % (b.host, gpu_text)
        missing = [m for m, ok in (info.get("modules") or {}).items()
                   if not ok]
        self._log("info", "%s: Python %s at %s; %s%s" % (
            b.host, info["python"], info["executable"], gpu_text,
            "; not installed there: %s" % ", ".join(missing)
            if missing else ""))

        env = {"PYTHONPATH": os.path.join(info["root"], "code", code),
               "PYTHONUNBUFFERED": "1",
               "CUDA_VISIBLE_DEVICES": visible}
        if b.num_threads:
            for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
                        "OPENBLAS_NUM_THREADS"):
                env[var] = str(b.num_threads)
        extra = dict(b.env)
        if extra.get("PYTHONPATH"):
            # Potato's code stays first, so a stray copy cannot shadow it.
            extra["PYTHONPATH"] = env["PYTHONPATH"] + os.pathsep \
                + extra["PYTHONPATH"]
        env.update(extra)

        argv = [self._python, "-m", "potato.training.agent"] + connection + [
            "--job", run_id, "--workdir", info["root"], "--python",
            self._python, "--token-stdin", "--exit-on-stdin-eof"]
        if b.keep_remote:
            argv.append("--keep")

        self._step("starting the agent on %s" % b.host)
        run_dir = os.path.join(self.root, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        self._agent_err = os.path.join(run_dir, "agent.log")
        err = open(self._agent_err, "wb")
        try:
            self._agent = self.transport.popen(argv, env, stdout=err,
                                               stderr=err)
        finally:
            err.close()
        try:
            self._agent.stdin.write((token + "\n").encode("utf-8"))
            self._agent.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise LaunchError("The agent on %s exited at once: %s %s"
                              % (b.host, exc, self.agent_stderr_tail()))
        self._step("waiting for the agent on %s" % b.host)

    # -- watching ------------------------------------------------------

    def agent_exited(self) -> bool:
        return self._agent is not None and self._agent.poll() is not None

    def agent_returncode(self) -> Optional[int]:
        return None if self._agent is None else self._agent.poll()

    def agent_stderr_tail(self, limit: int = 1500) -> str:
        return _read(self._agent_err)[-limit:] if self._agent_err else ""

    def kill_agent(self) -> None:
        """End the agent's ssh session; the agent stops on stdin EOF."""
        agent = self._agent
        if agent is None or agent.poll() is not None:
            return
        try:
            agent.stdin.close()
        except Exception:
            pass
        try:
            agent.wait(timeout=10)
        except subprocess.TimeoutExpired:
            agent.kill()

    # -- after ---------------------------------------------------------

    def _job_dir(self, run_id: str) -> str:
        from potato.training.agent import _job_dir_name
        return os.path.join(self.info.get("root", ""), "jobs",
                            _job_dir_name(run_id))

    def fetch_artifacts(self, run_id: str, dest: str) -> List[str]:
        """Copy the run's artifact directory back. Returns the file names.

        Streamed to a file and then unpacked, never held in memory: a
        fine-tuned model is hundreds of megabytes to gigabytes, and this runs
        inside the annotation server. There is no overall time limit, since
        a large model over a slow link legitimately takes many minutes;
        instead the copy fails when it sends nothing for ``FETCH_STALL_S``.
        """
        b = self.backend
        source = os.path.join(self._job_dir(run_id), "artifacts")
        limit = str(int(b.max_artifact_mb))
        expected = 0
        rc, out, _ = self.transport.run([self._python, "-c", _PACK_SIZE,
                                         source, limit], timeout=60)
        if rc == 0:
            try:
                expected = int(_text(out).split()[-1])
            except (ValueError, IndexError):
                expected = 0

        os.makedirs(dest, exist_ok=True)
        archive = os.path.join(os.path.dirname(os.path.abspath(dest)),
                               "artifacts.tar.gz.partial")
        errors = archive + ".err"
        self._step("fetching artifacts from %s%s"
                   % (b.host, " (%s)" % _megabytes(expected) if expected
                      else ""))
        try:
            with open(archive, "wb") as fh, open(errors, "wb") as err_fh:
                process = self.transport.popen(
                    [self._python, "-c", _PACK, source, limit], {}, fh,
                    err_fh)
                if process.stdin is not None:
                    process.stdin.close()
                received, last_change = 0, time.time()
                while process.poll() is None:
                    time.sleep(1.0)
                    size = os.path.getsize(archive)
                    if size != received:
                        received, last_change = size, time.time()
                        self._step("fetching artifacts from %s: %s%s"
                                   % (b.host, _megabytes(size),
                                      " of about %s" % _megabytes(expected)
                                      if expected else ""))
                    elif time.time() - last_change > FETCH_STALL_S:
                        process.kill()
                        process.wait()
                        raise LaunchError(
                            "The copy from %s sent nothing for %d s after "
                            "%s" % (b.host, FETCH_STALL_S, _megabytes(size)))
            stderr = _read(errors)
            if process.returncode != 0:
                raise LaunchError(stderr or "the copy exited with code %d"
                                  % process.returncode)
            if stderr:
                self._log("warning", stderr)

            names = []
            with tarfile.open(archive, mode="r:gz") as tar:
                for member in tar:
                    target = os.path.realpath(os.path.join(dest, member.name))
                    if not member.isfile() or not target.startswith(
                            os.path.realpath(dest) + os.sep):
                        continue
                    tar.extract(member, dest)
                    names.append(member.name)
            return names
        finally:
            for path in (archive, errors):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def close(self, run_id: str) -> None:
        try:
            if self._agent is not None and self._agent.poll() is None:
                self.kill_agent()
            if self.info.get("root") and not self.backend.keep_remote:
                job_dir = self._job_dir(run_id)
                self.transport.run([self._python, "-c",
                                    "import shutil,sys; shutil.rmtree("
                                    "sys.argv[1], ignore_errors=True)",
                                    job_dir], timeout=60)
        finally:
            self.transport.close()


def _megabytes(n: int) -> str:
    mb = n / 1048576.0
    return ("%.0f MB" if mb >= 10 else "%.1f MB") % mb


def _read(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _text(raw: bytes, limit: int = 1500) -> str:
    return raw.decode("utf-8", "replace").strip()[-limit:]


def check_backend(backend, transport: Optional[_Transport] = None
                  ) -> Dict[str, Any]:
    """Connect to an ssh backend and report what a run would get there.

    ``{"ok": bool, "message": str, "python": ..., "gpus": [...],
    "chosen": str, "missing": [...]}``. Never raises for an unreachable or
    unsuitable host; that is what the report is for.
    """
    if transport is None:
        transport = (LocalTransport() if backend._transport == "local"
                     else SSHTransport(backend))
    report: Dict[str, Any] = {"ok": False, "backend": backend.name,
                              "host": backend.host}
    try:
        transport.open(None, "check")
        info = preflight(transport, backend.python, backend.remote_dir,
                         code_digest())
        report.update({
            "python": info["python"], "executable": info["executable"],
            "gpus": info.get("gpus") or [],
            "missing": sorted(m for m, ok in
                              (info.get("modules") or {}).items() if not ok),
            "code_cached": info["code_present"],
        })
        try:
            for gpu in report["gpus"]:
                gpu["supported"] = gpu_supported(gpu.get("compute_cap"),
                                                 info.get("torch_arch"))
            report["torch_arch"] = info.get("torch_arch") or []
            _, report["chosen"] = choose_gpus(
                backend.gpus, report["gpus"], int(backend.min_free_gpu_mb),
                info.get("torch_arch"))
            report["ok"] = True
            report["message"] = "%s is reachable: Python %s, %s" % (
                backend.host, info["python"], report["chosen"])
        except LaunchError as exc:
            report["message"] = str(exc)
    except LaunchError as exc:
        report["message"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        report["message"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            transport.close()
        except Exception:
            pass
    return report
