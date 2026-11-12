"""
``potato download-models``.

The behaviour worth pinning is not the happy path — it is what happens when a
download goes wrong. An unverified or half-written model does not raise; it
produces *wrong masks*, which is far harder to notice than a crash. So a
mismatched file must be deleted rather than kept, and a model with no configured
source must say so plainly instead of failing later with a checksum error the
user cannot act on.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from potato import models_cli


@pytest.fixture
def fake_model(tmp_path, monkeypatch):
    """A one-file model served from a local file:// URL."""
    payload = b"pretend these are model weights" * 100
    src = tmp_path / "source" / "weights.onnx"
    src.parent.mkdir(parents=True)
    src.write_bytes(payload)

    digest = hashlib.sha256(payload).hexdigest()
    model = models_cli.SegmentationModel(
        key="test_model",
        description="Fixture model",
        licence="Test",
        files=[models_cli.ModelFile(
            name="weights.onnx", url=src.as_uri(), sha256=digest, size_mb=0.1)],
    )
    monkeypatch.setitem(models_cli.MODELS, "test_model", model)
    return model, payload, digest


class TestRegistry:
    def test_the_default_model_exists(self):
        assert models_cli.DEFAULT_MODEL in models_cli.MODELS

    def test_every_model_declares_a_licence(self):
        """Licensing is the reason weights are not bundled; it must be stated."""
        for key, model in models_cli.MODELS.items():
            assert model.licence.strip(), f"{key} has no licence line"
            assert model.description.strip(), f"{key} has no description"

    def test_models_without_a_source_are_reported_as_unavailable(self):
        """Rather than pretending, and failing later on a checksum."""
        for key in models_cli.MODELS:
            if not models_cli.MODELS[key].files:
                assert not models_cli.available(key)

    def test_video_propagation_model_is_flagged_as_such(self):
        """Wave 4 depends on knowing which model supports propagation."""
        assert "sam2" in " ".join(models_cli.MODELS).lower()

    def test_non_commercial_models_are_flagged_not_just_described(self):
        """
        EdgeSAM is NTU S-Lab License 1.0, which permits use "for non-commercial
        purpose" only. That is the one licence property that can make a model
        unusable for a given project, and nobody reads a licence name in a list
        — so it is a boolean the UI can surface, not prose.
        """
        assert models_cli.MODELS["edge_sam"].commercial_use is False
        assert "NON-COMMERCIAL" in models_cli.MODELS["edge_sam"].licence

    def test_the_default_model_is_permissively_licensed(self):
        """A default that forbids commercial use would be a trap."""
        default = models_cli.MODELS[models_cli.DEFAULT_MODEL]
        assert default.commercial_use is True
        assert "Apache" in default.licence

    def test_the_listing_shouts_about_non_commercial_licences(self, capsys):
        models_cli.main(["--list"])
        out = capsys.readouterr().out
        assert "NON-COMMERCIAL" in out


class TestListing:
    def test_listing_exits_clean(self, capsys):
        assert models_cli.main(["--list"]) == 0
        out = capsys.readouterr().out
        assert models_cli.DEFAULT_MODEL in out

    def test_no_arguments_lists_rather_than_downloading(self, capsys):
        """A bare invocation must not start a multi-megabyte download."""
        assert models_cli.main([]) == 0
        assert "Model directory" in capsys.readouterr().out

    def test_listing_states_that_nothing_is_bundled(self, capsys):
        models_cli.main(["--list"])
        out = capsys.readouterr().out
        assert "does not bundle" in out
        assert "licence" in out.lower()


class TestDownload:
    def test_downloads_and_verifies(self, fake_model, tmp_path):
        _model, payload, _digest = fake_model
        dest = tmp_path / "models"

        path = models_cli.download_model("test_model", str(dest))

        assert (path / "weights.onnx").read_bytes() == payload
        assert models_cli.installed("test_model", str(dest))

    def test_a_second_run_is_a_no_op(self, fake_model, tmp_path):
        dest = tmp_path / "models"
        models_cli.download_model("test_model", str(dest))
        before = (dest / "test_model" / "weights.onnx").stat().st_mtime_ns
        models_cli.download_model("test_model", str(dest))
        after = (dest / "test_model" / "weights.onnx").stat().st_mtime_ns
        assert before == after, "a valid file was re-downloaded"

    def test_a_corrupted_file_is_replaced(self, fake_model, tmp_path):
        _model, payload, _digest = fake_model
        dest = tmp_path / "models"
        models_cli.download_model("test_model", str(dest))

        target = dest / "test_model" / "weights.onnx"
        target.write_bytes(b"corrupted")

        models_cli.download_model("test_model", str(dest))
        assert target.read_bytes() == payload

    def test_a_checksum_mismatch_deletes_the_file(self, tmp_path, monkeypatch):
        """
        The important one. Keeping a mismatched file means the next run sees a
        model that "exists" and silently produces wrong masks.
        """
        src = tmp_path / "bad.onnx"
        src.write_bytes(b"not what the hash says")
        monkeypatch.setitem(models_cli.MODELS, "bad_model",
                            models_cli.SegmentationModel(
                                key="bad_model", description="d", licence="l",
                                files=[models_cli.ModelFile(
                                    name="bad.onnx", url=src.as_uri(),
                                    sha256="0" * 64, size_mb=0.1)]))

        dest = tmp_path / "models"
        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            models_cli.download_model("bad_model", str(dest))

        assert not (dest / "bad_model" / "bad.onnx").exists()
        assert not list((dest / "bad_model").glob("*.part")), "partial file left"
        assert not models_cli.installed("bad_model", str(dest))

    def test_an_unreachable_url_leaves_nothing_behind(self, tmp_path, monkeypatch):
        monkeypatch.setitem(models_cli.MODELS, "gone_model",
                            models_cli.SegmentationModel(
                                key="gone_model", description="d", licence="l",
                                files=[models_cli.ModelFile(
                                    name="x.onnx",
                                    url=(tmp_path / "missing.onnx").as_uri(),
                                    sha256="0" * 64, size_mb=0.1)]))

        dest = tmp_path / "models"
        with pytest.raises(RuntimeError, match="Could not download"):
            models_cli.download_model("gone_model", str(dest))
        assert not list((dest / "gone_model").glob("*")), "partial file left"


class TestErrors:
    def test_unknown_model_names_the_known_ones(self):
        with pytest.raises(RuntimeError) as exc:
            models_cli.download_model("no_such_model")
        assert "no_such_model" in str(exc.value)
        assert models_cli.DEFAULT_MODEL in str(exc.value)

    def test_a_model_with_no_source_says_so_actionably(self):
        # edge_sam, not mobile_sam: the default now HAS verified weights, so
        # using it here would test nothing.
        assert not models_cli.available("edge_sam"), "pick another example"
        with pytest.raises(RuntimeError) as exc:
            models_cli.download_model("edge_sam")
        message = str(exc.value)
        assert "No download is configured" in message
        # Tells the user what to do instead, rather than just failing.
        assert "checkpoint" in message

    def test_cli_returns_nonzero_on_failure(self, capsys):
        assert models_cli.main(["no_such_model"]) == 1
        assert "error:" in capsys.readouterr().err


class TestCliWiring:
    def test_download_models_is_dispatched_before_config_parsing(self):
        """
        It takes a model name, not a config file, so the server's own parser
        would reject it. Same pattern as `import` and `transcripts`.
        """
        source = Path("potato/flask_server.py").read_text()
        assert "'download-models'" in source
        assert "from potato.models_cli import main as models_main" in source

    def test_importing_the_cli_pulls_in_no_ml_stack(self):
        import ast

        tree = ast.parse(Path("potato/models_cli.py").read_text())
        banned = {"torch", "onnxruntime", "numpy", "cv2", "segment_anything"}
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {(getattr(node, "module", None) or "").split(".")[0]}
                names |= {a.name.split(".")[0] for a in getattr(node, "names", [])}
                assert not (names & banned), f"{names & banned} imported at module level"
