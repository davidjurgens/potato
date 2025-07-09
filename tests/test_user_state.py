def test_user_state_debug(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # Should be in annotation phase in debug mode
    assert b"annotation" in resp.data or b"debug_user" in resp.data