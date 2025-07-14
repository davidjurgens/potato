def test_home_page_debug(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Test Annotation Task" in resp.data