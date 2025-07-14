def test_home_page_debug(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"annotation" in resp.data or b"debug_user" in resp.data