"""
Tests for project-level base_css configuration support.
"""
import os
import pytest
from tests.helpers.test_utils import create_test_directory, cleanup_test_directory


class TestBaseCssConfig:
    """Test base_css loading and resolution."""

    @pytest.fixture(autouse=True)
    def setup_test_dir(self):
        self.test_dir = create_test_directory("base_css_test")
        yield
        cleanup_test_directory(self.test_dir)

    def _make_config(self, base_css=None):
        """Build a minimal config dict for testing."""
        config = {
            "__config_file__": os.path.join(self.test_dir, "config.yaml"),
            "task_dir": self.test_dir,
        }
        if base_css is not None:
            config["base_css"] = base_css
        return config

    def test_loads_css_file(self):
        """base_css should be read and wrapped in <style> tags."""
        from potato.server_utils.front_end import load_project_base_css_html

        css_file = os.path.join(self.test_dir, "custom.css")
        with open(css_file, "w") as f:
            f.write("body { background: red; }")

        config = self._make_config(base_css="custom.css")
        result = load_project_base_css_html(config)

        assert '<style id="potato-project-base-css">' in result
        assert "body { background: red; }" in result
        assert "</style>" in result

    def test_missing_file_raises(self):
        """A configured but missing CSS file should raise FileNotFoundError."""
        from potato.server_utils.front_end import load_project_base_css_html

        config = self._make_config(base_css="nonexistent.css")
        with pytest.raises(FileNotFoundError):
            load_project_base_css_html(config)

    def test_not_configured_returns_empty(self):
        """No base_css in config should return empty string."""
        from potato.server_utils.front_end import load_project_base_css_html

        config = self._make_config()
        result = load_project_base_css_html(config)
        assert result == ""

    def test_resolve_project_asset_path_security(self):
        """Paths resolved by resolve_project_asset_path should only find existing files."""
        from potato.server_utils.front_end import resolve_project_asset_path

        config = self._make_config()
        # Non-existent file should raise
        with pytest.raises(FileNotFoundError):
            resolve_project_asset_path(config, "../../etc/passwd")

        # Existing file should resolve
        css_file = os.path.join(self.test_dir, "real.css")
        with open(css_file, "w") as f:
            f.write("h1 { color: blue; }")
        result = resolve_project_asset_path(config, "real.css")
        assert os.path.exists(result)
