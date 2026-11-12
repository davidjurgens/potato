"""Where baked task templates land when the package directory is read-only.

Potato compiles each task's schemes into a Jinja template at boot. It wrote them
into ``<package>/templates/generated``, which is fine for a checkout and for
``pip install -e .`` but fails for an ordinary install: site-packages is not
writable by the serving user, and the server dies during boot with a
PermissionError. The published container hit it on its first run.

The read-only case is the whole point of these tests, so most of them make a
directory read-only rather than mocking the check.
"""

import os
import stat

import pytest

from potato.server_utils import generated_templates
from potato.server_utils.generated_templates import (
    ENV_VAR,
    resolve_generated_templates_dir,
)


@pytest.fixture(autouse=True)
def clear_env_and_log_flag(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(generated_templates, "_logged", False)


@pytest.fixture
def readonly_dir(tmp_path):
    """A directory the current user cannot create entries in."""
    path = tmp_path / "site-packages-templates"
    path.mkdir()
    path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    yield str(path)
    path.chmod(stat.S_IRWXU)


@pytest.fixture
def writable_dir(tmp_path):
    path = tmp_path / "checkout-templates"
    path.mkdir()
    return str(path)


class TestWritablePackage:
    """The existing arrangement must not change for anyone who had it working."""

    def test_uses_the_package_subdirectory(self, writable_dir):
        result = resolve_generated_templates_dir(writable_dir)
        assert result == os.path.join(writable_dir, "generated")

    def test_creates_it(self, writable_dir):
        assert os.path.isdir(resolve_generated_templates_dir(writable_dir))

    def test_create_false_does_not_create(self, writable_dir):
        result = resolve_generated_templates_dir(writable_dir, create=False)
        assert not os.path.exists(result)

    def test_is_stable_across_calls(self, writable_dir):
        assert (resolve_generated_templates_dir(writable_dir)
                == resolve_generated_templates_dir(writable_dir))


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root writes to read-only directories anyway")
class TestReadOnlyPackage:
    def test_falls_back_instead_of_raising(self, readonly_dir):
        """This is the boot crash: a PermissionError here kills the server."""
        result = resolve_generated_templates_dir(readonly_dir)
        assert os.path.isdir(result)

    def test_fallback_is_outside_the_package(self, readonly_dir):
        result = resolve_generated_templates_dir(readonly_dir)
        assert not result.startswith(readonly_dir)

    def test_fallback_is_writable(self, readonly_dir):
        result = resolve_generated_templates_dir(readonly_dir)
        probe = os.path.join(result, "task.html")
        with open(probe, "w") as handle:
            handle.write("<html></html>")
        assert os.path.isfile(probe)

    def test_fallback_survives_a_restart(self, readonly_dir):
        """A gunicorn worker respawn must find the templates it baked before."""
        first = resolve_generated_templates_dir(readonly_dir)
        with open(os.path.join(first, "task.html"), "w") as handle:
            handle.write("<html></html>")
        generated_templates._logged = False
        second = resolve_generated_templates_dir(readonly_dir)
        assert second == first
        assert os.path.isfile(os.path.join(second, "task.html"))

    def test_two_installs_do_not_collide(self, tmp_path):
        """Otherwise one Potato's templates serve another Potato's task."""
        paths = []
        for name in ("install-a", "install-b"):
            directory = tmp_path / name
            directory.mkdir()
            directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
            paths.append(resolve_generated_templates_dir(str(directory)))
            directory.chmod(stat.S_IRWXU)
        assert paths[0] != paths[1]


class TestEnvironmentOverride:
    def test_wins_over_a_writable_package(self, writable_dir, tmp_path,
                                          monkeypatch):
        chosen = tmp_path / "explicit"
        monkeypatch.setenv(ENV_VAR, str(chosen))
        assert resolve_generated_templates_dir(writable_dir) == str(chosen)

    def test_directory_is_created(self, writable_dir, tmp_path, monkeypatch):
        chosen = tmp_path / "explicit" / "nested"
        monkeypatch.setenv(ENV_VAR, str(chosen))
        assert os.path.isdir(resolve_generated_templates_dir(writable_dir))

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_unusable_override_names_itself_in_the_error(self, writable_dir,
                                                         readonly_dir,
                                                         monkeypatch):
        monkeypatch.setenv(ENV_VAR, os.path.join(readonly_dir, "nope"))
        with pytest.raises(RuntimeError, match=ENV_VAR):
            resolve_generated_templates_dir(writable_dir)


class TestCallersAgree:
    """The generator writes these files and the Flask loader reads them.

    If the two compute the path differently the annotation page 500s with no
    other symptom, so no caller may build the path itself.
    """

    @pytest.mark.parametrize("module_path", [
        "potato/flask_server.py",
        "potato/server_utils/front_end.py",
    ])
    def test_no_caller_hardcodes_the_subdirectory(self, module_path):
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(root, module_path)) as handle:
            source = handle.read()
        offenders = [line.strip() for line in source.splitlines()
                     if 'os.path.join(' in line and '"generated"' in line
                     and not line.lstrip().startswith("#")]
        assert not offenders, (
            f"{module_path} builds the generated-template path itself: "
            f"{offenders}. Use resolve_generated_templates_dir so the writer "
            "and the template loader cannot disagree.")

    def test_flask_and_front_end_resolve_identically(self, writable_dir):
        from potato.server_utils.front_end import (
            resolve_generated_templates_dir as from_front_end)
        assert (from_front_end(writable_dir)
                == resolve_generated_templates_dir(writable_dir))
