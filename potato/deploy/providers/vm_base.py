"""The shared half of every virtual-machine deploy target.

DigitalOcean, Lightsail, EC2, Hetzner, Vultr, Linode and OpenStack all do the
same thing once a machine exists: wait for SSH, wait for cloud-init, upload the
bundle, write the environment file, start Potato and Caddy, wait for HTTPS. What
differs is how the machine, its key, its disk and its firewall are made. That
split is this module: `VMProvider` owns the lifecycle, a subclass owns the API.

`create` is a sequence of waits as much as a sequence of calls. Server-active,
SSH-ready and cloud-init-done are three different moments minutes apart, and
treating them as one is what makes tools in this category appear to hang. Each
gets its own wait and its own message.

TLS uses Let's Encrypt certificates issued for the machine's bare IPv4 address
(generally available since 2026-01-15), or a real hostname when there is one.
See templates/Caddyfile.j2 for why sslip.io is not an option.

Where the data lives. Without a volume the task directory is ``APP_DIR`` on the
root disk. With one, it is ``VOLUME_APP_DIR`` on the volume. An earlier version
mounted the volume at ``DATA_DIR`` but kept the task, and so every annotation,
on the root disk; the volume held only certificates. The directory a deployment
uses is recorded in ``provider_ref['app_dir']`` at creation, so a deployment
made before the fix keeps the layout it was built with.
"""

from __future__ import annotations

import os
import posixpath
import shlex
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from potato.deploy.providers.base import (
    deploy_command,
    Action,
    DeployPlan,
    DeploymentStatus,
    DeploySpec,
    Provider,
    ProviderError,
    PullResult,
)
from potato.deploy.remote import SSHSession, WAL_DATABASES, generate_keypair
from potato.deploy.state import DeploymentRecord, SecretStore

DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
CADDY_IMAGE = "caddy:2.11.3-alpine"

APP_DIR = "/opt/potato/app"
DATA_DIR = "/opt/potato/data"
#: The task directory when a volume is attached: on the volume, not the root disk.
VOLUME_APP_DIR = posixpath.join(DATA_DIR, "app")
ENV_FILE = "/opt/potato/potato.env"
APP_PORT = 8000
CONTAINER = "potato"
CADDY_CONTAINER = "potato-caddy"

LETSENCRYPT_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"

# 1 GB cannot install Docker and run the image without swapping. The image is
# ~840 MB, and Potato's numpy/pandas/scipy working set is not small.
MIN_RECOMMENDED_MEMORY_MB = 2048

#: Inbound ports every VM opens. 8000 is never among them: the container binds
#: it to 127.0.0.1 and Caddy reaches it over loopback.
PUBLIC_PORTS = (22, 80, 443)

#: Written into the Caddyfile at first boot, before the address is known.
IP_PLACEHOLDER = "REPLACED_AFTER_IP"


def render_template(name: str, **context) -> str:
    """Render one of the templates under potato/deploy/templates."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    template_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "templates")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,      # a missing variable must not render as ""
        keep_trailing_newline=True,
        trim_blocks=False,
    )
    return environment.get_template(name).render(**context)


def app_dir_for(volume: bool) -> str:
    return VOLUME_APP_DIR if volume else APP_DIR


SERVICE_UNIT_PATH = "/etc/systemd/system/potato.service"


def render_potato_service(spec: DeploySpec, app_dir: str) -> str:
    """The systemd unit that runs the container. cloud-init installs it on
    first boot, and an update rewrites it so a new --image takes effect."""
    return render_template(
        "potato.service.j2",
        container_name=CONTAINER, env_file=ENV_FILE, app_port=APP_PORT,
        app_dir=app_dir, data_dir=DATA_DIR, image=spec.image or DEFAULT_IMAGE,
        deployment_name=spec.name)


#: Settings fixed when the machine is created. An update cannot change them,
#: and recording the requested value anyway left the record describing a
#: machine that did not exist.
IMMUTABLE_SETTINGS = (("size", "--size"), ("region", "--region"),
                      ("volume_gb", "--volume-gb"), ("domain", "--domain"))


def changed_settings(spec: DeploySpec, record) -> List[str]:
    """Flags this spec sets to something other than what the record holds."""
    changed = []
    for field, flag in IMMUTABLE_SETTINGS:
        wanted = getattr(spec, field)
        if wanted is None:
            continue
        had = (record.spec or {}).get(field)
        if had is not None and str(wanted) != str(had):
            changed.append(f"{flag} {wanted} (it has {had})")
    return changed


def build_cloud_init(spec: DeploySpec, *, public_host: str,
                     volume_device: Optional[str] = None,
                     app_dir: Optional[str] = None,
                     ssh_authorized_key: Optional[str] = None,
                     deploy_user: Optional[str] = None) -> str:
    """Render the full first-boot configuration.

    Pure: no credentials, no I/O, no network. That is what lets a test assert
    the exact firewall rules and unit files that a real deploy would install.
    """
    image = spec.image or DEFAULT_IMAGE
    app_dir = app_dir or app_dir_for(bool(volume_device))
    cert_dir = posixpath.join(DATA_DIR, "caddy") if volume_device else "/var/lib/caddy"

    potato_service = render_potato_service(spec, app_dir)

    caddyfile = render_template(
        "Caddyfile.j2",
        domain=spec.domain, public_host=public_host, app_port=APP_PORT,
        cert_dir=cert_dir, acme_directory=LETSENCRYPT_DIRECTORY,
        acme_email=spec.extra.get("acme_email"))

    caddy_service = render_template(
        "caddy.service.j2",
        container_name=CADDY_CONTAINER, caddy_image=CADDY_IMAGE,
        cert_dir=cert_dir, app_port=APP_PORT)

    return render_template(
        "cloud-init.yaml.j2",
        image=image, caddy_image=CADDY_IMAGE, app_dir=app_dir, data_dir=DATA_DIR,
        app_port=APP_PORT, volume_device=volume_device,
        potato_service=potato_service, caddyfile=caddyfile,
        caddy_service=caddy_service, ssh_authorized_key=ssh_authorized_key,
        deploy_user=deploy_user)


def prepare_volume_script(candidates: List[str], app_dir: str) -> str:
    """Format-if-blank, mount and hand over an attached volume. Idempotent.

    Run over SSH once the provider reports the disk attached, never from
    cloud-init: first boot races the attach, and a mount that fails under
    ``nofail`` leaves the task on the root disk with nothing reporting it.

    ``candidates`` are the paths the disk may appear at, first match wins. On
    Nitro hardware (Lightsail, EC2) a disk attached as /dev/xvdf shows up as
    /dev/nvme1n1, so a single requested path is not enough. fstab records the
    filesystem UUID, which survives the device being renamed on reboot.
    """
    paths = " ".join(candidates)
    return f"""set -e
dev=""
for attempt in $(seq 1 90); do
  for candidate in {paths}; do
    if [ -b "$candidate" ]; then dev="$candidate"; break 2; fi
  done
  sleep 2
done
if [ -z "$dev" ]; then
  echo "the volume never appeared at any of: {paths}" >&2
  exit 1
fi
mkdir -p {DATA_DIR}
if ! mountpoint -q {DATA_DIR}; then
  blkid "$dev" >/dev/null 2>&1 || mkfs.ext4 -F "$dev"
  uuid=$(blkid -s UUID -o value "$dev")
  grep -q " {DATA_DIR} " /etc/fstab || echo "UUID=$uuid {DATA_DIR} ext4 defaults,nofail,discard 0 2" >> /etc/fstab
  mount {DATA_DIR}
fi
mkdir -p {DATA_DIR}/caddy {app_dir}
chown -R 1000:1000 {DATA_DIR}
"""


def render_env_file(env: Dict[str, str]) -> str:
    """systemd EnvironmentFile format: KEY=value, one per line, no export."""
    lines = []
    for key in sorted(env):
        value = str(env[key])
        if "\n" in value:
            raise ProviderError(
                f"Environment value for {key} contains a newline, which systemd "
                "cannot read from an EnvironmentFile.")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def https_fallback(record, dest: str, console):
    """Pull over the admin archive endpoint, or None when that is not possible."""
    from potato.deploy.pull import pull_over_https

    config_path = record.spec.get("config_path")
    if not config_path or not record.url:
        return None
    admin_key = SecretStore(config_path).get(record.name, "admin_api_key")
    if not admin_key:
        return None
    console("No usable SSH key; falling back to the admin archive over HTTPS.")
    return pull_over_https(record.url, admin_key, dest, console=console)


def record_app_dir(record) -> str:
    """The task directory on this deployment's host."""
    return (record.provider_ref or {}).get("app_dir") or APP_DIR


class VMProvider(Provider):
    """One VM running the published image behind Caddy, reached over SSH."""

    requires = ("paramiko",)
    install_extra = "deploy"
    ephemeral_fs = False
    public = True
    supports_logs = True
    supports_pull = True

    #: The login a fresh image accepts the deploy key for.
    ssh_user = "root"
    #: When set, cloud-init creates this sudo user with the deploy key, for
    #: images whose default login is not known in advance.
    deploy_user: Optional[str] = None
    #: What the provider calls a machine, for messages.
    server_noun = "server"
    #: The provider_ref key whose presence means the machine was created.
    server_id_key = "server_id"
    default_region: Optional[str] = None
    default_size: Optional[str] = None
    #: Largest user_data the provider accepts, in bytes.
    user_data_limit = 64 * 1024
    #: Where to look when something needs a human: "the DigitalOcean console".
    console_name = "the provider's console"

    # -- hooks every subclass implements -------------------------------

    def _api(self, region: Optional[str] = None):
        """An API client. ``region`` matters for regional APIs (AWS, OpenStack)."""
        raise NotImplementedError

    def _check_account(self, api) -> None:
        """Raise ProviderError when the account cannot create anything."""

    def _provider_actions(self, spec: DeploySpec, *, region: str, size: str,
                          user_data: str) -> List[Action]:
        """The API half of the plan: key, disk, server, firewall, wait.active."""
        raise NotImplementedError

    def _create_infrastructure(self, api, spec: DeploySpec, record, store, *,
                               region: str, size: str, public_key: str,
                               user_data_for: Callable[[Optional[str]], str]) -> str:
        """Create the machine and everything around it; return its IPv4.

        Persist each resource id with ``store.upsert(record)`` the moment it
        exists. ``user_data_for(volume_device)`` renders cloud-init once the
        volume's device path is known.
        """
        raise NotImplementedError

    def _server_state(self, api, record) -> Tuple[str, Dict[str, Any]]:
        """``("active", raw)`` when serving, ``("absent", {})`` when gone."""
        raise NotImplementedError

    def _destroy_infrastructure(self, api, record, *, keep_data: bool) -> None:
        raise NotImplementedError

    def memory_mb(self, size: str) -> Optional[int]:
        return None

    def estimate_cost(self, size: str, volume_gb: Optional[int]) -> Optional[float]:
        return None

    def cost_note(self, size: str, volume_gb: Optional[int]) -> Optional[str]:
        """A price line for providers that do not bill in dollars."""
        return None

    def public_host(self, spec: DeploySpec, record, ip: str) -> str:
        """The name the certificate is issued for: a domain, else the IP."""
        return spec.domain or ip

    def host_placeholder(self, spec: DeploySpec) -> str:
        return spec.domain or f"<{self.server_noun}-ipv4>"

    def record_spec(self, spec: DeploySpec) -> Dict[str, Any]:
        """The parts of the spec later commands need, without any secret."""
        return {
            "config_path": os.path.abspath(spec.config_path),
            "domain": spec.domain,
            "region": spec.region or self.default_region,
            "size": spec.size or self.default_size,
            "volume_gb": spec.volume_gb,
            "output_annotation_dir": spec.extra.get("output_annotation_dir",
                                                    "annotation_output"),
        }

    # -- plan ----------------------------------------------------------

    def refusal(self, spec: DeploySpec, bundle, existing=None) -> Optional[str]:
        record = existing or spec.extra.get("existing_record")
        if record is None or not record.provider_ref.get(self.server_id_key):
            return None
        changed = changed_settings(spec, record)
        if not changed:
            return None
        return (f"'{record.name}' already has a {self.server_noun}, and an update "
                f"cannot change {', '.join(changed)}. To change it, run "
                f"`potato deploy pull` and then `potato deploy destroy`, and "
                "deploy again; or leave the flag off to update in place.")

    def _update_plan(self, spec: DeploySpec, bundle, record) -> DeployPlan:
        """What `up` does to a machine that already exists."""
        image = spec.image or DEFAULT_IMAGE
        size = (record.spec or {}).get("size") or self.default_size
        plan = DeployPlan(
            result_url_pattern=record.url or "",
            estimated_cost_usd_month=self.estimate_cost(
                size, (record.spec or {}).get("volume_gb")))
        plan.actions = [
            Action("ssh.connect", f"connect to the existing {self.server_noun} "
                   f"at {self._ssh_host(record)}"),
            Action("ssh.unit", f"rewrite potato.service to run {image}"),
            Action("docker.pull", f"docker pull {image}"),
            Action("ssh.upload", f"upload the bundle to {record_app_dir(record)}",
                   {"files": bundle.file_count if bundle else None}),
            Action("ssh.env", f"rewrite {ENV_FILE} at mode 0600"),
            Action("ssh.start", "restart potato and caddy"),
            Action("wait.http", f"poll {record.url}/health"),
        ]
        plan.warnings.append(
            f"This updates the existing {self.server_noun}; size, region, volume "
            "and domain stay as they are.")
        return plan

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        existing = spec.extra.get("existing_record")
        if existing is not None and existing.provider_ref.get(self.server_id_key):
            return self._update_plan(spec, bundle, existing)
        region = spec.region or self.default_region
        size = spec.size or self.default_size
        host = self.host_placeholder(spec)
        app_dir = app_dir_for(bool(spec.volume_gb))
        user_data = build_cloud_init(
            spec, public_host=host,
            volume_device=self.volume_device_hint(spec) if spec.volume_gb else None,
            app_dir=app_dir)
        env = self.runtime_env(spec, spec.extra.get("generated"))

        plan = DeployPlan(result_url_pattern=f"https://{host}",
                          estimated_cost_usd_month=self.estimate_cost(size, spec.volume_gb))
        plan.actions = list(self._provider_actions(
            spec, region=region, size=size, user_data=user_data))
        plan.actions += [
            Action("wait.ssh", "poll until the host accepts an SSH connection"),
            Action("wait.cloud_init",
                   "wait for docker install and image pull to finish"),
            Action("ssh.upload", f"upload the bundle to {app_dir}",
                   {"files": bundle.file_count if bundle else None,
                    "bytes": bundle.total_bytes if bundle else None}),
            Action("ssh.env", f"write {ENV_FILE} at mode 0600",
                   # Keys only. The values include the Flask signing key and the
                   # admin API key, and a plan is printed to a terminal.
                   {"env_keys": sorted(env)}),
            Action("ssh.start", "systemctl start potato and caddy"),
            Action("wait.http", f"poll https://{host}/health"),
        ]

        note = self.cost_note(size, spec.volume_gb)
        if note:
            plan.warnings.append(note)
        elif plan.estimated_cost_usd_month is None:
            plan.warnings.append(
                f"No price is known for {self.name} size {size!r}; check the "
                "provider's pricing before confirming.")
        if len(user_data.encode("utf-8")) > self.user_data_limit:
            plan.warnings.append(
                f"The first-boot script is {len(user_data)} bytes; {self.name} "
                f"accepts at most {self.user_data_limit}. This is a bug.")
        memory = self.memory_mb(size)
        if memory is not None and memory < MIN_RECOMMENDED_MEMORY_MB:
            plan.warnings.append(
                f"{size} has {memory} MB of RAM. The image is ~840 MB and Potato's "
                "working set is numpy/pandas/scipy; expect swapping. 2 GB is the "
                "smallest size worth using.")
        if not spec.domain and not self.has_hostname(spec):
            plan.warnings.append(
                f"No --domain, so TLS uses a Let's Encrypt certificate for the "
                f"{self.server_noun}'s IP address. These are valid ~6 days rather "
                "than 90, so check `potato deploy status` if the study runs "
                "unattended.")
        if spec.volume_gb is None:
            plan.warnings.append(
                f"No --volume-gb. Annotations live on the {self.server_noun}'s own "
                f"disk, which is destroyed with the {self.server_noun}. Pull before "
                "you destroy.")
        if not bundle:
            plan.warnings.append("No bundle was built; this plan cannot run.")
        return plan

    def has_hostname(self, spec: DeploySpec) -> bool:
        """True when the provider supplies a DNS name, so no IP certificate."""
        return False

    def volume_device_hint(self, spec: DeploySpec) -> Optional[str]:
        """The device path a volume will appear at, for the dry-run plan."""
        return "<volume-device>"

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        missing = self.check_requirements()
        if missing:
            raise ProviderError(
                f"The {self.name} provider needs {', '.join(missing)}. "
                f"Install with: pip install 'potato-annotation[{self.install_extra}]'")

        api = self._api(spec.region or self.default_region)
        self._check_account(api)

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        if record.provider_ref.get(self.server_id_key):
            return self._update(api, spec, bundle, record, store)
        return self._provision(api, spec, bundle, record, store)

    def _provision(self, api, spec, bundle, record, store) -> DeploymentRecord:
        region = spec.region or self.default_region
        size = spec.size or self.default_size
        secrets = SecretStore(spec.config_path)
        app_dir = app_dir_for(bool(spec.volume_gb))

        record.status = "creating"
        record.provider_ref.setdefault("tag", f"potato-{spec.name}")
        record.provider_ref["region"] = region
        record.provider_ref["app_dir"] = app_dir
        record.spec.update(self.record_spec(spec))
        store.upsert(record)

        self.console("Generating a deploy key...")
        private_pem, public_key = generate_keypair(f"potato-{spec.name}")
        secrets.put(spec.name, "ssh_private_key", private_pem)

        def user_data_for(volume_device: Optional[str]) -> str:
            rendered = build_cloud_init(
                spec, public_host=spec.domain or IP_PLACEHOLDER,
                volume_device=volume_device, app_dir=app_dir,
                ssh_authorized_key=public_key, deploy_user=self.deploy_user)
            if len(rendered.encode("utf-8")) > self.user_data_limit:
                raise ProviderError(
                    f"The first-boot script is {len(rendered)} bytes and "
                    f"{self.name} accepts {self.user_data_limit}. This is a bug.")
            return rendered

        try:
            ip = self._create_infrastructure(
                api, spec, record, store, region=region, size=size,
                public_key=public_key, user_data_for=user_data_for)
            record.provider_ref["ipv4"] = ip
            host = self.public_host(spec, record, ip)
            record.provider_ref["host"] = host
            record.url = f"https://{host}"
            store.upsert(record)

            self._configure_host(spec, bundle, record, private_pem)
            record.status = "running"
        except Exception:
            record.status = "failed"
            store.upsert(record)
            raise
        store.upsert(record)

        self.console("")
        self.console(f"Live at {record.url}")
        return record

    def _update(self, api, spec, bundle, record, store) -> DeploymentRecord:
        """Push a new bundle to a machine that already exists."""
        state, _raw = self._server_state(api, record)
        if state == "absent":
            raise ProviderError(
                f"The {self.server_noun} for '{record.name}' no longer exists. Run `"
                + deploy_command("destroy", spec.config_path, record.name, "--force")
                + "` to clear the record, then deploy again.")

        private_pem = SecretStore(spec.config_path).get(spec.name, "ssh_private_key")
        if not private_pem:
            raise ProviderError(
                "The deploy key for this deployment is missing from "
                f"{SecretStore(spec.config_path).path}, so the host cannot be "
                f"reached. Destroy and recreate, or add your own key in "
                f"{self.console_name}.")

        refused = self.refusal(spec, bundle, existing=record)
        if refused:
            raise ProviderError(refused)

        record.status = "updating"
        record.spec.update(self.record_spec(spec))
        store.upsert(record)
        self.console(f"Updating the existing {self.server_noun} at "
                     f"{self._ssh_host(record)}...")
        self._configure_host(spec, bundle, record, private_pem,
                             skip_cloud_init=True)
        record.status = "running"
        record.bundle_sha = bundle.sha256() if bundle else None
        store.upsert(record)
        return record

    def _configure_host(self, spec, bundle, record, private_pem,
                        *, skip_cloud_init: bool = False) -> None:
        """Upload the bundle, write the environment, start the services."""
        app_dir = record_app_dir(record)
        session = SSHSession(self._ssh_host(record), username=self.ssh_user,
                             private_key_pem=private_pem, console=self.console)
        try:
            self.console("Waiting for SSH...")
            session.wait_for_ssh(timeout=420)

            if not skip_cloud_init:
                self.console("Waiting for first-boot provisioning "
                             "(installing Docker, pulling the image)...")
                session.wait_for_cloud_init(timeout=1200)

                # The Caddyfile is written by cloud-init before the address is
                # known, so the placeholder has to be replaced now.
                if not spec.domain:
                    session.run(
                        f"sed -i 's/{IP_PLACEHOLDER}/{record.provider_ref['host']}/' "
                        "/etc/caddy/Caddyfile", check=True)

            if skip_cloud_init:
                # An update. The image is named only in the systemd unit, which
                # cloud-init wrote once, and nothing pulled it again: `up` on an
                # existing machine never picked up a new --image or a newer
                # :latest. Rewrite the unit and pull before the restart below.
                image = spec.image or DEFAULT_IMAGE
                self.console(f"Pulling {image}...")
                session.put_text(render_potato_service(spec, app_dir),
                                 SERVICE_UNIT_PATH, mode=0o644)
                session.run(f"docker pull {shlex.quote(image)}", check=True,
                            timeout=900)

            volume_devices = record.provider_ref.get("volume_devices")
            if volume_devices:
                self.console("Preparing the volume...")
                session.run(prepare_volume_script(volume_devices, app_dir),
                            check=True, timeout=300)

            self.console("Uploading the bundle...")
            session.run(f"mkdir -p {app_dir} {DATA_DIR}", check=True)
            uploaded = session.put_archive(bundle.bundle_dir, app_dir)
            record.bundle_sha = bundle.sha256()
            self.console(f"  {bundle.file_count} files, {uploaded // 1024} KiB compressed")

            # The upload arrives owned by root even though cloud-init chowned
            # the directory. The container runs as uid 1000 and would fail on
            # the first write. ENV_FILE is a sibling of both directories and
            # stays root-owned at 0600: systemd reads it, the container never does.
            session.run(f"chown -R 1000:1000 {app_dir} {DATA_DIR}", check=True)

            env = self.runtime_env(spec, spec.extra.get("generated"))
            session.put_text(render_env_file(env), ENV_FILE, mode=0o600)

            self.console("Starting the server...")
            session.run("systemctl daemon-reload", check=True)
            session.run("systemctl restart potato.service", check=True)
            session.run("systemctl restart caddy-potato.service", check=True)

            self.console("Waiting for the server to answer...")
            if not session.wait_for_http(f"{record.url}/health", timeout=420):
                logs = session.run(
                    "journalctl -u potato.service -n 30 --no-pager || true")
                raise ProviderError(
                    f"The {self.server_noun} was created but {record.url} never "
                    f"became healthy. The machine is still running — inspect it "
                    f"with `{deploy_command('logs', spec.config_path, spec.name)}` "
                    "or destroy it with "
                    f"`{deploy_command('destroy', spec.config_path, spec.name, '--force')}`.\n\n"
                    f"Last service logs:\n{logs.output()[:1500]}")
        finally:
            session.close()

    # -- status --------------------------------------------------------

    def status(self, record) -> DeploymentStatus:
        if not record.provider_ref.get(self.server_id_key):
            return DeploymentStatus(state="unknown",
                                    detail=f"no {self.server_noun} recorded")
        state, raw = self._server_state(
            self._api(record.provider_ref.get("region")), record)
        if state == "absent":
            return DeploymentStatus(
                state="absent", url=record.url,
                detail=f"the {self.server_noun} no longer exists in this account")
        if state != "active":
            return DeploymentStatus(state=state, url=record.url, raw=raw)

        healthy, detail = self._probe(record)
        return DeploymentStatus(state="running" if healthy else "unhealthy",
                                url=record.url, healthy=healthy, detail=detail,
                                raw=raw)

    def _probe(self, record) -> tuple:
        """Ask the app, then the certificate. Both can fail independently."""
        import requests

        url = f"{record.url}/health"
        try:
            response = requests.get(url, timeout=15)
        except requests.exceptions.SSLError as exc:
            # Worth its own message: an IP certificate lives ~6 days, so a
            # renewal that has been failing shows up here first.
            return False, (f"TLS error reaching {url}: {exc}. If this deployment "
                           "uses an IP-address certificate, renewal may have "
                           "failed — check `"
                           + deploy_command("logs", record.spec.get("config_path"),
                                            record.name) + "`.")
        except requests.RequestException as exc:
            return False, f"{url} is not answering: {exc}"

        if response.status_code == 200:
            return True, ""
        if response.status_code == 503:
            return False, "the server is still loading data (503 from /health)"
        return False, f"/health returned {response.status_code}"

    # -- logs ----------------------------------------------------------

    def logs(self, record, *, lines: int = 200, follow: bool = False) -> Iterator[str]:
        units = "-u potato.service -u caddy-potato.service"
        session = self._session(record)
        try:
            if follow:
                yield from session.stream(f"journalctl {units} -n {lines} -f")
            else:
                yield from session.run(
                    f"journalctl {units} -n {lines} --no-pager",
                    timeout=60).output().splitlines()
        finally:
            # Also on the follow path: a caller that stops iterating early
            # would otherwise leave the connection open until the process ends.
            session.close()

    # -- pull ----------------------------------------------------------

    def pull(self, record, dest: str) -> PullResult:
        """Fetch over SSH, falling back to HTTPS if the deploy key is gone.

        The key lives only in .potato/secrets.json. Losing that file used to
        mean losing the ability to retrieve the study's data, which is far too
        harsh a consequence for deleting a dotfile — the admin key is in the
        same store, and the archive endpoint needs nothing else.
        """
        try:
            session = self._session(record)
        except ProviderError as exc:
            fallback = https_fallback(record, dest, self.console)
            if fallback is not None:
                return fallback
            raise exc
        app_dir = record_app_dir(record)
        result = PullResult(dest=dest)
        os.makedirs(dest, exist_ok=True)
        try:
            output_dir = record.spec.get("output_annotation_dir") or "annotation_output"
            remote_output = posixpath.join(app_dir, output_dir.strip("/"))
            written = session.fetch_dir(remote_output,
                                        os.path.join(dest, "annotation_output"))
            result.files += len(written)

            for database in WAL_DATABASES:
                remote = posixpath.join(app_dir, database)
                local = os.path.join(dest, database)
                if session.sqlite_safe_fetch(remote, local):
                    result.files += 1
                    result.notes.append(f"{database} snapshotted with .backup")
                else:
                    result.skipped.append(database)

            for dirpath, _dirnames, filenames in os.walk(dest):
                for filename in filenames:
                    try:
                        result.bytes += os.path.getsize(
                            os.path.join(dirpath, filename))
                    except OSError:
                        pass
        finally:
            session.close()
        return result

    # -- destroy -------------------------------------------------------

    def destroy(self, record, *, keep_data: bool = False) -> None:
        self._destroy_infrastructure(self._api(record.provider_ref.get("region")),
                                     record, keep_data=keep_data)

    # -- helpers -------------------------------------------------------

    def _ssh_host(self, record) -> str:
        """Connect by address: a hostname may not resolve yet on first boot."""
        return record.provider_ref.get("ipv4") or record.provider_ref.get("host")

    def _session(self, record) -> SSHSession:
        """Open SSH to the recorded host using the stored deploy key.

        ``record.spec['config_path']`` is stamped by the CLI on every load, so
        it points at where the project lives now rather than where it lived when
        the machine was created.
        """
        host = self._ssh_host(record)
        if not host:
            raise ProviderError(
                f"No host address recorded for '{record.name}'. If the "
                f"{self.server_noun} still exists, find its IP in "
                f"{self.console_name}.")

        config_path = record.spec.get("config_path")
        if not config_path:
            raise ProviderError(
                "Cannot locate the project's secret store, so the deploy key is "
                "unreachable. This is a bug — report it with the contents of "
                ".potato/deployments.json.")

        store = SecretStore(config_path)
        private_pem = store.get(record.name, "ssh_private_key")
        if not private_pem:
            raise ProviderError(
                f"No deploy key for '{record.name}' in {store.path}, so the host "
                "cannot be reached over SSH. The key is generated once at create "
                "time and never leaves that file. If it was deleted, add your own "
                f"key to the {self.server_noun} from {self.console_name}, or pull "
                "the data through the admin export API instead.")
        return SSHSession(host, username=self.ssh_user, private_key_pem=private_pem,
                          console=self.console)
