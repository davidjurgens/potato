"""`potato deploy button`: the files a one-click deploy reads from a repository."""

import json
import os
import re
import subprocess

import pytest
import yaml

from potato.deploy import button, cli
from potato.deploy.backup_options import BackupOptions
from potato.deploy.button import DEPLOY_CONFIG, DOCKERFILE, ButtonError, generate, write


def backup():
    return BackupOptions(kinds=["hf"], hf_token=None, hf_repo="lab/study-annotations")


@pytest.fixture
def repo(tmp_path):
    """A git repository with the task in a subdirectory."""
    root = tmp_path / "repo"
    task = root / "studies" / "pilot"
    (task / "data").mkdir(parents=True)
    (task / "data" / "items.json").write_text('[{"id":"1","text":"hi"}]')
    config = {"task_dir": ".", "annotation_task_name": "pilot",
              "data_files": ["data/items.json"],
              "output_annotation_dir": "annotation_output/",
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [], "debug": True}
    (task / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                    "git@github.com:lab/study.git"], check=True)
    return root


def config_of(repo):
    return str(repo / "studies" / "pilot" / "config.yaml")


class TestCommon:
    def test_the_users_config_is_never_edited(self, repo):
        original = open(config_of(repo)).read()
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        write(result, str(repo))
        assert open(config_of(repo)).read() == original

    def test_the_deploy_config_is_hardened_and_backed_up(self, repo):
        result = generate(config_of(repo), "render", backup(), name="pilot")
        deployed = yaml.safe_load(result.files[f"studies/pilot/{DEPLOY_CONFIG}"])
        assert deployed["debug"] is False
        assert deployed["backup"]["restore_on_boot"] is True
        assert deployed["backup"]["sinks"][0]["repo_id"] == "lab/study-annotations"

    @pytest.mark.parametrize("target,reason", [
        ("heroku", "A Heroku button"), ("render", "A Render button"),
        ("aws", "An AWS Launch Stack button")])
    def test_refuses_without_a_backup(self, repo, target, reason):
        with pytest.raises(ButtonError, match="--backup") as excinfo:
            generate(config_of(repo), target, BackupOptions(), name="pilot")
        # Each target gave "A aws button ... (or, on Lightsail, ...)" before.
        assert str(excinfo.value).startswith(reason)
        if target != "aws":
            assert "Lightsail" not in str(excinfo.value)

    def test_a_dockerignore_keeps_secrets_out_of_the_image(self, repo):
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        ignore = result.files[".dockerignore"].splitlines()
        # Anchored patterns miss a task in a subdirectory; this one is in one.
        assert "**/.potato" in ignore and "**/*.sqlite" in ignore

    def test_an_incomplete_dockerignore_is_reported_not_rewritten(self, repo):
        (repo / ".dockerignore").write_text("node_modules\n")
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        assert ".dockerignore" not in result.files
        assert any(".potato" in note for note in result.notes)

    def test_existing_files_are_not_overwritten(self, repo):
        (repo / "app.json").write_text("{}")
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        with pytest.raises(ButtonError, match="--force"):
            write(result, str(repo))

    def test_ssh_remote_becomes_an_https_badge(self, repo):
        result = generate(config_of(repo), "render", backup(), name="pilot")
        assert "repo=https://github.com/lab/study)" in result.badge


    def test_unignored_secrets_are_warned_about(self, repo):
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        assert any("not in .gitignore" in n and ".potato" in n for n in result.notes)
        (repo / ".gitignore").write_text(".potato/\nadmin_api_key.txt\n"
                                         "annotation_output/\n*.sqlite\n")
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        assert not any("not in .gitignore" in n for n in result.notes)


class TestHeroku:
    def test_secrets_are_generated_by_heroku_and_never_written(self, repo):
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        app = json.loads(result.files["app.json"])
        assert app["stack"] == "container"
        assert app["env"]["POTATO_SECRET_KEY"] == {
            "description": "Signs session cookies.", "generator": "secret"}
        assert app["env"]["HF_TOKEN"]["required"] is True
        assert app["formation"]["web"]["quantity"] == 1

    def test_dockerfile_copies_the_task_subdirectory(self, repo):
        result = generate(config_of(repo), "heroku", backup(), name="pilot")
        dockerfile = result.files[DOCKERFILE]
        assert "COPY studies/pilot/ /app" in dockerfile
        assert f"POTATO_CONFIG={DEPLOY_CONFIG}" in dockerfile
        assert result.files["heroku.yml"] == f"build:\n  docker:\n    web: {DOCKERFILE}\n"


class TestRender:
    def test_blueprint_is_one_instance_with_generated_secrets(self, repo):
        result = generate(config_of(repo), "render", backup(), name="pilot")
        service = yaml.safe_load(result.files["render.yaml"])["services"][0]
        assert service["numInstances"] == 1
        env = {v["key"]: v for v in service["envVars"]}
        assert env["POTATO_ADMIN_API_KEY"]["generateValue"] is True
        assert env["HF_TOKEN"]["sync"] is False


class TestAWS:
    def _template(self, repo, **kwargs):
        result = generate(config_of(repo), "aws", backup(), name="pilot", **kwargs)
        return result, yaml.safe_load(result.files["potato-lightsail.cfn.yaml"])

    def test_template_is_instance_plus_static_ip(self, repo):
        _result, template = self._template(repo)
        resources = template["Resources"]
        assert resources["Instance"]["Type"] == "AWS::Lightsail::Instance"
        assert resources["StaticIp"]["Properties"]["AttachedTo"] == {"Ref": "Instance"}
        ports = resources["Instance"]["Properties"]["Networking"]["Ports"]
        assert sorted(p["FromPort"] for p in ports) == [22, 80, 443]

    def test_tokens_are_noecho_parameters(self, repo):
        _result, template = self._template(repo)
        assert template["Parameters"]["HfToken"]["NoEcho"] is True
        assert template["Parameters"]["ProjectRepo"]["Default"] == \
            "https://github.com/lab/study"
        assert template["Parameters"]["ProjectPath"]["Default"] == "studies/pilot"

    def test_the_launch_script_is_valid_bash_after_substitution(self, repo, tmp_path):
        """CloudFormation's Fn::Sub replaces ${Param}; bash must parse the result."""
        _result, template = self._template(repo)
        script = template["Resources"]["Instance"]["Properties"]["UserData"]["Fn::Sub"]
        substituted = re.sub(r"\$\{(\w+)\}", "VALUE", script)
        path = tmp_path / "launch.sh"
        path.write_text(substituted)
        check = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert check.returncode == 0, check.stderr

    def test_only_template_parameters_are_substituted(self, repo):
        """A stray ${...} would make CloudFormation reject the template."""
        _result, template = self._template(repo)
        script = template["Resources"]["Instance"]["Properties"]["UserData"]["Fn::Sub"]
        referenced = set(re.findall(r"\$\{([\w:.]+)\}", script))
        assert referenced <= set(template["Parameters"]) | {"AWS::StackName"}

    def test_secrets_are_generated_on_the_instance(self, repo):
        _result, template = self._template(repo)
        script = template["Resources"]["Instance"]["Properties"]["UserData"]["Fn::Sub"]
        assert "POTATO_SECRET_KEY=$(openssl rand" in script
        assert "umask 077" in script

    def test_launch_link_needs_the_s3_template_url(self, repo):
        result, _ = self._template(repo)
        assert "<quick-create-link>" in result.badge
        result, _ = self._template(repo, template_url="https://b.s3.amazonaws.com/t.yaml")
        assert "templateURL=https%3A%2F%2Fb.s3.amazonaws.com%2Ft.yaml" in result.badge


class TestCLI:
    def test_dry_run_writes_nothing(self, repo, capsys):
        code = cli.main(["button", config_of(repo), "--target", "render",
                         "--backup", "hf", "--hf-backup-repo", "lab/r", "--dry-run"])
        assert code == cli.EXIT_OK
        assert not (repo / "render.yaml").exists()
        assert "render.yaml" in capsys.readouterr().out

    def test_writes_files_and_prints_the_badge(self, repo, capsys):
        code = cli.main(["button", config_of(repo), "--target", "heroku",
                         "--backup", "hf", "--hf-backup-repo", "lab/r"])
        assert code == cli.EXIT_OK
        assert (repo / "app.json").exists()
        assert "herokucdn.com/deploy/button.svg" in capsys.readouterr().out

    def test_hf_backup_needs_a_repo_name(self, repo, capsys, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        code = cli.main(["button", config_of(repo), "--target", "heroku",
                         "--backup", "hf"])
        assert code == cli.EXIT_ERROR
        assert "--hf-backup-repo" in capsys.readouterr().out

    def test_dry_run_without_a_repo_name_stays_off_the_network(
            self, repo, capsys, monkeypatch):
        # It called whoami-v2 to name the dataset, so a dry run reached
        # HuggingFace and a bad token ended in an HfHubHTTPError traceback.
        def no_network(*_args, **_kwargs):
            raise AssertionError("a dry run asked HuggingFace who the token is")
        monkeypatch.setattr(cli, "default_hf_repo", no_network)
        code = cli.main(["button", config_of(repo), "--target", "render",
                         "--backup", "hf", "--hf-token", "x", "--dry-run"])
        assert code == cli.EXIT_OK
        assert "<hf-account>/" in capsys.readouterr().out

    def test_a_rejected_token_is_an_error_not_a_traceback(
            self, repo, capsys, monkeypatch):
        def rejected(*_args, **_kwargs):
            raise RuntimeError("401 Client Error: Unauthorized")
        monkeypatch.setattr(cli, "default_hf_repo", rejected)
        code = cli.main(["button", config_of(repo), "--target", "render",
                         "--backup", "hf", "--hf-token", "x"])
        assert code == cli.EXIT_ERROR
        assert "could not ask HuggingFace" in capsys.readouterr().out
        assert not (repo / "render.yaml").exists()
