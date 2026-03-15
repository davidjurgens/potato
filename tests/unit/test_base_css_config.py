from potato.server_utils.config_module import ConfigValidationError, validate_file_paths
from potato.server_utils.front_end import (
    generate_annotation_html_template,
    load_header_html,
    resolve_header_logo_src,
)


def _make_config(tmp_path, **overrides):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("annotation_task_name: Test Task\n", encoding="utf-8")

    config = {
        "__config_file__": str(config_file),
        "task_dir": str(tmp_path),
        "site_dir": str(tmp_path / "templates"),
        "annotation_task_name": "Test Task",
        "annotation_schemes": [
            {
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": ["positive", "negative"],
                "description": "Choose one",
            }
        ],
    }
    config.update(overrides)
    return config


def test_load_header_html_appends_project_base_css(tmp_path):
    header_file = tmp_path / "header.html"
    header_file.write_text("<script>console.log('header')</script>", encoding="utf-8")

    css_file = tmp_path / "custom.css"
    css_file.write_text("body { background: tomato; }", encoding="utf-8")

    config = _make_config(tmp_path, base_css="custom.css")

    header = load_header_html(config, str(header_file))

    assert "console.log('header')" in header
    assert 'id="potato-project-base-css"' in header
    assert "body { background: tomato; }" in header


def test_generate_annotation_html_template_injects_base_css(tmp_path):
    css_file = tmp_path / "annotation-base.css"
    css_file.write_text(".potato-navbar { border-bottom: 7px solid red; }", encoding="utf-8")

    config = _make_config(tmp_path, base_css="annotation-base.css")

    site_name = generate_annotation_html_template(config)
    output_file = tmp_path / "templates" / "generated" / site_name

    assert output_file.exists()
    html = output_file.read_text(encoding="utf-8")

    assert 'id="potato-project-base-css"' in html
    assert ".potato-navbar { border-bottom: 7px solid red; }" in html


def test_generate_annotation_html_template_raises_for_missing_base_css(tmp_path):
    config = _make_config(tmp_path, base_css="missing.css")

    try:
        generate_annotation_html_template(config)
    except FileNotFoundError as exc:
        assert "base_css file not found" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError for missing base_css")


def test_generate_annotation_html_template_includes_header_logo_markup(tmp_path):
    logo_file = tmp_path / "logo.svg"
    logo_file.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'></svg>",
        encoding="utf-8",
    )

    config = _make_config(tmp_path, header_logo="logo.svg")

    site_name = generate_annotation_html_template(config)
    output_file = tmp_path / "templates" / "generated" / site_name
    html = output_file.read_text(encoding="utf-8")

    assert 'class="header-logo"' in html
    assert "{{ header_logo_url }}" in html


def test_resolve_header_logo_src_returns_data_url_for_local_image(tmp_path):
    logo_file = tmp_path / "logo.svg"
    logo_file.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'></svg>",
        encoding="utf-8",
    )

    config = _make_config(tmp_path, header_logo="logo.svg")

    logo_src = resolve_header_logo_src(config)

    assert logo_src.startswith("data:image/svg+xml;base64,")


def test_validate_file_paths_rejects_missing_header_logo(tmp_path):
    config = _make_config(tmp_path, header_logo="missing.svg")

    try:
        validate_file_paths(config, str(tmp_path), str(tmp_path))
    except ConfigValidationError as exc:
        assert "header_logo file not found" in str(exc)
    else:
        raise AssertionError("Expected ConfigValidationError for missing header_logo")
