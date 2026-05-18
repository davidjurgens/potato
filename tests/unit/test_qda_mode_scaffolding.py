"""Unit tests for potato.qda_mode scaffolding (config, manager, routes)."""

import pytest
from flask import Flask

from potato.qda_mode import (
    QDAModeConfig,
    clear_qda_mode_manager,
    get_qda_mode_manager,
    init_qda_mode_manager,
    parse_qda_mode_config,
    qda_mode_bp,
)
from potato.qda_mode.config import CodebookConfig, MemosConfig


@pytest.fixture(autouse=True)
def _reset_singleton():
    clear_qda_mode_manager()
    yield
    clear_qda_mode_manager()


class TestParseConfig:
    def test_missing_block_returns_disabled(self):
        cfg = parse_qda_mode_config({})
        assert cfg.enabled is False
        assert cfg.codebook is None

    def test_non_mapping_block_treated_as_disabled(self):
        cfg = parse_qda_mode_config({"qda_mode": "true"})
        assert cfg.enabled is False

    def test_enabled_block_parses_defaults(self):
        cfg = parse_qda_mode_config({"qda_mode": {"enabled": True}})
        assert cfg.enabled is True
        assert isinstance(cfg.memos, MemosConfig)
        assert cfg.memos.enabled is True
        assert cfg.memos.show_sidebar_by_default is True
        assert cfg.codebook is None  # opt-in only when explicitly configured

    def test_memos_subblock(self):
        cfg = parse_qda_mode_config({"qda_mode": {
            "enabled": True,
            "memos": {"enabled": False, "show_sidebar_by_default": False},
        }})
        assert cfg.memos.enabled is False
        assert cfg.memos.show_sidebar_by_default is False

    def test_codebook_subblock(self):
        cfg = parse_qda_mode_config({"qda_mode": {
            "enabled": True,
            "codebook": {"enabled": True, "mode": "extensible"},
        }})
        assert cfg.codebook is not None
        assert cfg.codebook.enabled is True
        assert cfg.codebook.mode == "extensible"

    def test_unknown_keys_preserved_in_extras(self):
        cfg = parse_qda_mode_config({"qda_mode": {
            "enabled": True,
            "queries": {"enabled": True},  # forward-compatible future block
        }})
        assert "queries" in cfg.extras
        assert cfg.extras["queries"] == {"enabled": True}


class TestValidate:
    def test_valid_codebook_modes(self):
        for mode in ("open", "extensible", "fixed"):
            cfg = QDAModeConfig(
                enabled=True,
                codebook=CodebookConfig(enabled=True, mode=mode),
            )
            assert cfg.validate() == []

    def test_invalid_codebook_mode_returns_error(self):
        cfg = QDAModeConfig(
            enabled=True,
            codebook=CodebookConfig(enabled=True, mode="nonsense"),
        )
        errors = cfg.validate()
        assert errors
        assert "mode" in errors[0]


class TestManager:
    def test_disabled_config_returns_none(self):
        result = init_qda_mode_manager({})
        assert result is None
        assert get_qda_mode_manager() is None

    def test_enabled_config_initializes_singleton(self, tmp_path):
        result = init_qda_mode_manager({
            "qda_mode": {"enabled": True},
            "task_dir": str(tmp_path),
        })
        assert result is not None
        assert get_qda_mode_manager() is result
        assert result.task_dir == str(tmp_path)

    def test_double_init_returns_same_instance(self, tmp_path):
        first = init_qda_mode_manager({
            "qda_mode": {"enabled": True},
            "task_dir": str(tmp_path),
        })
        second = init_qda_mode_manager({
            "qda_mode": {"enabled": True},
            "task_dir": str(tmp_path),
        })
        assert first is second

    def test_clear_resets_singleton(self, tmp_path):
        init_qda_mode_manager({
            "qda_mode": {"enabled": True},
            "task_dir": str(tmp_path),
        })
        clear_qda_mode_manager()
        assert get_qda_mode_manager() is None

    def test_invalid_config_does_not_init(self):
        result = init_qda_mode_manager({
            "qda_mode": {
                "enabled": True,
                "codebook": {"mode": "nonsense"},
            },
        })
        assert result is None
        assert get_qda_mode_manager() is None


class TestRoutes:
    @pytest.fixture
    def app(self):
        a = Flask(__name__)
        a.register_blueprint(qda_mode_bp)
        return a

    def test_blueprint_mounted_at_qda(self, app):
        with app.test_client() as client:
            resp = client.get("/qda/status")
            assert resp.status_code == 200

    def test_status_when_disabled(self, app):
        with app.test_client() as client:
            resp = client.get("/qda/status")
            assert resp.get_json() == {"enabled": False}

    def test_status_when_enabled(self, app, tmp_path):
        init_qda_mode_manager({
            "qda_mode": {"enabled": True},
            "task_dir": str(tmp_path),
        })
        with app.test_client() as client:
            data = client.get("/qda/status").get_json()
        assert data["enabled"] is True
        assert data["memos"]["enabled"] is True
        assert data["codebook"] is None
        assert data["task_dir"] == str(tmp_path)

    def test_qda_mode_required_returns_503_when_disabled(self, app):
        from potato.qda_mode.routes import qda_mode_required

        @qda_mode_required
        def guarded():
            from flask import jsonify
            return jsonify({"ok": True})

        app.add_url_rule("/qda/guarded", "guarded", guarded)
        with app.test_client() as client:
            resp = client.get("/qda/guarded")
            assert resp.status_code == 503
            assert "QDA Mode not enabled" in resp.get_json()["error"]
