from flask import url_for


def test_proxy_fix_uses_forwarded_prefix_for_static_urls(monkeypatch):
    monkeypatch.setenv("POTATO_PROXY_FIX", "1")

    from potato.flask_server import create_app

    app = create_app()
    app.add_url_rule(
        "/_static-url",
        "_static_url",
        lambda: url_for("static", filename="styles.css"),
    )

    response = app.test_client().get(
        "/_static-url",
        headers={"X-Forwarded-Prefix": "/round1"},
    )

    assert response.get_data(as_text=True) == "/round1/static/styles.css"


def test_env_url_prefix_generates_prefixed_static_urls(monkeypatch):
    monkeypatch.delenv("POTATO_PROXY_FIX", raising=False)
    monkeypatch.setenv("POTATO_URL_PREFIX", "/app1")

    from potato.flask_server import create_app

    app = create_app()
    app.add_url_rule(
        "/_static-url",
        "_static_url",
        lambda: url_for("static", filename="styles.css"),
    )

    response = app.test_client().get("/_static-url")

    assert response.get_data(as_text=True) == "/app1/static/styles.css"


def test_env_url_prefix_is_exposed_to_annotation_client(monkeypatch):
    monkeypatch.setenv("POTATO_URL_PREFIX", "/app1")

    from potato.flask_server import create_app

    app = create_app()

    with app.test_request_context("/"):
        rendered = app.jinja_env.get_template("base_template_v2.html").render(
            username="user",
            annotation_task_name="Task",
            annotation_status="unlabeled",
            finished=0,
            total_count=1,
            instance_index=0,
            instance_plain_text="",
            instance="",
            instance_id="",
            instance_record={},
            is_annotation_page=True,
            can_go_back=True,
            frontend_assets={},
            annotation_schemes=[],
            ui_config={},
            url_prefix="/app1",
        )

    assert 'url_prefix: "/app1"' in rendered
    assert "window.fetch = function(input, init)" in rendered
    assert "navigator.sendBeacon = function(url, data)" in rendered
