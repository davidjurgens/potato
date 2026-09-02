"""Deploy a Potato task to a DigitalOcean droplet.

This is the provider the rest of the interface was designed around. Persistence,
TLS without a domain, secret injection, log retrieval and getting the data back
are all real problems here, and solving them on a plain VM produces an interface
that a push-to-git host can also satisfy. Doing it the other way round yields a
`Provider` that only fits Spaces.

`create` is a sequence of waits as much as a sequence of calls. Droplet-active,
SSH-ready and cloud-init-done are three different moments minutes apart, and
treating them as one is what makes tools in this category appear to hang. Each
gets its own wait and its own message.

TLS uses Let's Encrypt certificates issued for the droplet's bare IPv4 address
(generally available since 2026-01-15). `--domain` remains available for anyone
with a real name to point at it. See templates/Caddyfile.j2 for why sslip.io is
not an option.
"""

from __future__ import annotations

import os
import posixpath
import time
from typing import Any, Dict, Iterator, Optional

from potato.deploy.do_api import DigitalOceanAPI
from potato.deploy.providers.base import (
    Action,
    DeployPlan,
    DeploymentStatus,
    DeploySpec,
    Provider,
    ProviderError,
    PullResult,
    register_provider,
)
from potato.deploy.remote import SSHSession, WAL_DATABASES, generate_keypair
from potato.deploy.state import DeploymentRecord, SecretStore

DEFAULT_IMAGE = "ghcr.io/davidjurgens/potato:latest"
CADDY_IMAGE = "caddy:2.11.3-alpine"
BASE_IMAGE = "docker-20-04"

DEFAULT_REGION = "nyc3"
DEFAULT_SIZE = "s-2vcpu-2gb"

APP_DIR = "/opt/potato/app"
DATA_DIR = "/opt/potato/data"
ENV_FILE = "/opt/potato/potato.env"
APP_PORT = 8000
CONTAINER = "potato"
CADDY_CONTAINER = "potato-caddy"

LETSENCRYPT_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"

# Monthly price by slug. Displayed before the confirmation prompt, so a wrong
# number here misleads someone about their own money.
SIZE_PRICES = {
    "s-1vcpu-1gb": 6.0,
    "s-1vcpu-2gb": 12.0,
    "s-2vcpu-2gb": 18.0,
    "s-2vcpu-4gb": 24.0,
    "s-4vcpu-8gb": 48.0,
}
VOLUME_PRICE_PER_GB = 0.10

# 1 GB cannot install Docker and run the image without swapping. The image is
# ~840 MB, and Potato's numpy/pandas/scipy working set is not small.
MIN_RECOMMENDED_MEMORY_MB = 2048


def _memory_mb(size_slug: str) -> Optional[int]:
    """Parse the memory out of a size slug like `s-2vcpu-2gb`."""
    for part in (size_slug or "").split("-"):
        if part.endswith("gb") and part[:-2].isdigit():
            return int(part[:-2]) * 1024
        if part.endswith("mb") and part[:-2].isdigit():
            return int(part[:-2])
    return None


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


def build_cloud_init(spec: DeploySpec, *, public_host: str,
                     volume_device: Optional[str] = None) -> str:
    """Render the full first-boot configuration.

    Pure: no credentials, no I/O, no network. That is what lets a test assert
    the exact firewall rules and unit files that a real deploy would install.
    """
    image = spec.image or DEFAULT_IMAGE
    cert_dir = posixpath.join(DATA_DIR, "caddy") if volume_device else "/var/lib/caddy"

    potato_service = render_template(
        "potato.service.j2",
        container_name=CONTAINER, env_file=ENV_FILE, app_port=APP_PORT,
        app_dir=APP_DIR, data_dir=DATA_DIR, image=image,
        deployment_name=spec.name)

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
        image=image, caddy_image=CADDY_IMAGE, app_dir=APP_DIR, data_dir=DATA_DIR,
        app_port=APP_PORT, volume_device=volume_device,
        potato_service=potato_service, caddyfile=caddyfile,
        caddy_service=caddy_service)


def firewall_rules(name: str, tag: str) -> Dict[str, Any]:
    """Inbound 22/80/443 only.

    Port 8000 is never opened. The container binds it to 127.0.0.1 and Caddy
    reaches it over loopback, so the plaintext app is unreachable from outside
    even if this firewall is deleted by hand.
    """
    anywhere = {"addresses": ["0.0.0.0/0", "::/0"]}
    return {
        "name": f"potato-{name}",
        "inbound_rules": [
            {"protocol": "tcp", "ports": "22", "sources": anywhere},
            {"protocol": "tcp", "ports": "80", "sources": anywhere},
            {"protocol": "tcp", "ports": "443", "sources": anywhere},
        ],
        "outbound_rules": [
            {"protocol": "tcp", "ports": "all", "destinations": anywhere},
            {"protocol": "udp", "ports": "all", "destinations": anywhere},
            {"protocol": "icmp", "destinations": anywhere},
        ],
        "tags": [tag],
    }


def droplet_payload(spec: DeploySpec, *, tag: str, ssh_key_id, user_data: str,
                    region: str, size: str) -> Dict[str, Any]:
    return {
        "name": f"potato-{spec.name}",
        "region": region,
        "size": size,
        "image": BASE_IMAGE,
        "ssh_keys": [ssh_key_id],
        "backups": False,
        "ipv6": True,
        "monitoring": True,
        "tags": [tag, "potato"],
        "user_data": user_data,
    }


@register_provider
class DigitalOceanProvider(Provider):
    """A single droplet running the published image behind Caddy."""

    name = "digitalocean"
    requires = ("paramiko",)
    ephemeral_fs = False
    public = True
    supports_logs = True
    supports_pull = True

    # -- plan ----------------------------------------------------------

    def verify_credential(self):
        account = DigitalOceanAPI(self.token).verify_token()
        email = account.get("email") or "unknown account"
        limit = account.get("droplet_limit")
        status = account.get("status")
        detail = f"{email}"
        if status and status != "active":
            detail += f", status {status}"
        if limit is not None:
            detail += f", droplet limit {limit}"
        return detail

    def plan(self, spec: DeploySpec, bundle) -> DeployPlan:
        region = spec.region or DEFAULT_REGION
        size = spec.size or DEFAULT_SIZE
        tag = f"potato-{spec.name}"
        image = spec.image or DEFAULT_IMAGE

        host_placeholder = spec.domain or "<droplet-ipv4>"
        scheme = "https"
        user_data = build_cloud_init(
            spec, public_host=host_placeholder,
            volume_device=_volume_device(spec) if spec.volume_gb else None)

        env = self.runtime_env(spec, spec.extra.get("generated"))

        plan = DeployPlan(
            result_url_pattern=f"{scheme}://{host_placeholder}",
            estimated_cost_usd_month=_estimate_cost(size, spec.volume_gb))

        plan.actions = [
            Action("do.account", "verify the token with GET /v2/account"),
            Action("ssh.keygen",
                   "generate an ed25519 deploy key (never your own key)"),
            Action("do.ssh_key", f"register the public key as potato-{spec.name}",
                   {"name": f"potato-{spec.name}"}),
        ]
        if spec.volume_gb:
            plan.actions.append(Action(
                "do.volume", f"create a {spec.volume_gb} GB volume in {region}",
                {"size_gigabytes": spec.volume_gb, "region": region}))
        plan.actions += [
            Action("do.droplet", f"create a {size} droplet in {region} from {BASE_IMAGE}",
                   droplet_payload(spec, tag=tag, ssh_key_id="<key-id>",
                                   user_data=user_data, region=region, size=size)),
            Action("state.persist",
                   "record the droplet id before anything else can fail"),
            Action("do.firewall", "allow inbound 22/80/443 only; never 8000",
                   firewall_rules(spec.name, tag)),
            Action("wait.active", "poll until the droplet reports active with an IPv4"),
            Action("wait.ssh", "poll until the host accepts an SSH connection"),
            Action("wait.cloud_init",
                   "wait for docker install and image pull to finish"),
            Action("ssh.upload", f"upload the bundle to {APP_DIR}",
                   {"files": bundle.file_count if bundle else None,
                    "bytes": bundle.total_bytes if bundle else None}),
            Action("ssh.env", f"write {ENV_FILE} at mode 0600",
                   # Keys only. The values include the Flask signing key and the
                   # admin API key, and a plan is printed to a terminal.
                   {"env_keys": sorted(env)}),
            Action("ssh.start", "systemctl start potato and caddy"),
            Action("wait.http", f"poll {scheme}://{host_placeholder}/health"),
        ]

        memory = _memory_mb(size)
        if memory is not None and memory < MIN_RECOMMENDED_MEMORY_MB:
            plan.warnings.append(
                f"{size} has {memory} MB of RAM. The image is ~840 MB and Potato's "
                "working set is numpy/pandas/scipy; expect swapping. 2 GB is the "
                "smallest size worth using.")
        if not spec.domain:
            plan.warnings.append(
                "No --domain, so TLS uses a Let's Encrypt certificate for the "
                "droplet's IP address. These are valid ~6 days rather than 90, so "
                "check `potato deploy status` if the study runs unattended.")
        if spec.volume_gb is None:
            plan.warnings.append(
                "No --volume-gb. Annotations live on the droplet's own disk, which "
                "is destroyed with the droplet. Pull before you destroy.")
        if not bundle:
            plan.warnings.append("No bundle was built; this plan cannot run.")
        return plan

    # -- create --------------------------------------------------------

    def create(self, spec: DeploySpec, bundle, existing, store) -> DeploymentRecord:
        missing = self.check_requirements()
        if missing:
            raise ProviderError(
                f"The digitalocean provider needs {', '.join(missing)}. "
                "Install with: pip install 'potato-annotation[deploy]'")

        api = DigitalOceanAPI(self.token)
        account = api.verify_token()
        if account.get("status") not in (None, "active"):
            raise ProviderError(
                f"The DigitalOcean account is {account.get('status')}: "
                f"{account.get('status_message') or 'see the console'}")

        record = existing or DeploymentRecord(name=spec.name, provider=self.name)
        if record.provider_ref.get("droplet_id"):
            return self._update(api, spec, bundle, record, store)
        return self._provision(api, spec, bundle, record, store)

    def _provision(self, api, spec, bundle, record, store) -> DeploymentRecord:
        region = spec.region or DEFAULT_REGION
        size = spec.size or DEFAULT_SIZE
        tag = f"potato-{spec.name}"
        secrets = SecretStore(spec.config_path)

        record.status = "creating"
        record.provider_ref.setdefault("tag", tag)
        record.provider_ref["region"] = region
        record.spec.update(_record_spec(spec))
        store.upsert(record)

        self.console("Generating a deploy key...")
        private_pem, public_key = generate_keypair(f"potato-{spec.name}")
        secrets.put(spec.name, "ssh_private_key", private_pem)

        ssh_key = api.create_ssh_key(f"potato-{spec.name}", public_key)
        record.provider_ref["ssh_key_id"] = ssh_key["id"]
        store.upsert(record)

        volume_id = None
        if spec.volume_gb:
            self.console(f"Creating a {spec.volume_gb} GB volume...")
            volume = api.create_volume({
                "name": f"potato-{spec.name}",
                "region": region,
                "size_gigabytes": int(spec.volume_gb),
                "filesystem_type": "ext4",
                "tags": [tag],
            })
            volume_id = volume["id"]
            record.provider_ref["volume_id"] = volume_id
            record.provider_ref["volume_name"] = volume["name"]
            store.upsert(record)

        user_data = build_cloud_init(
            spec, public_host=spec.domain or "REPLACED_AFTER_IP",
            volume_device=_volume_device(spec) if spec.volume_gb else None)

        self.console(f"Creating a {size} droplet in {region}...")
        try:
            droplet = api.create_droplet(droplet_payload(
                spec, tag=tag, ssh_key_id=ssh_key["id"], user_data=user_data,
                region=region, size=size))
        except ProviderError:
            record.status = "failed"
            store.upsert(record)
            raise

        # Before anything else can fail. A droplet whose id exists only in a
        # dead process is a machine that bills forever.
        record.provider_ref["droplet_id"] = droplet["id"]
        store.upsert(record)

        try:
            firewall = api.create_firewall(firewall_rules(spec.name, tag))
            record.provider_ref["firewall_id"] = firewall["id"]
            store.upsert(record)

            ip = self._wait_for_ipv4(api, droplet["id"])
            record.provider_ref["ipv4"] = ip
            host = spec.domain or ip
            record.url = f"https://{host}"
            store.upsert(record)

            if volume_id:
                self.console("Attaching the volume...")
                api.attach_volume(volume_id, droplet["id"], region)

            self._configure_host(spec, bundle, record, host, private_pem)
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
        """Push a new bundle to a droplet that already exists."""
        droplet_id = record.provider_ref["droplet_id"]
        if api.get_droplet(droplet_id) is None:
            raise ProviderError(
                f"Droplet {droplet_id} no longer exists. Run "
                f"`potato deploy destroy --name {record.name} --force` to clear the "
                "record, then deploy again.")

        private_pem = SecretStore(spec.config_path).get(spec.name, "ssh_private_key")
        if not private_pem:
            raise ProviderError(
                "The deploy key for this deployment is missing from "
                f"{SecretStore(spec.config_path).path}, so the host cannot be "
                "reached. Destroy and recreate, or add your own key in the "
                "DigitalOcean console.")

        host = spec.domain or record.provider_ref.get("ipv4")
        record.status = "updating"
        record.spec.update(_record_spec(spec))
        store.upsert(record)
        self.console(f"Updating the existing droplet at {host}...")
        self._configure_host(spec, bundle, record, host, private_pem,
                             skip_cloud_init=True)
        record.status = "running"
        record.bundle_sha = bundle.sha256() if bundle else None
        store.upsert(record)
        return record

    def _configure_host(self, spec, bundle, record, host, private_pem,
                        *, skip_cloud_init: bool = False) -> None:
        """Upload the bundle, write the environment, start the services."""
        session = SSHSession(host, private_key_pem=private_pem, console=self.console)
        try:
            self.console("Waiting for SSH...")
            session.wait_for_ssh(timeout=420)

            if not skip_cloud_init:
                self.console("Waiting for first-boot provisioning "
                             "(installing Docker, pulling the image)...")
                session.wait_for_cloud_init(timeout=1200)

                # The Caddyfile is written by cloud-init before the IP is known,
                # so the placeholder has to be replaced now.
                if not spec.domain:
                    session.run(
                        f"sed -i 's/REPLACED_AFTER_IP/{host}/' /etc/caddy/Caddyfile",
                        check=True)

            self.console("Uploading the bundle...")
            session.run(f"mkdir -p {APP_DIR} {DATA_DIR}", check=True)
            uploaded = session.put_archive(bundle.bundle_dir, APP_DIR)
            record.bundle_sha = bundle.sha256()
            self.console(f"  {bundle.file_count} files, {uploaded // 1024} KiB compressed")

            # SFTP writes as root, so every uploaded file arrives owned by root
            # even though cloud-init chowned the directory. The container runs
            # as uid 1000 and would fail on the first write. ENV_FILE is a
            # sibling of both directories and stays root-owned at 0600: systemd
            # reads it, the container never does.
            session.run(f"chown -R 1000:1000 {APP_DIR} {DATA_DIR}", check=True)

            env = self.runtime_env(spec, spec.extra.get("generated"))
            session.put_text(_render_env_file(env), ENV_FILE, mode=0o600)

            self.console("Starting the server...")
            session.run("systemctl daemon-reload", check=True)
            session.run("systemctl restart potato.service", check=True)
            session.run("systemctl restart caddy-potato.service", check=True)

            self.console("Waiting for the server to answer...")
            if not session.wait_for_http(f"{record.url}/health", timeout=420):
                logs = session.run(
                    "journalctl -u potato.service -n 30 --no-pager || true")
                raise ProviderError(
                    f"The droplet was created but {record.url} never became "
                    f"healthy. The machine is still running — inspect it with "
                    f"`potato deploy logs --name {spec.name}` or destroy it with "
                    f"`potato deploy destroy --name {spec.name} --force`.\n\n"
                    f"Last service logs:\n{logs.output()[:1500]}")
        finally:
            session.close()

    def _wait_for_ipv4(self, api, droplet_id: int, timeout: int = 300) -> str:
        self.console("Waiting for the droplet to become active...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            droplet = api.get_droplet(droplet_id) or {}
            for network in (droplet.get("networks", {}).get("v4") or []):
                if network.get("type") == "public" and network.get("ip_address"):
                    return network["ip_address"]
            time.sleep(5)
        raise ProviderError(
            f"Droplet {droplet_id} did not report a public IPv4 within {timeout}s. "
            "It may still be provisioning; check the DigitalOcean console. The "
            "droplet id is recorded locally, so `potato deploy destroy` can "
            "still remove it.")

    # -- status --------------------------------------------------------

    def status(self, record) -> DeploymentStatus:
        droplet_id = record.provider_ref.get("droplet_id")
        if not droplet_id:
            return DeploymentStatus(state="unknown", detail="no droplet recorded")

        api = DigitalOceanAPI(self.token)
        droplet = api.get_droplet(droplet_id)
        if droplet is None:
            return DeploymentStatus(
                state="absent", url=record.url,
                detail="the droplet no longer exists in this account")

        do_state = droplet.get("status", "unknown")
        if do_state != "active":
            return DeploymentStatus(state=do_state, url=record.url, raw=droplet)

        healthy, detail = self._probe(record)
        return DeploymentStatus(state="running" if healthy else "unhealthy",
                                url=record.url, healthy=healthy, detail=detail,
                                raw=droplet)

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
                           "failed — check `potato deploy logs --name "
                           f"{record.name}`.")
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
            fallback = _https_fallback(record, dest, self.console)
            if fallback is not None:
                return fallback
            raise exc
        result = PullResult(dest=dest)
        os.makedirs(dest, exist_ok=True)
        try:
            output_dir = record.spec.get("output_annotation_dir") or "annotation_output"
            remote_output = posixpath.join(APP_DIR, output_dir.strip("/"))
            written = session.fetch_dir(remote_output,
                                        os.path.join(dest, "annotation_output"))
            result.files += len(written)

            for database in WAL_DATABASES:
                remote = posixpath.join(APP_DIR, database)
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
        """Remove the droplet, firewall, SSH key and volume.

        Order matters: the droplet goes first so the volume detaches, and every
        step tolerates a missing resource so a partly-destroyed deployment can
        be finished off rather than becoming unremovable.
        """
        api = DigitalOceanAPI(self.token)
        reference = record.provider_ref

        droplet_id = reference.get("droplet_id")
        if droplet_id:
            api.delete_droplet(droplet_id)
            self.console(f"Deleted droplet {droplet_id}")

        if reference.get("firewall_id"):
            api.delete_firewall(reference["firewall_id"])
            self.console("Deleted the firewall")

        if reference.get("ssh_key_id"):
            try:
                api.delete_ssh_key(reference["ssh_key_id"])
                self.console("Removed the deploy key")
            except ProviderError as exc:
                self.console(f"Could not remove the deploy key: {exc}")

        volume_id = reference.get("volume_id")
        if volume_id and not keep_data:
            # The droplet has to release it first; a detach lags the delete.
            for attempt in range(12):
                try:
                    api.delete_volume(volume_id)
                    self.console("Deleted the volume")
                    break
                except ProviderError:
                    time.sleep(5)
            else:
                self.console(
                    f"Volume {volume_id} could not be deleted (still attached?). "
                    "It continues to bill until removed in the console.")
        elif volume_id:
            self.console(f"Kept volume {volume_id}; it still bills "
                         f"${VOLUME_PRICE_PER_GB:.2f}/GB per month.")

        # Anything created but never recorded — a mid-create crash — is still
        # tagged, so name it rather than leaving it to bill unnoticed.
        orphans = [d for d in api.droplets_by_tag(reference.get("tag", ""))
                   if d.get("id") != droplet_id]
        for orphan in orphans:
            self.console(f"Also found tagged droplet {orphan['id']} "
                         f"({orphan.get('name')}); deleting it too")
            api.delete_droplet(orphan["id"])

    # -- helpers -------------------------------------------------------

    def _session(self, record) -> SSHSession:
        """Open SSH to the recorded host using the stored deploy key.

        ``record.spec['config_path']`` is stamped by the CLI on every load, so
        it points at where the project lives now rather than where it lived when
        the droplet was created.
        """
        host = record.provider_ref.get("ipv4")
        if not host:
            raise ProviderError(
                f"No host address recorded for '{record.name}'. If the droplet "
                "still exists, find its IP in the DigitalOcean console.")

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
                "key to the droplet from the DigitalOcean console, or pull the "
                "data through the admin export API instead.")
        return SSHSession(host, private_key_pem=private_pem, console=self.console)


def _https_fallback(record, dest: str, console):
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


def _record_spec(spec: DeploySpec) -> Dict[str, Any]:
    """The parts of the spec later commands need, without any secret."""
    return {
        "config_path": os.path.abspath(spec.config_path),
        "domain": spec.domain,
        "region": spec.region or DEFAULT_REGION,
        "size": spec.size or DEFAULT_SIZE,
        "volume_gb": spec.volume_gb,
        "output_annotation_dir": spec.extra.get("output_annotation_dir",
                                                "annotation_output"),
    }


def _render_env_file(env: Dict[str, str]) -> str:
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


def _volume_device(spec: DeploySpec) -> str:
    """DigitalOcean exposes an attached volume at a name-derived path."""
    return f"/dev/disk/by-id/scsi-0DO_Volume_potato-{spec.name}"


def _estimate_cost(size: str, volume_gb: Optional[int]) -> float:
    cost = SIZE_PRICES.get(size, 0.0)
    if volume_gb:
        cost += float(volume_gb) * VOLUME_PRICE_PER_GB
    return cost
