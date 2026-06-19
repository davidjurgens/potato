from flask import render_template_string, url_for


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
    # Live-agent SSE streams must also be prefixed.
    assert "window.EventSource = function(url, config)" in rendered


def test_context_processor_derives_client_prefix_from_forwarded_prefix(monkeypatch):
    """ProxyFix mode must also fix client-side calls, not just url_for().

    The annotation client reads window.config.url_prefix to prefix fetch /
    sendBeacon / EventSource. That value comes from request.script_root, which
    ProxyFix populates from X-Forwarded-Prefix. Without this, ProxyFix would fix
    CSS/JS asset tags but leave autosave POSTs hitting the public root.
    """
    monkeypatch.setenv("POTATO_PROXY_FIX", "1")
    monkeypatch.delenv("POTATO_URL_PREFIX", raising=False)

    from potato.flask_server import create_app

    app = create_app()
    app.add_url_rule(
        "/_client-prefix",
        "_client_prefix",
        lambda: render_template_string("{{ url_prefix }}"),
    )

    response = app.test_client().get(
        "/_client-prefix",
        headers={"X-Forwarded-Prefix": "/round1"},
    )

    assert response.get_data(as_text=True) == "/round1"


def test_forwarded_prefix_wins_over_env_prefix(monkeypatch):
    """When both mechanisms are configured, the per-request forwarded prefix
    takes precedence over the static env prefix (StaticPrefixMiddleware only
    fills SCRIPT_NAME when it is empty, and ProxyFix runs first)."""
    monkeypatch.setenv("POTATO_PROXY_FIX", "1")
    monkeypatch.setenv("POTATO_URL_PREFIX", "/app1")

    from potato.flask_server import create_app

    app = create_app()
    app.add_url_rule(
        "/_client-prefix",
        "_client_prefix",
        lambda: render_template_string("{{ url_prefix }}"),
    )

    response = app.test_client().get(
        "/_client-prefix",
        headers={"X-Forwarded-Prefix": "/round1"},
    )

    assert response.get_data(as_text=True) == "/round1"
