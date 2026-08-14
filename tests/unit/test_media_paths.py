"""
Unit tests for potato.media.paths — the one media traversal guard.

The guard had been written out three times before this module existed, twice
with a comment promising the copies matched. Every caller hands the result to
something that reads bytes off disk, and the critique service then sends those
bytes to a third-party model, so a weaker check in any one copy is an
exfiltration path rather than a tidiness problem.
"""

import os

import pytest

from potato.media.paths import media_root, resolve_media_path, resolve_media_url


@pytest.fixture
def project(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "scene.png").write_bytes(b"not really a png")
    (media / "nested").mkdir()
    (media / "nested" / "deep.png").write_bytes(b"also not a png")
    (tmp_path.parent / "outside.png").write_bytes(b"secret")
    return {"task_dir": str(tmp_path), "media_directory": "media"}


class TestMediaRoot:
    def test_relative_media_directory_resolves_under_task_dir(self, project):
        assert media_root(project) == os.path.realpath(
            os.path.join(project["task_dir"], "media"))

    def test_absolute_media_directory_is_used_as_is(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        config = {"task_dir": str(tmp_path), "media_directory": str(elsewhere)}
        assert media_root(config) == os.path.realpath(str(elsewhere))

    def test_the_default_directory_is_media(self, tmp_path):
        assert media_root({"task_dir": str(tmp_path)}).endswith("media")


class TestResolveMediaPath:
    def test_a_plain_filename_resolves(self, project):
        root, path = resolve_media_path(project, "scene.png")
        assert path == os.path.join(root, "scene.png")

    def test_a_nested_path_resolves(self, project):
        _, path = resolve_media_path(project, "nested/deep.png")
        assert path.endswith(os.path.join("nested", "deep.png"))

    def test_traversal_is_refused(self, project):
        assert resolve_media_path(project, "../outside.png") == (None, None)
        assert resolve_media_path(project, "../../outside.png") == (None, None)
        assert resolve_media_path(project, "nested/../../outside.png") == (None, None)

    def test_an_absolute_path_is_refused(self, project):
        """``os.path.join(root, "/etc/passwd")`` returns ``/etc/passwd`` — the
        join silently discards the root on an absolute second argument, so this
        has to be checked explicitly rather than left to the containment test.

        Unreachable through the Flask route, whose ``<path:...>`` converter
        never yields a leading slash, but very reachable through the critique
        service, which takes whatever a project's data file says.
        """
        assert resolve_media_path(project, "/etc/passwd") == (None, None)

    def test_a_symlink_pointing_out_of_the_tree_is_refused(self, project,
                                                           tmp_path):
        """The guard resolves symlinks before comparing, so a link planted
        inside media/ cannot be used to read the rest of the disk."""
        link = tmp_path / "media" / "escape.png"
        try:
            os.symlink(str(tmp_path.parent / "outside.png"), str(link))
        except (OSError, NotImplementedError):  # pragma: no cover - platform
            pytest.skip("symlinks unavailable")
        assert resolve_media_path(project, "escape.png") == (None, None)

    def test_existence_is_not_checked_here(self, project):
        """Callers differ on whether missing means 404, fallback or error;
        folding it in would make the traversal result ambiguous."""
        _, path = resolve_media_path(project, "does-not-exist.png")
        assert path is not None
        assert not os.path.exists(path)


class TestResolveMediaUrl:
    def test_a_media_url_path_resolves_to_the_file(self, project):
        assert resolve_media_url(project, "/media/scene.png") is not None

    def test_a_bare_media_prefix_resolves(self, project):
        assert resolve_media_url(project, "media/scene.png") is not None

    def test_remote_and_data_references_are_not_local_files(self, project):
        for reference in ("http://example.com/a.png",
                          "https://example.com/a.png",
                          "data:image/png;base64,AAAA"):
            assert resolve_media_url(project, reference) is None

    def test_traversal_returns_nothing(self, project):
        assert resolve_media_url(project, "/media/../../outside.png") is None

    def test_a_missing_file_returns_nothing(self, project):
        assert resolve_media_url(project, "/media/absent.png") is None

    def test_an_empty_reference_returns_nothing(self, project):
        for reference in ("", None, "   "):
            assert resolve_media_url(project, reference) is None


class TestCallersShareTheGuard:
    def test_the_media_proxy_delegates(self):
        """Not a duplicate implementation with a comment promising it matches."""
        import pathlib

        source = pathlib.Path("potato/media/routes.py").read_text()
        assert "from potato.media.paths import resolve_media_path" in source
        assert "startswith(media_dir" not in source

    def test_serve_media_delegates(self):
        import pathlib

        source = pathlib.Path("potato/routes.py").read_text()
        assert "from potato.media.paths import resolve_media_path" in source

    def test_the_critique_service_delegates(self):
        import pathlib

        source = pathlib.Path("potato/ai/critique_service.py").read_text()
        assert "resolve_media_url" in source
