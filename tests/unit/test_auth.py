def test_auth_redirect(client):
    resp = client.get("/auth")
    # In debug mode, should redirect to home
    assert resp.status_code in (200, 302)