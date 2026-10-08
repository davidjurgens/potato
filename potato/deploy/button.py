"""One-click deploy buttons: ``potato deploy button``.

A button deploys a git repository, not a laptop, so this writes the files each
host reads into the project's repository and prints the badge to put in its
README. Commit, push, click.

Nothing here edits the user's own config. A hardened copy with the backup
block, ``potato.deploy.yaml``, is written beside it and the generated files
point at that. Secrets are never written: Heroku and Render generate them at
deploy time, and the Lightsail launch script generates them on the machine.

Targets:

* ``heroku`` — app.json (container stack, generated secrets), heroku.yml and
  Dockerfile.potato.
* ``render`` — render.yaml, a Blueprint with Dockerfile.potato.
* ``aws`` — potato-lightsail.cfn.yaml, a CloudFormation template for a
  Lightsail instance, plus the quick-create "Launch Stack" link once the
  template is in S3.
* ``railway`` — Railway publishes templates from its dashboard only, so this
  prints the steps.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from potato.deploy.backup_options import BackupOptions, apply_to_config
from potato.deploy.preflight import harden_config

TARGETS = ("heroku", "render", "aws", "railway")

#: Why each target's button refuses to run without a backup.
_NEEDS_BACKUP = {
    "heroku": "A Heroku button deploys onto a disk that is wiped at least daily",
    "render": "A Render button deploys onto a disk that does not survive a restart",
    "aws": ("An AWS Launch Stack button creates an instance nobody pulls the "
            "annotations from"),
}
DEPLOY_CONFIG = "potato.deploy.yaml"
DOCKERFILE = "Dockerfile.potato"
from potato.deploy.image import DEFAULT_IMAGE  # noqa: E402

#: What must never be copied into an image built from the repository.
#: .dockerignore patterns are anchored at the build context's root, so a task in
#: a subdirectory needs the ``**/`` form; plain ``.potato`` matched nothing there
#: and the deploy secrets went into the image.
DOCKERIGNORE = [".git", "**/.potato", "**/annotation_output", "**/*.sqlite",
                "**/*.sqlite-wal", "**/*.sqlite-shm", "**/admin_api_key.txt",
                "**/__pycache__", "**/*.log"]

#: What must never be committed to the repository a button deploys from.
#: Directories end in "/" so `git check-ignore` matches a `dir/` pattern even
#: before the directory exists.
GIT_PRIVATE = (".potato/", "admin_api_key.txt", "annotation_output/", "project.sqlite")


class ButtonError(ValueError):
    pass


@dataclass
class ButtonResult:
    files: Dict[str, str] = field(default_factory=dict)   # repo-relative path -> content
    badge: str = ""
    notes: List[str] = field(default_factory=list)


def git_root(path: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def repo_url(root: Optional[str]) -> Optional[str]:
    """The origin as an https URL, which is what every button wants."""
    if not root:
        return None
    try:
        out = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    url = out.stdout.strip()
    if url.startswith("git@"):
        host, _, path = url[4:].partition(":")
        url = f"https://{host}/{path}"
    return url[:-4] if url.endswith(".git") else (url or None)


def deploy_config(config_path: str, backup: BackupOptions) -> str:
    """The hardened config with the backup block, as YAML text."""
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    hardened = apply_to_config(harden_config(config), backup)
    return yaml.safe_dump(hardened, sort_keys=False, allow_unicode=True)


def generate(config_path: str, target: str, backup: BackupOptions, *, name: str,
             image: Optional[str] = None, root: Optional[str] = None,
             url: Optional[str] = None, template_url: Optional[str] = None,
             region: str = "us-east-1") -> ButtonResult:
    if target not in TARGETS:
        raise ButtonError(f"Unknown target {target!r}; use one of {', '.join(TARGETS)}.")
    config_dir = os.path.dirname(os.path.abspath(config_path))
    root = root or git_root(config_dir) or config_dir
    url = url or repo_url(root)
    project_rel = os.path.relpath(config_dir, root)
    project_rel = "" if project_rel == "." else project_rel.replace(os.sep, "/")
    image = image or DEFAULT_IMAGE

    if target == "railway":
        return _railway(name)
    if target in _NEEDS_BACKUP and not backup.enabled:
        raise ButtonError(
            f"{_NEEDS_BACKUP[target]}, so the button needs a backup: pass "
            "--backup hf or --backup s3 --s3-bucket <bucket>.")

    result = ButtonResult()
    result.files[_join(project_rel, DEPLOY_CONFIG)] = deploy_config(config_path, backup)
    result.notes += _dockerignore_notes(root, result)
    result.notes += _gitignore_notes(root, config_dir)

    if target == "aws":
        return _aws(result, backup, name=name, url=url, project_rel=project_rel,
                    image=image, template_url=template_url, region=region)

    result.files[DOCKERFILE] = _dockerfile(image, project_rel)
    if target == "heroku":
        result.files["app.json"] = json.dumps(_app_json(name, backup), indent=2) + "\n"
        result.files["heroku.yml"] = f"build:\n  docker:\n    web: {DOCKERFILE}\n"
        result.badge = ("[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)]"
                        f"(https://heroku.com/deploy?template={url or '<repo-url>'})")
    else:
        result.files["render.yaml"] = yaml.safe_dump(_render_yaml(name, backup),
                                                     sort_keys=False)
        result.badge = ("[![Deploy to Render](https://render.com/images/"
                        "deploy-to-render-button.svg)]"
                        f"(https://render.com/deploy?repo={url or '<repo-url>'})")
    if not url:
        result.notes.append("No git remote named origin; replace <repo-url> in the badge.")
    return result


def write(result: ButtonResult, root: str, *, force: bool = False) -> List[str]:
    """Write the files, refusing to overwrite unless ``force``."""
    written = []
    for relative, content in result.files.items():
        path = os.path.join(root, *relative.split("/"))
        if os.path.exists(path) and not force:
            with open(path, "r", encoding="utf-8") as handle:
                if handle.read() == content:
                    continue
            raise ButtonError(f"{relative} already exists; pass --force to replace it.")
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        written.append(relative)
    return written


# -- per target --------------------------------------------------------


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def _dockerfile(image: str, project_rel: str) -> str:
    from potato.deploy.providers.vm_base import render_template

    return render_template("derived.Dockerfile.j2", image=image,
                           config_rel=DEPLOY_CONFIG, threads=8,
                           source_dir=(project_rel + "/") if project_rel else ".")


def _dockerignore_notes(root: str, result: ButtonResult) -> List[str]:
    path = os.path.join(root, ".dockerignore")
    if not os.path.exists(path):
        result.files[".dockerignore"] = (
            "# Written by `potato deploy button`: none of this may reach an image.\n"
            + "\n".join(DOCKERIGNORE) + "\n")
        return []
    with open(path, "r", encoding="utf-8") as handle:
        present = {line.strip().rstrip("/") for line in handle}
    missing = [entry for entry in DOCKERIGNORE if entry not in present]
    if missing:
        return [f".dockerignore exists but does not exclude {', '.join(missing)}. "
                "Add them: .potato holds the admin key, and collected data must not "
                "be baked into an image."]
    return []


def _gitignore_notes(root: str, config_dir: str) -> List[str]:
    """A button deploys from a pushed repository, so these must not be pushed."""
    exposed = []
    for name in GIT_PRIVATE:
        path = os.path.join(config_dir, name.rstrip("/")) + ("/" if name.endswith("/") else "")
        try:
            ignored = subprocess.run(["git", "-C", root, "check-ignore", "-q", path],
                                     capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            continue
        if not ignored:
            exposed.append(os.path.relpath(path.rstrip("/"), root))
    if not exposed:
        return []
    return ["WARNING: not in .gitignore: " + ", ".join(exposed) + ". The button "
            "deploys from your pushed repository; .potato holds the admin key and "
            "deploy secrets, and the rest is collected data. Add them to "
            ".gitignore before you commit."]


def _backup_env(backup: BackupOptions) -> Dict[str, str]:
    """Credentials the person clicking the button must supply."""
    wanted = {}
    if "hf" in backup.kinds:
        wanted["HF_TOKEN"] = "A HuggingFace token with write access, for the backup dataset."
    if "s3" in backup.kinds:
        wanted["POTATO_S3_ACCESS_KEY_ID"] = "Access key for the backup bucket."
        wanted["POTATO_S3_SECRET_ACCESS_KEY"] = "Secret key for the backup bucket."
    return wanted


def _app_json(name: str, backup: BackupOptions) -> Dict:
    env = {
        "POTATO_SECRET_KEY": {"description": "Signs session cookies.",
                              "generator": "secret"},
        "POTATO_ADMIN_API_KEY": {"description": "Admin API key; read it with "
                                 "`heroku config:get POTATO_ADMIN_API_KEY`.",
                                 "generator": "secret"},
        "GUNICORN_WORKERS": {"description": "Potato holds its state in one process.",
                             "value": "1"},
        "POTATO_NONINTERACTIVE": {"value": "1"},
    }
    for key, description in _backup_env(backup).items():
        env[key] = {"description": description, "required": True}
    return {
        "name": f"Potato: {name}",
        "description": "A Potato annotation task.",
        "repository": "",
        "stack": "container",
        "env": env,
        "formation": {"web": {"quantity": 1, "size": "basic"}},
    }


def _render_yaml(name: str, backup: BackupOptions) -> Dict:
    env_vars = [
        {"key": "POTATO_SECRET_KEY", "generateValue": True},
        {"key": "POTATO_ADMIN_API_KEY", "generateValue": True},
        {"key": "GUNICORN_WORKERS", "value": "1"},
        {"key": "POTATO_NONINTERACTIVE", "value": "1"},
    ]
    env_vars += [{"key": key, "sync": False} for key in _backup_env(backup)]
    return {"services": [{
        "type": "web",
        "name": f"potato-{name}",
        "runtime": "docker",
        "dockerfilePath": f"./{DOCKERFILE}",
        "plan": "free",
        "numInstances": 1,
        "healthCheckPath": "/health",
        "envVars": env_vars,
    }]}


def _aws(result: ButtonResult, backup: BackupOptions, *, name: str, url: Optional[str],
         project_rel: str, image: str, template_url: Optional[str],
         region: str) -> ButtonResult:
    result.files["potato-lightsail.cfn.yaml"] = lightsail_template(
        repo=url or "", project_path=project_rel or ".", image=image)
    launch = "https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png"
    if template_url:
        query = urllib.parse.urlencode({"templateURL": template_url,
                                        "stackName": f"potato-{name}"})
        link = (f"https://console.aws.amazon.com/cloudformation/home?region={region}"
                f"#/stacks/create/review?{query}")
        result.badge = f"[![Launch Stack]({launch})]({link})"
    else:
        result.badge = f"[![Launch Stack]({launch})](<quick-create-link>)"
        result.notes.append(
            "CloudFormation reads templates from S3. Upload potato-lightsail.cfn.yaml "
            "(`aws s3 cp potato-lightsail.cfn.yaml s3://<bucket>/`) and re-run with "
            "--template-url https://<bucket>.s3.amazonaws.com/potato-lightsail.cfn.yaml.")
    if not url:
        result.notes.append("No git remote named origin; set ProjectRepo when launching.")
    result.notes.append(
        "The repository must be public: the instance clones it with no credentials.")
    result.notes.append(
        "The admin API key is generated on the instance. Read it from the Lightsail "
        "browser SSH: sudo grep ADMIN /opt/potato/potato.env")
    return result


def lightsail_template(*, repo: str, project_path: str, image: str) -> str:
    """A CloudFormation template: Lightsail instance + static IP + launch script."""
    from potato.deploy.providers.base import DeploySpec
    from potato.deploy.providers.vm_base import (
        APP_DIR, APP_PORT, CADDY_CONTAINER, CADDY_IMAGE, CONTAINER, DATA_DIR,
        ENV_FILE, IP_PLACEHOLDER, LETSENCRYPT_DIRECTORY, render_template)

    spec = DeploySpec(name="button", config_path=DEPLOY_CONFIG, image=image)
    cert_dir = f"{DATA_DIR}/caddy"
    launch = render_template(
        "lightsail-launch.sh.j2",
        app_dir=APP_DIR, data_dir=DATA_DIR, env_file=ENV_FILE,
        config_rel=DEPLOY_CONFIG, image=image, caddy_image=CADDY_IMAGE,
        ip_placeholder=IP_PLACEHOLDER,
        potato_service=render_template(
            "potato.service.j2", container_name=CONTAINER, env_file=ENV_FILE,
            app_port=APP_PORT, app_dir=APP_DIR, data_dir=DATA_DIR, image=image,
            deployment_name=spec.name),
        caddy_service=render_template(
            "caddy.service.j2", container_name=CADDY_CONTAINER,
            caddy_image=CADDY_IMAGE, cert_dir=cert_dir, app_port=APP_PORT),
        caddyfile=render_template(
            "Caddyfile.j2", domain=None, public_host=IP_PLACEHOLDER,
            app_port=APP_PORT, cert_dir=cert_dir,
            acme_directory=LETSENCRYPT_DIRECTORY, acme_email=None))

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "A Potato annotation task on one Lightsail instance "
                       "(potato deploy button --target aws).",
        "Parameters": {
            "ProjectRepo": {"Type": "String", "Default": repo,
                            "Description": "Public git URL of the task repository."},
            "ProjectPath": {"Type": "String", "Default": project_path,
                            "Description": "Directory inside the repo holding the task."},
            "BundleId": {"Type": "String", "Default": "small_3_0",
                         "AllowedValues": ["micro_3_0", "small_3_0", "medium_3_0"],
                         "Description": "small_3_0 is 2 GB, $12/month."},
            "AvailabilityZone": {"Type": "String", "Default": "us-east-1a"},
            "HfToken": {"Type": "String", "NoEcho": True, "Default": "",
                        "Description": "HuggingFace write token for the backup."},
            "S3AccessKeyId": {"Type": "String", "NoEcho": True, "Default": ""},
            "S3SecretAccessKey": {"Type": "String", "NoEcho": True, "Default": ""},
        },
        "Resources": {
            "Instance": {
                "Type": "AWS::Lightsail::Instance",
                "Properties": {
                    "InstanceName": {"Fn::Sub": "potato-${AWS::StackName}"},
                    "AvailabilityZone": {"Ref": "AvailabilityZone"},
                    "BlueprintId": "ubuntu_24_04",
                    "BundleId": {"Ref": "BundleId"},
                    "Networking": {"Ports": [
                        {"FromPort": port, "ToPort": port, "Protocol": "tcp"}
                        for port in (22, 80, 443)]},
                    "UserData": {"Fn::Sub": launch},
                    "Tags": [{"Key": "potato", "Value": {"Ref": "AWS::StackName"}}],
                },
            },
            "StaticIp": {
                "Type": "AWS::Lightsail::StaticIp",
                "Properties": {
                    "StaticIpName": {"Fn::Sub": "potato-${AWS::StackName}-ip"},
                    "AttachedTo": {"Ref": "Instance"},
                },
            },
        },
        "Outputs": {
            "URL": {"Description": "Give this to annotators (ready a few minutes "
                                   "after the stack completes).",
                    "Value": {"Fn::Sub": "https://${StaticIp.IpAddress}"}},
        },
    }
    return yaml.safe_dump(template, sort_keys=False, width=1000)


def _railway(name: str) -> ButtonResult:
    result = ButtonResult()
    result.notes = [
        "Railway templates are created in its dashboard, not from a file:",
        f"  1. Deploy once with `potato deploy up <config> --provider railway "
        f"--backup hf`.",
        "  2. In the Railway project, open Settings → Generate Template.",
        "  3. Mark POTATO_SECRET_KEY and POTATO_ADMIN_API_KEY as generated secrets "
        "and HF_TOKEN as required.",
        "  4. Publish; Railway gives you the button markdown.",
    ]
    return result
