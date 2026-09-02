"""SSH and SFTP against a provisioned host.

Every VM provider needs the same four things — wait until the machine accepts
connections, run a command, push the bundle up, pull annotations back down — so
they live here once rather than in each provider.

The reason this exists at all rather than a pure-API bootstrap: DigitalOcean
caps cloud-init `user_data` at 64 KB, which a bundle with data files exceeds
immediately. SSH also delivers `logs` and `pull` for free, so one dependency
covers three of the five provider verbs.

paramiko is an optional dependency (`pip install potato-annotation[deploy]`),
imported lazily so that importing a provider module never requires it.
"""

from __future__ import annotations

import io
import logging
import os
import posixpath
import stat
import tarfile
import tempfile
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional

from potato.deploy.providers.base import ProviderError

logger = logging.getLogger(__name__)

# Databases that must be snapshotted rather than copied. See sqlite_safe_fetch.
WAL_DATABASES = ("project.sqlite", "datasets.sqlite")

# Regenerable, large, or a credential. None of it is worth pulling.
PULL_EXCLUDES = (".item_cache.sqlite", "admin_api_key.txt", "__pycache__")


def _paramiko():
    try:
        import paramiko
    except ImportError as exc:
        raise ProviderError(
            "This provider needs paramiko for SSH. Install it with:\n"
            "    pip install 'potato-annotation[deploy]'") from exc
    return paramiko


@dataclass
class CommandResult:
    command: str
    exit_status: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_status == 0

    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


def generate_keypair(comment: str = "potato-deploy") -> tuple:
    """A fresh ed25519 keypair, as (private_openssh, public_openssh).

    Generated per deployment and never reused, so revoking one deployment's
    access cannot affect another and nothing touches the operator's own ~/.ssh.

    Generated through `cryptography` rather than paramiko: paramiko's RSAKey and
    ECDSAKey have a `generate` classmethod but Ed25519Key does not, in any
    version. `cryptography` is a paramiko dependency, so it is present whenever
    this code can run at all.
    """
    _paramiko()      # fail with the install hint if the extra is missing
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
    except ImportError as exc:      # pragma: no cover - paramiko requires it
        raise ProviderError(
            "Generating a deploy key needs the `cryptography` package, which "
            "paramiko normally installs. Try: pip install --upgrade paramiko"
        ) from exc

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        # OpenSSH format, not PKCS8: this is what sshd and paramiko read back.
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption()).decode("ascii")
    public_blob = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH).decode("ascii")
    return private, f"{public_blob} {comment}"


class SSHSession:
    """A connection to one host, opened lazily and reused."""

    def __init__(self, host: str, *, username: str = "root",
                 private_key_pem: Optional[str] = None,
                 port: int = 22, console=None):
        self.host = host
        self.username = username
        self.private_key_pem = private_key_pem
        self.port = port
        self.console = console or logger.info
        self._client = None

    # -- connection ----------------------------------------------------

    def _load_key(self):
        paramiko = _paramiko()
        if not self.private_key_pem:
            return None
        for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                return key_class.from_private_key(io.StringIO(self.private_key_pem))
            except Exception:
                continue
        raise ProviderError("Could not parse the stored deploy key.")

    def connect(self, timeout: int = 20):
        if self._client is not None:
            return self._client
        paramiko = _paramiko()
        client = paramiko.SSHClient()
        # The host key is unknown by construction: the machine was created
        # seconds ago and has no entry anywhere. Pinning it would mean trusting
        # a fingerprint fetched over the same channel, which buys nothing.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=self.host, port=self.port, username=self.username,
                       pkey=self._load_key(), timeout=timeout,
                       allow_agent=False, look_for_keys=False)
        self._client = client
        return client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    # -- waiting -------------------------------------------------------

    def wait_for_ssh(self, timeout: int = 300, interval: int = 5) -> None:
        """Block until the host accepts an SSH connection.

        A droplet reports `active` well before sshd is listening. Conflating the
        two is the classic source of "it just hangs" reports, so this gets its
        own wait and its own message, separate from waiting on cloud-init.
        """
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                self.connect(timeout=10)
                return
            except Exception as exc:
                last_error = exc
                self._client = None
                time.sleep(interval)
        raise ProviderError(
            f"{self.host} never accepted an SSH connection within {timeout}s. "
            f"Last error: {last_error}")

    def wait_for_cloud_init(self, timeout: int = 900) -> None:
        """Block until first-boot provisioning finishes.

        Separate from wait_for_ssh: sshd comes up minutes before Docker is
        installed and the image is pulled. On failure the tail of
        cloud-init-output.log is surfaced, because the status code alone says
        nothing about what broke.
        """
        result = self.run("cloud-init status --wait || true", timeout=timeout)
        combined = result.output()
        if "status: done" in combined:
            return
        if "status: error" in combined or not result.ok:
            log = self.run(
                "tail -n 40 /var/log/cloud-init-output.log 2>/dev/null || true")
            raise ProviderError(
                "First-boot provisioning failed on the host.\n"
                f"cloud-init reported: {combined.strip() or '(no output)'}\n"
                f"Last lines of /var/log/cloud-init-output.log:\n{log.output()}")

    def wait_for_http(self, url: str, timeout: int = 600,
                      interval: int = 5) -> bool:
        """Poll a URL until it answers. Returns False rather than raising."""
        import requests

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = requests.get(url, timeout=10, verify=False)
                if response.status_code < 500:
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    # -- commands ------------------------------------------------------

    def run(self, command: str, *, timeout: int = 300,
            check: bool = False) -> CommandResult:
        client = self.connect()
        try:
            _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            status = stdout.channel.recv_exit_status()
        except Exception as exc:
            raise ProviderError(f"SSH command failed on {self.host}: {exc}") from exc
        result = CommandResult(command, status, out, err)
        if check and not result.ok:
            raise ProviderError(
                f"Command failed on {self.host} (exit {status}): {command}\n"
                f"{result.output()[:800]}")
        return result

    def stream(self, command: str) -> Iterator[str]:
        client = self.connect()
        _stdin, stdout, _stderr = client.exec_command(command, get_pty=True)
        for line in iter(stdout.readline, ""):
            yield line.rstrip("\n")

    # -- file transfer -------------------------------------------------

    def put_archive(self, local_dir: str, remote_dir: str) -> int:
        """Upload a directory as one tarball and unpack it remotely.

        One transfer rather than thousands: a bundle is typically several
        hundred small files, and per-file SFTP round trips over a fresh droplet
        turn seconds into minutes.
        """
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
            archive_path = handle.name
        try:
            with tarfile.open(archive_path, "w:gz") as archive:
                for entry in sorted(os.listdir(local_dir)):
                    archive.add(os.path.join(local_dir, entry), arcname=entry)
            size = os.path.getsize(archive_path)

            self.run(f"mkdir -p {remote_dir}", check=True)
            remote_archive = posixpath.join("/tmp", "potato-bundle.tar.gz")
            client = self.connect()
            sftp = client.open_sftp()
            try:
                sftp.put(archive_path, remote_archive)
            finally:
                sftp.close()
            self.run(f"tar -xzf {remote_archive} -C {remote_dir} && "
                     f"rm -f {remote_archive}", check=True)
            return size
        finally:
            os.unlink(archive_path)

    def put_text(self, content: str, remote_path: str, *, mode: int = 0o644) -> None:
        """Write a file remotely, setting its mode before its contents land.

        The mode matters: this carries the environment file holding the Flask
        signing key and the admin API key, and a world-readable moment is still
        a disclosure on a shared host.
        """
        client = self.connect()
        sftp = client.open_sftp()
        try:
            with sftp.file(remote_path, "w") as handle:
                handle.chmod(mode)
                handle.write(content)
        finally:
            sftp.close()

    def fetch_dir(self, remote_dir: str, local_dir: str,
                  excludes: tuple = PULL_EXCLUDES) -> List[str]:
        """Recursively download a directory. Returns the relative paths written."""
        client = self.connect()
        sftp = client.open_sftp()
        written: List[str] = []
        try:
            self._fetch_recursive(sftp, remote_dir, local_dir, excludes, "", written)
        finally:
            sftp.close()
        return written

    def _fetch_recursive(self, sftp, remote_dir, local_dir, excludes,
                         prefix, written) -> None:
        try:
            entries = sftp.listdir_attr(remote_dir)
        except IOError:
            return
        for entry in entries:
            if entry.filename in excludes:
                continue
            relative = posixpath.join(prefix, entry.filename) if prefix else entry.filename
            remote_path = posixpath.join(remote_dir, entry.filename)
            local_path = os.path.join(local_dir, *relative.split("/"))
            if stat.S_ISDIR(entry.st_mode or 0):
                os.makedirs(local_path, exist_ok=True)
                self._fetch_recursive(sftp, remote_path, local_dir, excludes,
                                      relative, written)
                continue
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            sftp.get(remote_path, local_path)
            written.append(relative)

    def sqlite_safe_fetch(self, remote_path: str, local_path: str) -> bool:
        """Snapshot a live SQLite database, then fetch the snapshot.

        Copying the file directly is the wrong thing and fails silently.
        `project.sqlite` runs in WAL mode with a live writer: the `-wal` file
        holds committed pages the main file does not yet have, so a plain copy
        yields a database that is either corrupt or missing recent work, and
        nothing reports it. Weeks later a researcher finds their memos gone.

        `.backup` takes a consistent snapshot through SQLite itself, which is
        the only correct way to copy a database with a writer attached.
        """
        probe = self.run(f"test -f {remote_path}")
        if not probe.ok:
            return False

        snapshot = f"/tmp/potato-snapshot-{os.path.basename(remote_path)}"
        result = self.run(
            f"sqlite3 {remote_path} \".backup '{snapshot}'\"", timeout=300)
        if not result.ok:
            raise ProviderError(
                f"Could not snapshot {remote_path} on the host: {result.output()}\n"
                "Refusing to copy the file directly — a WAL-mode database copied "
                "while a writer holds it is corrupt or stale, and the damage is "
                "silent.")

        client = self.connect()
        sftp = client.open_sftp()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
            sftp.get(snapshot, local_path)
        finally:
            sftp.close()
        self.run(f"rm -f {snapshot}")
        return True
