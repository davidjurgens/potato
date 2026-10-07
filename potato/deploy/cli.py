"""``potato deploy`` — build, inspect, provision, and tear down a hosted task.

Dispatched before argparse in ``flask_server.main`` because ``deploy`` has its
own flag set and does not fit the ``mode`` + ``config_file`` positional shape of
``server_utils/arg_utils.py``. That follows the pattern already used by
``transcripts``, ``convokit``, ``import`` and ``download-models``.

``up`` spends the user's money, so it prints the plan, the exposure summary and
the estimated cost, then asks for confirmation. ``--yes`` skips the prompt;
``--dry-run`` stops before anything is created.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from potato.deploy import credentials as creds
from potato.deploy.backup_options import (
    BackupOptions,
    BackupOptionsError,
    apply_to_config as apply_backup_to_config,
    default_hf_repo,
    from_args as backup_from_args,
)
from potato.deploy.bundle import build_bundle
from potato.deploy.preflight import harden_config, render_report, run_preflight
from potato.deploy.providers.base import (
    DeploySpec,
    Provider,
    ProviderError,
    available_providers,
    get_provider,
)
from potato.deploy.state import DeploymentRecord, DeploymentStore, SecretStore, slugify

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2
EXIT_ABORTED = 3


def _echo(message: str = "") -> None:
    print(message, flush=True)


def _load_task_name(config_path: str) -> str:
    return _load_config(config_path).get("annotation_task_name") or "potato-task"


def _load_config(config_path: str) -> dict:
    """The raw YAML, or an empty dict. Never raises.

    Preflight is what reports an unreadable config; this only feeds defaults, so
    it must not turn a bad config into a traceback before the report is printed.
    """
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return {}


def _bundle_dir(config_path: str, provider: str, name: str) -> str:
    """Where a deployment's bundle is assembled.

    Scoped by provider, not only by name. The ``local`` provider bind-mounts
    its bundle as the running task's directory, so the server's annotations
    live there — and a bundle directory shared with a cloud provider meant that
    building for DigitalOcean (a `--dry-run` was enough) deleted the running
    local deployment's data on the way past.
    """
    return os.path.join(os.path.dirname(os.path.abspath(config_path)),
                        ".potato", "bundle", provider, name)


def _parse_key_values(pairs: Optional[List[str]], flag: str) -> dict:
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"{flag} expects KEY=VALUE, got: {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato deploy",
        description="Put an annotation task on a host, and take it down again.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, needs_provider=True):
        p.add_argument("config_file", help="path to the task's config.yaml")
        if needs_provider:
            p.add_argument("--provider", default="local",
                           choices=available_providers(),
                           help="deployment target (default: local)")
        p.add_argument("--name", default=None,
                       help="deployment name; defaults to a slug of the task name")
        return p

    check = sub.add_parser("check", help="validate a config for deployment")
    add_common(check)
    check.add_argument("--json", action="store_true", dest="as_json")
    check.add_argument("--private", action="store_true",
                       help="assess as a non-public host")

    build = sub.add_parser("build", help="assemble the deployable bundle and stop")
    add_common(build)
    build.add_argument("--out", default=None, help="output directory")
    build.add_argument("--tarball", default=None, help="also write a .tar.gz here")

    up = sub.add_parser("up", help="provision or update a deployment")
    add_common(up)
    up.add_argument("--region", default=None)
    up.add_argument("--size", default=None)
    up.add_argument("--domain", default=None)
    up.add_argument("--image", default=None)
    up.add_argument("--port", type=int, default=8000)
    up.add_argument("--volume-gb", type=int, default=None, dest="volume_gb")
    up.add_argument("--workers", type=int, default=1)
    up.add_argument("--threads", type=int, default=8)
    up.add_argument("--token", default=None, help="provider API token")
    up.add_argument("--env", action="append", metavar="KEY=VALUE")
    up.add_argument("--secret", action="append", metavar="KEY=VALUE")
    up.add_argument("--private", action="store_true")
    up.add_argument("--demo", action="store_true",
                    help="throwaway data; skip durability warnings")
    up.add_argument("--plan", default=None,
                    help="provider service plan (render: free, starter, standard)")
    up.add_argument("--owner", default=None,
                    help="account or organization to deploy under (huggingface)")
    up.add_argument("--hf-token", default=None, dest="hf_token",
                    help="HuggingFace token for continuous Dataset backup, on any "
                         "provider. Falls back to HF_TOKEN.")
    up.add_argument("--backup-minutes", type=int, default=None,
                    dest="backup_minutes",
                    help="how often to mirror annotations to the backup")
    up.add_argument("--backup", default=None, metavar="hf|s3|hf,s3",
                    help="where to back collected data up to; restored "
                         "automatically into an empty task at boot")
    up.add_argument("--hf-backup-repo", default=None, dest="hf_backup_repo",
                    help="dataset repo for the HF backup "
                         "(default <account>/<name>-annotations)")
    up.add_argument("--s3-bucket", default=None, dest="s3_bucket",
                    help="bucket for an S3 backup (also R2, B2, MinIO)")
    up.add_argument("--s3-prefix", default=None, dest="s3_prefix",
                    help="key prefix inside the bucket (default potato/<name>)")
    up.add_argument("--s3-region", default=None, dest="s3_region")
    up.add_argument("--s3-endpoint", default=None, dest="s3_endpoint",
                    help="S3-compatible endpoint URL, for R2/B2/MinIO")
    up.add_argument("--aws-profile", default=None, dest="aws_profile",
                    help="AWS named profile (aws, aws-ec2, aws-ecs); default "
                         "is boto3's own chain, including AWS_PROFILE")
    up.add_argument("--subnet", default=None,
                    help="aws-ec2: a public subnet id, when the region has no "
                         "default VPC")
    up.add_argument("--cloud", default=None,
                    help="openstack: clouds.yaml entry (e.g. jetstream2); "
                         "default $OS_CLOUD")
    up.add_argument("--network", default=None,
                    help="openstack: network name (default: auto-allocated)")
    up.add_argument("--os-image", default=None, dest="os_image",
                    help="openstack: image name (default Featured-Ubuntu24 on "
                         "Jetstream2)")
    up.add_argument("--heroku-registry", action="store_true", dest="heroku_registry",
                    help="heroku: build with local Docker and push to "
                         "registry.heroku.com instead of building on Heroku")
    up.add_argument("--acme-email", default=None, dest="acme_email",
                    help="contact address for the Let's Encrypt certificate "
                         "(default: git config user.email)")
    up.add_argument("--dry-run", action="store_true", dest="dry_run")
    up.add_argument("--yes", "-y", action="store_true",
                    help="skip the confirmation prompt")
    up.add_argument("--force", action="store_true",
                    help="proceed despite preflight errors (never for a public host)")

    for name, help_text in (("status", "show a deployment's current state"),
                            ("destroy", "remove a deployment's resources")):
        p = sub.add_parser(name, help=help_text)
        add_common(p, needs_provider=False)
        p.add_argument("--token", default=None)
        if name == "destroy":
            p.add_argument("--keep-data", action="store_true", dest="keep_data")
            p.add_argument("--yes", "-y", action="store_true")
            p.add_argument("--force", action="store_true",
                           help="destroy without a prior successful pull")

    logs = sub.add_parser("logs", help="show server logs")
    add_common(logs, needs_provider=False)
    logs.add_argument("--token", default=None)
    logs.add_argument("--lines", type=int, default=200)
    logs.add_argument("--follow", "-f", action="store_true")

    pull = sub.add_parser("pull", help="download annotations from a deployment")
    pull.add_argument("--allow-empty", action="store_true",
                      help="record a pull that returned no files")
    add_common(pull, needs_provider=False)
    pull.add_argument("--token", default=None)
    pull.add_argument("--dest", default=None)

    listing = sub.add_parser("list", help="list deployments recorded for a config")
    listing.add_argument("config_file")

    button = sub.add_parser("button", help="write one-click deploy button files "
                            "into the project's repository")
    button.add_argument("config_file")
    button.add_argument("--target", required=True,
                        choices=("heroku", "render", "aws", "railway"))
    button.add_argument("--name", default=None)
    button.add_argument("--image", default=None)
    button.add_argument("--backup", default=None, metavar="hf|s3|hf,s3")
    button.add_argument("--hf-token", default=None, dest="hf_token")
    button.add_argument("--hf-backup-repo", default=None, dest="hf_backup_repo")
    button.add_argument("--s3-bucket", default=None, dest="s3_bucket")
    button.add_argument("--s3-prefix", default=None, dest="s3_prefix")
    button.add_argument("--s3-region", default=None, dest="s3_region")
    button.add_argument("--s3-endpoint", default=None, dest="s3_endpoint")
    button.add_argument("--backup-minutes", type=int, default=None, dest="backup_minutes")
    button.add_argument("--template-url", default=None, dest="template_url",
                        help="aws: the S3 URL of the uploaded template")
    button.add_argument("--region", default="us-east-1")
    button.add_argument("--force", action="store_true",
                        help="replace files that already exist")
    button.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="print what would be written")

    providers = sub.add_parser("providers", help="show targets and credential status")
    providers.add_argument("--verify", action="store_true",
                           help="ask each provider whether its token actually works")
    return parser


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_check(args) -> int:
    provider = get_provider(args.provider)
    report = run_preflight(args.config_file, provider=args.provider,
                           public=(provider.public and not args.private),
                           ephemeral_fs=provider.ephemeral_fs)
    if args.as_json:
        _echo(json.dumps(report.to_dict(), indent=2))
    else:
        _echo(render_report(report))
    return EXIT_OK if report.ok else EXIT_BLOCKED


def cmd_build(args) -> int:
    name = args.name or slugify(_load_task_name(args.config_file))
    out_dir = args.out or _bundle_dir(args.config_file, args.provider, name)

    report = run_preflight(args.config_file, provider=args.provider,
                           public=False)
    manifest = build_bundle(args.config_file, out_dir,
                            patch=lambda cfg: harden_config(cfg, provider=args.provider))

    _echo(f"Bundle: {manifest.bundle_dir}")
    _echo(f"  {manifest.file_count} files, {manifest.human_size()}")
    _echo(f"  sha256 {manifest.sha256()[:16]}")
    for key, value in manifest.rewritten_keys.items():
        _echo(f"  relocated {key} -> {value}")
    for warning in manifest.warnings:
        _echo(f"  WARNING {warning}")

    if args.tarball:
        from potato.deploy.bundle import bundle_tarball
        _echo(f"  tarball {bundle_tarball(manifest, args.tarball)}")

    if not report.ok:
        _echo("")
        _echo("Preflight found errors; `potato deploy up` will refuse until they are fixed.")
        return EXIT_BLOCKED
    return EXIT_OK


def cmd_up(args) -> int:
    name = args.name or slugify(_load_task_name(args.config_file))
    provider_name = args.provider
    public = provider_name != "local" and not args.private

    # A target `deploy up` cannot drive at all (the tunnel runs under `potato
    # share`) is refused before anything else, including the credential prompt
    # it used to show first.
    early = get_provider(provider_name, console=_echo)
    if getattr(early, "driven_by", None):
        _echo(f"REFUSED: {early.refusal(None, None)}")
        return EXIT_BLOCKED

    token, source = creds.resolve_token(provider_name, args.token)
    if creds.requires_credential(provider_name) and not token and not args.dry_run:
        _echo(creds.missing_token_message(provider_name))
        return EXIT_ERROR

    provider = get_provider(provider_name, token=token, console=_echo)

    try:
        backup = _resolve_backup(args, name, provider_name)
    except BackupOptionsError as exc:
        _echo(f"Backup: {exc}")
        return EXIT_ERROR

    report = run_preflight(args.config_file, provider=provider_name, public=public,
                           ephemeral_fs=provider.ephemeral_fs, workers=args.workers,
                           backup_configured=backup.enabled or (
                               provider_name == "huggingface" and not args.demo),
                           provided_env=[item.split("=", 1)[0] for item in
                                         (args.secret or []) + (args.env or [])])
    _echo(render_report(report))
    _echo("")

    if not report.ok:
        if not args.force:
            _echo("Refusing to deploy. Fix the errors above, or pass --force "
                  "(not available for a public host).")
            return EXIT_BLOCKED
        if public:
            _echo("--force is not honoured for a public host: the errors above "
                  "describe what a stranger could do.")
            return EXIT_BLOCKED
        _echo("Proceeding despite errors because --force was given.")

    out_dir = _bundle_dir(args.config_file, provider_name, name)
    manifest = build_bundle(args.config_file, out_dir,
                            patch=lambda cfg: apply_backup_to_config(harden_config(
                                cfg, provider=provider_name, workers=args.workers),
                                backup),
                            preserve_collected_data=provider.mounts_bundle)
    _echo(f"Bundle: {manifest.file_count} files, {manifest.human_size()}")
    for warning in manifest.warnings:
        _echo(f"  WARNING {warning}")
    if backup.enabled:
        _echo(f"Backup: {backup.describe()}, every {backup.minutes} min, "
              "restored into an empty task at boot")
    _echo("")

    hf_token = args.hf_token or os.environ.get("HF_TOKEN")
    secrets = _parse_key_values(args.secret, "--secret")
    for key, value in backup.secrets().items():
        secrets.setdefault(key, value)

    spec = DeploySpec(
        name=name, config_path=args.config_file, region=args.region, size=args.size,
        domain=args.domain, image=args.image, workers=args.workers,
        threads=args.threads, volume_gb=args.volume_gb, private=args.private,
        demo=args.demo,
        env=_parse_key_values(args.env, "--env"),
        secrets=secrets,
        extra={"port": args.port, "generated": report.generated,
               "config_rel": manifest.config_rel_path,
               # `pull` needs this to know which directory holds the
               # annotations. Defaulting to the common value would silently
               # fetch nothing from a task that sets its own.
               "output_annotation_dir": _load_config(args.config_file).get(
                   "output_annotation_dir") or "annotation_output",
               "plan": args.plan,
               "owner": args.owner,
               "hf_token": hf_token,
               "huggingface_backup": "hf" in backup.kinds,
               "backup": backup,
               "backup_kinds": list(backup.kinds),
               "backup_minutes": args.backup_minutes or 5,
               # Image-only hosts upload the tarball here before fetching it.
               "bundle_workdir": out_dir + ".dist",
               "acme_email": args.acme_email or _git_email(),
               "aws_profile": args.aws_profile,
               "heroku_registry": args.heroku_registry,
               "subnet": args.subnet,
               "cloud": args.cloud,
               "network": args.network,
               "os_image": args.os_image,
               "title": _load_config(args.config_file).get("annotation_task_name"),
               },
    )

    # The plan and the refusal check need to know whether this is an update:
    # an existing VM is updated in place, and a plan for a fresh machine
    # described resources `up` would never create.
    spec.extra["existing_record"] = DeploymentStore(args.config_file).get(name)

    plan = provider.plan(spec, manifest)
    for field in getattr(provider, "ignored_flags", ()):
        if getattr(spec, field, None) not in (None, False):
            flag = "--" + field.replace("_", "-")
            plan.warnings.append(f"{provider_name} does not use {flag}; it is ignored.")
    _echo(plan.render())
    _echo("")

    # The same check create() makes first, so a dry run that `up` would refuse
    # fails too instead of printing a clean plan.
    refused = provider.refusal(spec, manifest)
    if refused:
        _echo(f"REFUSED: {refused}")
        return EXIT_BLOCKED

    if args.dry_run:
        _echo("Dry run: nothing was created.")
        if token:
            _echo(f"Token would come from {source.description} ({creds.redact(token)}).")
        return EXIT_OK

    if not args.yes and not _confirm(plan, provider_name):
        _echo("Aborted.")
        return EXIT_ABORTED

    store = DeploymentStore(args.config_file)
    existing = store.get(name)
    record = provider.create(spec, manifest, existing, store)

    if report.generated:
        secret_store = SecretStore(args.config_file)
        secret_store.put(name, "admin_api_key", report.generated.admin_api_key)
        secret_store.put(name, "secret_key", report.generated.secret_key)

    _echo("")
    _echo(f"Deployed: {record.url or '(no URL recorded)'}")
    _echo(f"Admin key stored in {SecretStore(args.config_file).path}")
    return EXIT_OK


def _resolve_backup(args, name: str, provider_name: str) -> BackupOptions:
    """Backup options from the flags, with the HF repo filled in.

    The huggingface provider creates and wires its own backup dataset, so an
    HF backup is left to it here; an S3 backup alongside still applies.
    """
    backup = backup_from_args(args, name)
    if provider_name == "huggingface" and "hf" in backup.kinds:
        backup.kinds.remove("hf")
    if "hf" in backup.kinds and not backup.hf_repo:
        if args.dry_run:
            backup.hf_repo = f"<hf-account>/{name}-annotations"
        else:
            try:
                backup.hf_repo = default_hf_repo(backup.hf_token, name)
            except Exception as exc:
                raise BackupOptionsError(
                    f"could not ask HuggingFace who the token belongs to: {exc}")
    return backup


def _git_email() -> Optional[str]:
    import subprocess
    try:
        result = subprocess.run(["git", "config", "user.email"],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _confirm(plan, provider_name: str) -> bool:
    if not sys.stdin.isatty():
        _echo("Not a terminal; re-run with --yes to confirm non-interactively.")
        return False
    cost = plan.estimated_cost_usd_month
    # None means "not estimated" (an unlisted size, a non-dollar price), never
    # free: it used to read "no ongoing cost" for Hetzner, Railway and any size
    # missing from a provider's price table.
    if cost is None:
        money = "cost not estimated; see the plan above"
    elif cost == 0:
        money = "no ongoing cost"
    else:
        money = f"about ${cost:.2f} per month"
    answer = input(f"Create this deployment on {provider_name} ({money})? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


def _load_record(args):
    store = DeploymentStore(args.config_file)
    name = args.name or slugify(_load_task_name(args.config_file))
    record = store.get(name)
    if record is None:
        known = ", ".join(r.name for r in store.list()) or "none"
        raise SystemExit(f"No deployment named '{name}'. Recorded: {known}")
    # Stamp the live config path over whatever create() recorded. Providers need
    # it to open the secret store — the SSH deploy key lives there — and the
    # stored copy is an absolute path that a moved or renamed project breaks.
    record.spec = dict(record.spec)
    record.spec["config_path"] = os.path.abspath(args.config_file)
    return store, record


def cmd_status(args) -> int:
    store, record = _load_record(args)
    token, _ = creds.resolve_token(record.provider, args.token)
    provider = get_provider(record.provider, token=token, console=_echo)
    status = provider.status(record)

    _echo(f"{record.name}  ({record.provider})")
    _echo(f"  state   {status.state}")
    _echo(f"  url     {status.url or record.url or '-'}")
    _echo(f"  healthy {status.healthy}")
    if status.detail:
        _echo(f"  detail  {status.detail}")
    if record.last_pull_at:
        _echo(f"  pulled  {record.last_pull_at}")
    else:
        _echo("  pulled  never")
    return EXIT_OK


def cmd_logs(args) -> int:
    store, record = _load_record(args)
    token, _ = creds.resolve_token(record.provider, args.token)
    provider = get_provider(record.provider, token=token, console=_echo)
    for line in provider.logs(record, lines=args.lines, follow=args.follow):
        _echo(line)
    return EXIT_OK


def _pull_destination(name: str) -> str:
    """A fresh directory under the CWD, never an existing one.

    The timestamp is only to the second, so two pulls in the same second would
    otherwise land in the same directory and the second would be verified
    against the first one's files.
    """
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(os.getcwd(), f"potato-pull-{name}-{stamp}")
    candidate = base
    suffix = 1
    while os.path.exists(candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def cmd_pull(args) -> int:
    store, record = _load_record(args)
    token, _ = creds.resolve_token(record.provider, args.token)
    provider = get_provider(record.provider, token=token, console=_echo)

    dest = args.dest or _pull_destination(record.name)

    result = provider.pull(record, dest)

    from potato.deploy.pull import render_verification, verify_pull

    _echo("")
    _echo(f"Pulled to {result.dest}")
    for note in result.notes:
        _echo(f"  {note}")
    for skipped in result.skipped:
        _echo(f"  skipped {skipped}")

    # Check what landed rather than trusting the transport's own count. An empty
    # result and a study nobody has annotated look identical from the outside,
    # and `destroy` treats "pulled" as permission to delete the host.
    verification = verify_pull(result.dest)
    _echo(render_verification(verification))

    if verification.corrupt:
        _echo("")
        _echo("Refusing to record this as a successful pull: a database came "
              "back unreadable. `destroy` will keep blocking until a good pull "
              "succeeds.")
        return EXIT_ERROR

    if verification.files == 0 and not args.allow_empty:
        _echo("")
        _echo("Nothing came back, so this is not recorded as a pull and "
              "`destroy` will still refuse. If the task genuinely has no "
              "annotations yet, re-run with --allow-empty.")
        return EXIT_ERROR

    store.mark_pulled(record.name)
    return EXIT_OK


def cmd_destroy(args) -> int:
    store, record = _load_record(args)
    token, _ = creds.resolve_token(record.provider, args.token)
    provider = get_provider(record.provider, token=token, console=_echo)

    # Destroying a host with annotations that were never downloaded is the one
    # unrecoverable action here.
    if provider.supports_pull and not record.last_pull_at and not args.force:
        _echo(f"'{record.name}' has never been pulled, so any annotations on it "
              "exist only there.")
        _echo("Run `potato deploy pull` first, or pass --force to discard them.")
        return EXIT_BLOCKED

    if not args.yes and sys.stdin.isatty():
        answer = input(f"Destroy '{record.name}' on {record.provider}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            _echo("Aborted.")
            return EXIT_ABORTED

    provider.destroy(record, keep_data=args.keep_data)
    store.remove(record.name)
    SecretStore(args.config_file).forget(record.name)
    _echo(f"Destroyed {record.name}.")
    return EXIT_OK


def cmd_list(args) -> int:
    records = DeploymentStore(args.config_file).list()
    if not records:
        _echo("No deployments recorded for this config.")
        return EXIT_OK
    _echo(f"{'NAME':20s} {'PROVIDER':14s} {'STATUS':12s} URL")
    for record in records:
        _echo(f"{record.name:20s} {record.provider:14s} {record.status:12s} "
              f"{record.url or '-'}")
    return EXIT_OK


def cmd_providers(args) -> int:
    _echo("Targets:")
    for name in available_providers():
        provider = get_provider(name)
        traits = []
        if provider.ephemeral_fs:
            traits.append("ephemeral filesystem")
        if not provider.public:
            traits.append("local only")
        if provider.supports_pull:
            traits.append("supports pull")
        # An unmet extra is the first thing that will stop someone, so say it
        # here rather than after they have chosen a target and typed a token.
        missing = provider.check_requirements()
        if missing:
            traits.append(f"needs `pip install 'potato-annotation[{provider.install_extra}]'` "
                          f"({', '.join(missing)} missing)")
        _echo(f"  {name:14s} {provider.summary or ', '.join(traits) or 'durable, public'}")
    _echo("")
    _echo("Credentials:")
    for line in creds.describe_available(providers=available_providers()):
        _echo(f"  {line}")

    if getattr(args, "verify", False):
        _echo("")
        _echo("Verifying:")
        for name in available_providers():
            provider = get_provider(name)
            if type(provider).verify_credential is Provider.verify_credential:
                # No identity call, so there is nothing to check and saying
                # "no token configured" would read as a problem.
                continue
            token, _source = creds.resolve_token(name)
            if not token and not creds.is_ambient(name):
                _echo(f"  {name:14s} skipped, no token configured")
                continue
            try:
                identity = get_provider(name, token=token).verify_credential()
            except ProviderError as exc:
                _echo(f"  {name:14s} REJECTED — {exc}")
                continue
            except Exception as exc:  # a provider SDK can raise anything
                _echo(f"  {name:14s} could not be checked — {exc}")
                continue
            if identity is None:
                _echo(f"  {name:14s} no identity call; only `up` can prove it")
            else:
                _echo(f"  {name:14s} OK — {identity}")
    return EXIT_OK


def cmd_button(args) -> int:
    from potato.deploy import button as buttons

    name = args.name or slugify(_load_task_name(args.config_file))
    try:
        # The token is supplied by whoever clicks the button; generation needs
        # only the repo name, from --hf-backup-repo or a token's owner.
        backup = backup_from_args(args, name, require_credentials=False)
        if "hf" in backup.kinds and not backup.hf_repo:
            if not backup.hf_token:
                raise BackupOptionsError(
                    "name the backup dataset with --hf-backup-repo <owner>/<name> "
                    "(or pass --hf-token so its owner can be looked up)")
            # A dry run stays off the network, as `up --dry-run` does.
            if args.dry_run:
                backup.hf_repo = f"<hf-account>/{name}-annotations"
            else:
                try:
                    backup.hf_repo = default_hf_repo(backup.hf_token, name)
                except BackupOptionsError:
                    raise
                except Exception as exc:
                    raise BackupOptionsError(
                        "could not ask HuggingFace who the token belongs to: "
                        f"{exc}")
        result = buttons.generate(args.config_file, args.target, backup, name=name,
                                  image=args.image, template_url=args.template_url,
                                  region=args.region)
    except (BackupOptionsError, buttons.ButtonError) as exc:
        _echo(f"Button: {exc}")
        return EXIT_ERROR

    config_dir = os.path.dirname(os.path.abspath(args.config_file))
    root = buttons.git_root(config_dir) or config_dir
    if args.dry_run:
        for path, content in result.files.items():
            _echo(f"--- {path}")
            _echo(content)
    else:
        try:
            written = buttons.write(result, root, force=args.force)
        except buttons.ButtonError as exc:
            _echo(f"Button: {exc}")
            return EXIT_ERROR
        for path in written:
            _echo(f"wrote {path}")
    for note in result.notes:
        _echo(note)
    if result.badge:
        _echo("")
        _echo("Add this to your README, commit, and push:")
        _echo(f"  {result.badge}")
    return EXIT_OK


COMMANDS = {
    "check": cmd_check, "build": cmd_build, "up": cmd_up, "status": cmd_status,
    "logs": cmd_logs, "pull": cmd_pull, "destroy": cmd_destroy,
    "list": cmd_list, "providers": cmd_providers, "button": cmd_button,
}


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except ProviderError as exc:
        _echo(f"Error: {exc}")
        return EXIT_ERROR
    except creds.CredentialError as exc:
        _echo(str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        _echo("\nInterrupted.")
        return EXIT_ABORTED


if __name__ == "__main__":
    sys.exit(main())
